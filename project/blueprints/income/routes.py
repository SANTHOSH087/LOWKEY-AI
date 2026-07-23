from datetime import date
from calendar import monthrange

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models import Income
from blueprints.income.forms import IncomeForm

income_bp = Blueprint("income", __name__, template_folder="../../templates/income")


@income_bp.route("/")
@login_required
def list_view():
    incomes = current_user.incomes.order_by(Income.received_on.desc()).all()
    total = sum(float(i.amount) for i in incomes)

    today = date.today()
    month_start = today.replace(day=1)
    month_end = today.replace(day=monthrange(today.year, today.month)[1])
    monthly_total = float(
        db.session.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == current_user.id, Income.received_on.between(month_start, month_end))
        .scalar()
    )

    by_source = (
        db.session.query(Income.source, func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == current_user.id)
        .group_by(Income.source)
        .all()
    )

    return render_template(
        "income/list.html",
        incomes=incomes,
        total=total,
        monthly_total=monthly_total,
        by_source=by_source,
    )


@income_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = IncomeForm()
    if not form.received_on.data:
        form.received_on.data = date.today()

    if form.validate_on_submit():
        income = Income(
            user_id=current_user.id,
            amount=form.amount.data,
            source=form.source.data,
            description=form.description.data,
            received_on=form.received_on.data,
            is_recurring=form.is_recurring.data,
        )
        db.session.add(income)
        db.session.commit()
        flash("Income added.", "success")
        return redirect(url_for("income.list_view"))

    return render_template("income/form.html", form=form, mode="create")


@income_bp.route("/<int:income_id>/edit", methods=["GET", "POST"])
@login_required
def edit(income_id):
    income = current_user.incomes.filter_by(id=income_id).first_or_404()
    form = IncomeForm(obj=income)

    if form.validate_on_submit():
        form.populate_obj(income)
        db.session.commit()
        flash("Income updated.", "success")
        return redirect(url_for("income.list_view"))

    return render_template("income/form.html", form=form, mode="edit", income=income)


@income_bp.route("/<int:income_id>/delete", methods=["POST"])
@login_required
def delete(income_id):
    income = current_user.incomes.filter_by(id=income_id).first_or_404()
    db.session.delete(income)
    db.session.commit()
    flash("Income deleted.", "info")
    return redirect(url_for("income.list_view"))
