from datetime import date

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user

from extensions import db
from models import Expense, Category, Budget, Notification
from blueprints.expenses.forms import ExpenseForm

expenses_bp = Blueprint("expenses", __name__, template_folder="../../templates/expenses")


def _category_choices():
    return [(c.id, f"{c.icon} {c.name}") for c in current_user.categories.order_by(Category.name)]


def _check_budget_alerts(category_id):
    """Notify (once) when an expense pushes a budget to/over 100% — real
    event, not a placeholder. Dedup: skip if that exact budget already has
    an unread alert, so one purchase spree doesn't spam ten notifications."""
    budgets = current_user.budgets.filter(
        (Budget.category_id == category_id) | (Budget.category_id.is_(None))
    ).all()
    for budget in budgets:
        if budget.percent_used() < 100:
            continue
        already_alerted = current_user.notifications.filter_by(
            kind="budget", is_read=False, title=f"{budget.name} exceeded"
        ).first()
        if already_alerted:
            continue
        db.session.add(Notification(
            user_id=current_user.id, kind="budget",
            title=f"{budget.name} exceeded",
            body=f"You've spent ₹{budget.spent_amount():,.2f} of your ₹{float(budget.amount):,.2f} {budget.period} budget.",
            link=url_for("budgets.list_view"),
        ))
        db.session.commit()


@expenses_bp.route("/")
@login_required
def list_view():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    payment_method = request.args.get("payment_method", "")

    query = current_user.expenses
    if q:
        query = query.filter(Expense.description.ilike(f"%{q}%"))
    if category_id:
        query = query.filter(Expense.category_id == category_id)
    if payment_method:
        query = query.filter(Expense.payment_method == payment_method)

    expenses = query.order_by(Expense.spent_on.desc(), Expense.created_at.desc()).all()
    total = sum(float(e.amount) for e in expenses)

    return render_template(
        "expenses/list.html",
        expenses=expenses,
        total=total,
        categories=current_user.categories.order_by(Category.name).all(),
        q=q,
        selected_category=category_id,
        selected_payment=payment_method,
    )


@expenses_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = ExpenseForm()
    form.category_id.choices = _category_choices()
    if request.method == "GET":
        form.spent_on.data = date.today()

    if form.validate_on_submit():
        expense = Expense(
            user_id=current_user.id,
            amount=form.amount.data,
            category_id=form.category_id.data,
            description=form.description.data,
            payment_method=form.payment_method.data,
            location=form.location.data,
            tags=form.tags.data,
            spent_on=form.spent_on.data,
            is_recurring=form.is_recurring.data,
            recurring_interval=form.recurring_interval.data or None,
        )
        db.session.add(expense)
        db.session.commit()
        _check_budget_alerts(expense.category_id)
        flash("Expense added.", "success")
        return redirect(url_for("expenses.list_view"))

    return render_template("expenses/form.html", form=form, mode="create")


@expenses_bp.route("/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit(expense_id):
    expense = current_user.expenses.filter_by(id=expense_id).first_or_404()
    form = ExpenseForm(obj=expense)
    form.category_id.choices = _category_choices()

    if form.validate_on_submit():
        form.populate_obj(expense)
        db.session.commit()
        _check_budget_alerts(expense.category_id)
        flash("Expense updated.", "success")
        return redirect(url_for("expenses.list_view"))

    return render_template("expenses/form.html", form=form, mode="edit", expense=expense)


@expenses_bp.route("/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete(expense_id):
    expense = current_user.expenses.filter_by(id=expense_id).first_or_404()
    db.session.delete(expense)
    db.session.commit()
    flash("Expense deleted.", "info")
    return redirect(url_for("expenses.list_view"))


@expenses_bp.route("/<int:expense_id>/duplicate", methods=["POST"])
@login_required
def duplicate(expense_id):
    original = current_user.expenses.filter_by(id=expense_id).first_or_404()
    copy = Expense(
        user_id=current_user.id,
        amount=original.amount,
        category_id=original.category_id,
        description=original.description,
        payment_method=original.payment_method,
        location=original.location,
        tags=original.tags,
        spent_on=date.today(),
    )
    db.session.add(copy)
    db.session.commit()
    flash("Expense duplicated.", "success")
    return redirect(url_for("expenses.list_view"))


@expenses_bp.route("/export.csv")
@login_required
def export_csv():
    import csv
    import io
    from flask import Response

    expenses = current_user.expenses.order_by(Expense.spent_on.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Category", "Description", "Payment Method", "Amount"])
    for e in expenses:
        writer.writerow([
            e.spent_on.isoformat(),
            e.category.name if e.category else "",
            e.description or "",
            e.payment_method or "",
            float(e.amount),
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )
