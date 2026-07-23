from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import db
from models import Loan, LoanPayment, Notification
from blueprints.loans.forms import LoanForm, LoanPaymentForm

loans_bp = Blueprint("loans", __name__, template_folder="../../templates/loans")


@loans_bp.route("/")
@login_required
def list_view():
    loans = current_user.loans.order_by(Loan.created_at.desc()).all()
    rows = [{"loan": l, "emi": l.emi_amount(), "paid": l.paid_amount(), "remaining": l.remaining_amount(), "percent": l.percent_paid()} for l in loans]
    total_remaining = sum(r["remaining"] for r in rows if not r["loan"].is_closed)
    return render_template("loans/list.html", rows=rows, total_remaining=total_remaining)


@loans_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = LoanForm()
    if request.method == "GET":
        form.start_date.data = date.today()
    if form.validate_on_submit():
        loan = Loan(
            user_id=current_user.id, name=form.name.data, bank=form.bank.data,
            principal=form.principal.data, interest_rate=form.interest_rate.data,
            tenure_months=form.tenure_months.data, start_date=form.start_date.data,
        )
        db.session.add(loan)
        db.session.commit()
        flash(f"Loan added — EMI comes to ₹{loan.emi_amount():,.2f}/month.", "success")
        return redirect(url_for("loans.list_view"))
    return render_template("loans/form.html", form=form, mode="create")


@loans_bp.route("/<int:loan_id>")
@login_required
def detail(loan_id):
    loan = current_user.loans.filter_by(id=loan_id).first_or_404()
    payments = loan.payments.order_by(LoanPayment.paid_on.desc()).all()
    schedule = loan.amortization_schedule()
    payment_form = LoanPaymentForm()
    payment_form.paid_on.data = date.today()
    return render_template("loans/detail.html", loan=loan, payments=payments, schedule=schedule, form=payment_form)


@loans_bp.route("/<int:loan_id>/pay", methods=["POST"])
@login_required
def record_payment(loan_id):
    loan = current_user.loans.filter_by(id=loan_id).first_or_404()
    form = LoanPaymentForm()
    if form.validate_on_submit():
        db.session.add(LoanPayment(loan_id=loan.id, amount=form.amount.data, paid_on=form.paid_on.data, note=form.note.data))
        db.session.commit()
        if loan.remaining_amount() <= 0 and not loan.is_closed:
            loan.is_closed = True
            db.session.add(Notification(user_id=current_user.id, kind="loan", title=f"{loan.name} fully paid off", body="Congratulations — this loan is now closed.", link=url_for("loans.detail", loan_id=loan.id)))
            db.session.commit()
        flash("Payment recorded.", "success")
    else:
        flash("Couldn't record that payment — check the amount and date.", "error")
    return redirect(url_for("loans.detail", loan_id=loan.id))


@loans_bp.route("/<int:loan_id>/delete", methods=["POST"])
@login_required
def delete(loan_id):
    loan = current_user.loans.filter_by(id=loan_id).first_or_404()
    db.session.delete(loan)
    db.session.commit()
    flash("Loan deleted.", "info")
    return redirect(url_for("loans.list_view"))


@loans_bp.route("/calculator", methods=["GET", "POST"])
@login_required
def calculator():
    """Standalone EMI calculator — doesn't save anything, just computes."""
    result = None
    if request.method == "POST":
        try:
            principal = float(request.form.get("principal", 0))
            rate = float(request.form.get("rate", 0))
            months = int(request.form.get("months", 0))
            r = rate / 12 / 100
            if months > 0:
                emi = principal / months if r == 0 else principal * r * (1 + r) ** months / ((1 + r) ** months - 1)
                result = {
                    "emi": round(emi, 2),
                    "total_payable": round(emi * months, 2),
                    "total_interest": round(emi * months - principal, 2),
                }
        except (ValueError, ZeroDivisionError):
            flash("Enter valid numbers for principal, rate, and tenure.", "error")
    return render_template("loans/calculator.html", result=result)
