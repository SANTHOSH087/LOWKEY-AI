from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models import Product, Sale, Purchase, Supplier, Client, Notification
from blueprints.business.forms import ProductForm, SaleForm, PurchaseForm, SupplierForm

business_bp = Blueprint("business", __name__, template_folder="../../templates/business")


def _supplier_choices():
    return [(0, "— None —")] + [(s.id, s.name) for s in current_user.suppliers.order_by(Supplier.name)]


def _product_choices():
    return [(p.id, p.name) for p in current_user.products.order_by(Product.name)]


def _client_choices():
    return [(0, "— Walk-in / none —")] + [(c.id, c.name) for c in current_user.clients.order_by(Client.name)]


@business_bp.route("/")
@login_required
def index():
    products = current_user.products.order_by(Product.name).all()
    total_revenue = float(
        db.session.query(func.coalesce(func.sum(Sale.sale_price * Sale.quantity), 0))
        .filter(Sale.user_id == current_user.id).scalar()
    )
    total_cost = float(
        db.session.query(func.coalesce(func.sum(Purchase.purchase_price * Purchase.quantity), 0))
        .filter(Purchase.user_id == current_user.id).scalar()
    )
    profit = total_revenue - total_cost
    low_stock = [p for p in products if p.is_low_stock()]

    recent_sales = current_user.sales.order_by(Sale.sold_on.desc(), Sale.created_at.desc()).limit(8).all()

    inventory_value = sum(float(p.purchase_price) * p.stock_qty for p in products)

    return render_template(
        "business/index.html",
        products=products,
        total_revenue=total_revenue,
        total_cost=total_cost,
        profit=profit,
        loss=profit < 0,
        low_stock=low_stock,
        recent_sales=recent_sales,
        inventory_value=inventory_value,
    )


# ---------------- Products ----------------

@business_bp.route("/products/new", methods=["GET", "POST"])
@login_required
def product_create():
    form = ProductForm()
    form.supplier_id.choices = _supplier_choices()
    if form.validate_on_submit():
        product = Product(
            user_id=current_user.id,
            name=form.name.data,
            sku=form.sku.data,
            purchase_price=form.purchase_price.data,
            selling_price=form.selling_price.data,
            stock_qty=form.stock_qty.data,
            low_stock_threshold=form.low_stock_threshold.data,
            supplier_id=form.supplier_id.data or None,
        )
        db.session.add(product)
        db.session.commit()
        flash("Product added.", "success")
        return redirect(url_for("business.index"))
    return render_template("business/product_form.html", form=form, mode="create")


@business_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def product_edit(product_id):
    product = current_user.products.filter_by(id=product_id).first_or_404()
    form = ProductForm(obj=product)
    form.supplier_id.choices = _supplier_choices()
    if request.method == "GET":
        form.supplier_id.data = product.supplier_id or 0

    if form.validate_on_submit():
        form.populate_obj(product)
        product.supplier_id = form.supplier_id.data or None
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("business.index"))
    return render_template("business/product_form.html", form=form, mode="edit", product=product)


@business_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def product_delete(product_id):
    product = current_user.products.filter_by(id=product_id).first_or_404()
    if product.sales.count() or product.purchases.count():
        flash("Can't delete a product with sale/purchase history — it would erase those records.", "error")
        return redirect(url_for("business.index"))
    db.session.delete(product)
    db.session.commit()
    flash("Product deleted.", "info")
    return redirect(url_for("business.index"))


# ---------------- Sales ----------------

@business_bp.route("/sales/new", methods=["GET", "POST"])
@login_required
def sale_create():
    form = SaleForm()
    form.product_id.choices = _product_choices()
    form.client_id.choices = _client_choices()
    if not form.product_id.choices:
        flash("Add a product before recording a sale.", "error")
        return redirect(url_for("business.product_create"))
    if request.method == "GET":
        form.sold_on.data = date.today()

    if form.validate_on_submit():
        product = current_user.products.filter_by(id=form.product_id.data).first_or_404()
        if form.quantity.data > product.stock_qty:
            flash(f"Only {product.stock_qty} in stock — can't sell {form.quantity.data}.", "error")
            return render_template("business/sale_form.html", form=form, mode="create")

        sale = Sale(
            user_id=current_user.id,
            product_id=product.id,
            client_id=form.client_id.data or None,
            quantity=form.quantity.data,
            sale_price=form.sale_price.data,
            sold_on=form.sold_on.data,
        )
        product.stock_qty -= form.quantity.data
        db.session.add(sale)
        db.session.commit()

        if product.is_low_stock():
            db.session.add(Notification(
                user_id=current_user.id, kind="stock",
                title=f"Low stock: {product.name}",
                body=f"Only {product.stock_qty} left (threshold {product.low_stock_threshold}).",
                link=url_for("business.index"),
            ))
            db.session.commit()

        flash("Sale recorded.", "success")
        return redirect(url_for("business.index"))

    return render_template("business/sale_form.html", form=form, mode="create")


# ---------------- Purchases ----------------

@business_bp.route("/purchases/new", methods=["GET", "POST"])
@login_required
def purchase_create():
    form = PurchaseForm()
    form.product_id.choices = _product_choices()
    form.supplier_id.choices = _supplier_choices()
    if not form.product_id.choices:
        flash("Add a product before recording a purchase.", "error")
        return redirect(url_for("business.product_create"))
    if request.method == "GET":
        form.purchased_on.data = date.today()

    if form.validate_on_submit():
        product = current_user.products.filter_by(id=form.product_id.data).first_or_404()
        purchase = Purchase(
            user_id=current_user.id,
            product_id=product.id,
            supplier_id=form.supplier_id.data or None,
            quantity=form.quantity.data,
            purchase_price=form.purchase_price.data,
            purchased_on=form.purchased_on.data,
        )
        product.stock_qty += form.quantity.data
        db.session.add(purchase)
        db.session.commit()
        flash("Purchase recorded — stock updated.", "success")
        return redirect(url_for("business.index"))

    return render_template("business/purchase_form.html", form=form, mode="create")


# ---------------- Suppliers ----------------

@business_bp.route("/suppliers")
@login_required
def supplier_list():
    suppliers = current_user.suppliers.order_by(Supplier.name).all()
    return render_template("business/suppliers.html", suppliers=suppliers)


@business_bp.route("/suppliers/new", methods=["GET", "POST"])
@login_required
def supplier_create():
    form = SupplierForm()
    if form.validate_on_submit():
        db.session.add(Supplier(
            user_id=current_user.id, name=form.name.data, phone=form.phone.data,
            email=form.email.data, notes=form.notes.data,
        ))
        db.session.commit()
        flash("Supplier added.", "success")
        return redirect(url_for("business.supplier_list"))
    return render_template("business/supplier_form.html", form=form)


@business_bp.route("/suppliers/<int:supplier_id>/delete", methods=["POST"])
@login_required
def supplier_delete(supplier_id):
    supplier = current_user.suppliers.filter_by(id=supplier_id).first_or_404()
    # SQLite doesn't enforce FK constraints by default in this setup — nullify
    # references explicitly so no product is left pointing at a deleted supplier
    for product in supplier.products:
        product.supplier_id = None
    db.session.delete(supplier)
    db.session.commit()
    flash("Supplier deleted.", "info")
    return redirect(url_for("business.supplier_list"))
