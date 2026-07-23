from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from models import Budget, Category
from blueprints.budgets.forms import BudgetForm

budgets_bp = Blueprint("budgets", __name__, template_folder="../../templates/budgets")


def _category_choices():
    choices = [(0, "Overall (all categories)")]
    choices += [(c.id, f"{c.icon} {c.name}") for c in current_user.categories.order_by(Category.name)]
    return choices


@budgets_bp.route("/")
@login_required
def list_view():
    budgets = current_user.budgets.order_by(Budget.created_at.desc()).all()
    rows = [
        {
            "budget": b,
            "spent": b.spent_amount(),
            "percent": b.percent_used(),
            "remaining": max(float(b.amount) - b.spent_amount(), 0),
        }
        for b in budgets
    ]
    return render_template("budgets/list.html", rows=rows)


@budgets_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = BudgetForm()
    form.category_id.choices = _category_choices()
    if not form.period_start.data:
        form.period_start.data = date.today().replace(day=1)

    if form.validate_on_submit():
        budget = Budget(
            user_id=current_user.id,
            name=form.name.data,
            period=form.period.data,
            amount=form.amount.data,
            category_id=form.category_id.data or None,
            period_start=form.period_start.data,
        )
        db.session.add(budget)
        db.session.commit()
        flash("Budget created.", "success")
        return redirect(url_for("budgets.list_view"))

    return render_template("budgets/form.html", form=form, mode="create")


@budgets_bp.route("/<int:budget_id>/edit", methods=["GET", "POST"])
@login_required
def edit(budget_id):
    budget = current_user.budgets.filter_by(id=budget_id).first_or_404()
    form = BudgetForm(obj=budget)
    form.category_id.choices = _category_choices()
    if request_is_get_with_no_category(budget):
        form.category_id.data = budget.category_id or 0

    if form.validate_on_submit():
        form.populate_obj(budget)
        budget.category_id = form.category_id.data or None
        db.session.commit()
        flash("Budget updated.", "success")
        return redirect(url_for("budgets.list_view"))

    return render_template("budgets/form.html", form=form, mode="edit", budget=budget)


def request_is_get_with_no_category(budget):
    # small helper kept explicit rather than clever: WTForms' obj= populate
    # will set category_id to None for an "overall" budget, but the select
    # field needs the 0 sentinel to render the right option as selected.
    return budget.category_id is None


@budgets_bp.route("/<int:budget_id>/delete", methods=["POST"])
@login_required
def delete(budget_id):
    budget = current_user.budgets.filter_by(id=budget_id).first_or_404()
    db.session.delete(budget)
    db.session.commit()
    flash("Budget deleted.", "info")
    return redirect(url_for("budgets.list_view"))
