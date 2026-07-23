from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, request, Response, current_app
from flask_login import login_required, current_user

from extensions import db
from models import Invoice, InvoiceItem, InvoicePayment, Client, Product, Notification
from blueprints.invoices.forms import InvoiceForm, InvoicePaymentForm
from blueprints.invoices.pdf import generate_invoice_pdf, generate_invoice_qr

invoices_bp = Blueprint("invoices", __name__, template_folder="../../templates/invoices")


def _next_invoice_number() -> str:
    year = date.today().year
    prefix = f"INV-{year}-"
    last = (
        Invoice.query.filter(Invoice.user_id == current_user.id, Invoice.invoice_number.like(f"{prefix}%"))
        .order_by(Invoice.id.desc())
        .first()
    )
    if last:
        try:
            n = int(last.invoice_number.rsplit("-", 1)[-1]) + 1
        except ValueError:
            n = 1
    else:
        n = 1
    return f"{prefix}{n:04d}"


def _parse_line_items(form_data) -> list[InvoiceItem]:
    """Line items come from JS-managed dynamic rows, not a WTForms
    FieldList — parallel arrays keyed by name, parsed and validated here."""
    descriptions = form_data.getlist("item_description[]")
    quantities = form_data.getlist("item_quantity[]")
    prices = form_data.getlist("item_unit_price[]")
    gst_rates = form_data.getlist("item_gst_rate[]")
    product_ids = form_data.getlist("item_product_id[]")

    items = []
    for i, desc in enumerate(descriptions):
        desc = desc.strip()
        if not desc:
            continue
        try:
            qty = float(quantities[i]) if i < len(quantities) and quantities[i] else 0
            price = float(prices[i]) if i < len(prices) and prices[i] else 0
            gst = float(gst_rates[i]) if i < len(gst_rates) and gst_rates[i] else 0
        except (ValueError, IndexError):
            continue
        if qty <= 0 or price < 0:
            continue
        product_id = None
        if i < len(product_ids) and product_ids[i] and product_ids[i] != "0":
            try:
                product_id = int(product_ids[i])
            except ValueError:
                product_id = None
        items.append(InvoiceItem(description=desc, quantity=qty, unit_price=price, gst_rate=gst, product_id=product_id))
    return items


def _client_choices():
    return [(0, "— No client —")] + [(c.id, c.name) for c in current_user.clients.order_by(Client.name)]


@invoices_bp.route("/")
@login_required
def list_view():
    status_filter = request.args.get("status", "")
    query = current_user.invoices
    if status_filter:
        query = query.filter(Invoice.status == status_filter)
    invoices = query.order_by(Invoice.issued_on.desc(), Invoice.id.desc()).all()

    total_outstanding = sum(inv.balance_due() for inv in current_user.invoices if inv.effective_status() != "Paid")
    return render_template("invoices/list.html", invoices=invoices, status_filter=status_filter, total_outstanding=total_outstanding)


@invoices_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = InvoiceForm()
    form.client_id.choices = _client_choices()

    if request.method == "GET":
        form.issued_on.data = date.today()
        form.status.data = "Draft"

    if form.validate_on_submit():
        items = _parse_line_items(request.form)
        if not items:
            flash("Add at least one valid line item (description, quantity, and price).", "error")
            return render_template("invoices/form.html", form=form, mode="create", products=current_user.products.all())

        invoice = Invoice(
            user_id=current_user.id,
            invoice_number=_next_invoice_number(),
            client_id=form.client_id.data or None,
            status=form.status.data,
            discount_type=form.discount_type.data,
            discount_value=form.discount_value.data or 0,
            notes=form.notes.data,
            issued_on=form.issued_on.data,
            due_on=form.due_on.data,
        )
        invoice.items.extend(items)
        db.session.add(invoice)
        db.session.commit()
        flash(f"Invoice {invoice.invoice_number} created.", "success")
        return redirect(url_for("invoices.detail", invoice_id=invoice.id))

    return render_template("invoices/form.html", form=form, mode="create", products=current_user.products.all())


@invoices_bp.route("/<int:invoice_id>")
@login_required
def detail(invoice_id):
    invoice = current_user.invoices.filter_by(id=invoice_id).first_or_404()
    payment_form = InvoicePaymentForm()
    payment_form.paid_on.data = date.today()
    return render_template("invoices/detail.html", invoice=invoice, form=payment_form)


@invoices_bp.route("/<int:invoice_id>/edit", methods=["GET", "POST"])
@login_required
def edit(invoice_id):
    invoice = current_user.invoices.filter_by(id=invoice_id).first_or_404()
    form = InvoiceForm(obj=invoice)
    form.client_id.choices = _client_choices()
    if request.method == "GET":
        form.client_id.data = invoice.client_id or 0

    if form.validate_on_submit():
        items = _parse_line_items(request.form)
        if not items:
            flash("Add at least one valid line item.", "error")
            return render_template("invoices/form.html", form=form, mode="edit", invoice=invoice, products=current_user.products.all())

        invoice.client_id = form.client_id.data or None
        invoice.status = form.status.data
        invoice.discount_type = form.discount_type.data
        invoice.discount_value = form.discount_value.data or 0
        invoice.notes = form.notes.data
        invoice.issued_on = form.issued_on.data
        invoice.due_on = form.due_on.data

        # replace line items wholesale — simpler and safer than diffing
        for old_item in invoice.items.all():
            db.session.delete(old_item)
        invoice.items.extend(items)
        db.session.commit()
        flash("Invoice updated.", "success")
        return redirect(url_for("invoices.detail", invoice_id=invoice.id))

    return render_template("invoices/form.html", form=form, mode="edit", invoice=invoice, products=current_user.products.all())


@invoices_bp.route("/<int:invoice_id>/delete", methods=["POST"])
@login_required
def delete(invoice_id):
    invoice = current_user.invoices.filter_by(id=invoice_id).first_or_404()
    db.session.delete(invoice)
    db.session.commit()
    flash("Invoice deleted.", "info")
    return redirect(url_for("invoices.list_view"))


@invoices_bp.route("/<int:invoice_id>/pay", methods=["POST"])
@login_required
def record_payment(invoice_id):
    invoice = current_user.invoices.filter_by(id=invoice_id).first_or_404()
    form = InvoicePaymentForm()
    if form.validate_on_submit():
        db.session.add(InvoicePayment(invoice_id=invoice.id, amount=form.amount.data, paid_on=form.paid_on.data, method=form.method.data))
        db.session.commit()
        if invoice.balance_due() <= 0 and invoice.status != "Paid":
            invoice.status = "Paid"
            db.session.add(Notification(user_id=current_user.id, kind="invoice", title=f"{invoice.invoice_number} paid in full", body=f"₹{invoice.grand_total():,.2f} received.", link=url_for("invoices.detail", invoice_id=invoice.id)))
            db.session.commit()
        flash("Payment recorded.", "success")
    else:
        flash("Couldn't record that payment.", "error")
    return redirect(url_for("invoices.detail", invoice_id=invoice.id))


@invoices_bp.route("/<int:invoice_id>/pdf")
@login_required
def download_pdf(invoice_id):
    invoice = current_user.invoices.filter_by(id=invoice_id).first_or_404()
    pdf_bytes = generate_invoice_pdf(invoice, current_user, current_app.config["CURRENCY_SYMBOL"])
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename={invoice.invoice_number}.pdf"},
    )


@invoices_bp.route("/<int:invoice_id>/qr.png")
@login_required
def qr_image(invoice_id):
    invoice = current_user.invoices.filter_by(id=invoice_id).first_or_404()
    qr_bytes = generate_invoice_qr(invoice, current_app.config["CURRENCY_SYMBOL"])
    return Response(qr_bytes, mimetype="image/png")


@invoices_bp.route("/<int:invoice_id>/print")
@login_required
def print_view(invoice_id):
    invoice = current_user.invoices.filter_by(id=invoice_id).first_or_404()
    return render_template("invoices/print.html", invoice=invoice)
