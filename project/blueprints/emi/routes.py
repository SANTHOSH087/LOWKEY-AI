from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from models import EMI, EMIPayment, Notification
from blueprints.emi.forms import EMIForm, EMIPaymentForm

emi_bp = Blueprint("emi", __name__, template_folder="../../templates/emi")


@emi_bp.route("/")
@login_required
def list_view():
    emis = current_user.emis.order_by(EMI.created_at.desc()).all()
    total_pending = sum(e.pending_amount() for e in emis if not e.is_completed)
    return render_template("emi/list.html", emis=emis, total_pending=total_pending)


@emi_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = EMIForm()
    if request.method == "GET":
        form.start_date.data = date.today()
        form.installments_paid.data = 0
    if form.validate_on_submit():
        emi = EMI(
            user_id=current_user.id, name=form.name.data, bank=form.bank.data,
            interest_rate=form.interest_rate.data, monthly_amount=form.monthly_amount.data,
            total_installments=form.total_installments.data,
            installments_paid=form.installments_paid.data or 0,
            due_day=form.due_day.data, start_date=form.start_date.data,
        )
        if emi.installments_paid >= emi.total_installments:
            emi.is_completed = True
        db.session.add(emi)
        db.session.commit()
        flash("EMI added.", "success")
        return redirect(url_for("emi.list_view"))
    return render_template("emi/form.html", form=form, mode="create")


@emi_bp.route("/<int:emi_id>")
@login_required
def detail(emi_id):
    emi = current_user.emis.filter_by(id=emi_id).first_or_404()
    payments = emi.payments.order_by(EMIPayment.paid_on.desc()).all()
    form = EMIPaymentForm()
    form.paid_on.data = date.today()
    form.amount.data = emi.monthly_amount
    return render_template("emi/detail.html", emi=emi, payments=payments, form=form)


@emi_bp.route("/<int:emi_id>/pay", methods=["POST"])
@login_required
def record_payment(emi_id):
    emi = current_user.emis.filter_by(id=emi_id).first_or_404()
    if emi.is_completed:
        flash("This EMI is already fully paid.", "info")
        return redirect(url_for("emi.detail", emi_id=emi.id))

    form = EMIPaymentForm()
    if form.validate_on_submit():
        db.session.add(EMIPayment(emi_id=emi.id, amount=form.amount.data, paid_on=form.paid_on.data))
        emi.installments_paid += 1
        if emi.installments_paid >= emi.total_installments:
            emi.is_completed = True
            db.session.add(Notification(user_id=current_user.id, kind="emi", title=f"{emi.name} completed", body="All installments paid — nice work.", link=url_for("emi.detail", emi_id=emi.id)))
        db.session.commit()
        flash("Installment recorded.", "success")
    else:
        flash("Couldn't record that payment.", "error")
    return redirect(url_for("emi.detail", emi_id=emi.id))


@emi_bp.route("/<int:emi_id>/edit", methods=["GET", "POST"])
@login_required
def edit(emi_id):
    emi = current_user.emis.filter_by(id=emi_id).first_or_404()
    form = EMIForm(obj=emi)
    if form.validate_on_submit():
        form.populate_obj(emi)
        emi.is_completed = emi.installments_paid >= emi.total_installments
        db.session.commit()
        flash("EMI updated.", "success")
        return redirect(url_for("emi.detail", emi_id=emi.id))
    return render_template("emi/form.html", form=form, mode="edit", emi=emi)


@emi_bp.route("/<int:emi_id>/delete", methods=["POST"])
@login_required
def delete(emi_id):
    emi = current_user.emis.filter_by(id=emi_id).first_or_404()
    db.session.delete(emi)
    db.session.commit()
    flash("EMI deleted.", "info")
    return redirect(url_for("emi.list_view"))
