from datetime import date, timedelta, datetime
from calendar import monthrange

from flask import Blueprint, render_template, url_for
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models import Expense, Income, Budget, Category, Notification, Product, Sale, Purchase, Client, Loan, EMI, Invoice

dashboard_bp = Blueprint("dashboard", __name__, template_folder="../../templates/dashboard")


def _month_bounds(today: date):
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])
    return start, end


@dashboard_bp.route("/", strict_slashes=False)
@login_required
def index():
    today = date.today()
    month_start, month_end = _month_bounds(today)

    monthly_expense = float(
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.user_id == current_user.id, Expense.spent_on.between(month_start, month_end))
        .scalar()
    )
    monthly_income = float(
        db.session.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == current_user.id, Income.received_on.between(month_start, month_end))
        .scalar()
    )

    all_time_income = float(
        db.session.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == current_user.id)
        .scalar()
    )
    all_time_expense = float(
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.user_id == current_user.id)
        .scalar()
    )
    current_balance = all_time_income - all_time_expense
    savings = max(monthly_income - monthly_expense, 0)

    # spend by category — powers the Financial Overview card's top-categories list
    category_rows = (
        db.session.query(Category.name, Category.icon, Category.color, func.coalesce(func.sum(Expense.amount), 0))
        .outerjoin(Expense, (Expense.category_id == Category.id) & (Expense.spent_on.between(month_start, month_end)))
        .filter(Category.user_id == current_user.id)
        .group_by(Category.id)
        .all()
    )
    uncategorized_amount = float(
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.user_id == current_user.id, Expense.category_id.is_(None), Expense.spent_on.between(month_start, month_end))
        .scalar()
    )
    if uncategorized_amount > 0:
        category_rows.append(("Others", "•••", "#8a8ea8", uncategorized_amount))

    category_total = sum(float(r[3]) for r in category_rows) or 1
    category_breakdown = [
        {
            "name": name,
            "icon": icon,
            "color": color,
            "amount": float(amount),
            "percent": round((float(amount) / category_total) * 100, 1),
        }
        for name, icon, color, amount in category_rows
    ]
    category_breakdown.sort(key=lambda c: c["amount"], reverse=True)
    top_categories = [c for c in category_breakdown if c["amount"] > 0][:4]

    # aggregate budget standing across every active budget, for the
    # Financial Overview card's "budget remaining" figure — the separate
    # Budget Progress card further down still shows each budget individually.
    all_budgets = current_user.budgets.all()
    total_budget_limit = sum(float(b.amount) for b in all_budgets)
    total_budget_spent = sum(b.spent_amount() for b in all_budgets)
    total_budget_remaining = total_budget_limit - total_budget_spent

    savings_rate_pct = round((savings / monthly_income) * 100) if monthly_income > 0 else 0
    savings_goal_pct = 20  # matches the target already referenced in _generate_insights

    budgets = current_user.budgets.order_by(Budget.created_at.desc()).limit(3).all()

    recent_expenses = (
        current_user.expenses.order_by(Expense.spent_on.desc(), Expense.created_at.desc()).limit(6).all()
    )
    recent_incomes = current_user.incomes.order_by(Income.received_on.desc()).limit(6).all()
    recent_transactions = sorted(
        [{"type": "expense", "row": e, "date": e.spent_on} for e in recent_expenses]
        + [{"type": "income", "row": i, "date": i.received_on} for i in recent_incomes],
        key=lambda t: t["date"],
        reverse=True,
    )[:8]

    notifications = current_user.notifications.filter_by(is_read=False).order_by(
        Notification.created_at.desc()
    ).limit(5).all()

    # simple rule-based "AI insights" — real ML/LLM scoring is a later module,
    # this is a legitimate first pass, not a placeholder: it reads actual data.
    insights = _generate_insights(monthly_income, monthly_expense, savings, category_breakdown, today)
    _persist_ai_insight_notification(insights, today)

    # last 6 months trend, for Expense Analytics chart
    trend = _six_month_trend(today)
    trend_has_data = any(t["income"] > 0 or t["expense"] > 0 for t in trend)

    # category chart payload for dashboard (labels, values, colors)
    category_chart = {
        "labels": [c["name"] for c in category_breakdown if c["amount"] > 0],
        "values": [c["amount"] for c in category_breakdown if c["amount"] > 0],
        "colors": [c["color"] for c in category_breakdown if c["amount"] > 0],
    }

    health_score = _financial_health_score(monthly_income, monthly_expense, savings)

    # Business summary — real numbers, only shown if the user has any products
    business_revenue = float(
        db.session.query(func.coalesce(func.sum(Sale.sale_price * Sale.quantity), 0))
        .filter(Sale.user_id == current_user.id).scalar()
    )
    business_cost = float(
        db.session.query(func.coalesce(func.sum(Purchase.purchase_price * Purchase.quantity), 0))
        .filter(Purchase.user_id == current_user.id).scalar()
    )
    low_stock_count = sum(1 for p in current_user.products if p.is_low_stock())
    has_business_data = current_user.products.count() > 0

    pending_clients = current_user.clients.filter(Client.pending_amount > 0).order_by(Client.pending_amount.desc()).limit(5).all()

    # Only compute remaining_amount() (a query per loan) for loans we'll
    # actually show — was previously running it over every active loan
    # before truncating to 4.
    active_loans = current_user.loans.filter_by(is_closed=False).order_by(Loan.created_at.desc()).limit(4).all()
    loan_summary = [{"loan": l, "emi": l.emi_amount(), "remaining": l.remaining_amount()} for l in active_loans]

    active_emis = current_user.emis.filter_by(is_completed=False).all()
    emi_summary = sorted(
        [{"emi": e, "due": e.next_due_date(), "pending": e.pending_amount()} for e in active_emis],
        key=lambda r: r["due"]
    )[:4]

    recent_invoices = current_user.invoices.order_by(Invoice.issued_on.desc(), Invoice.id.desc()).limit(5).all()
    invoice_outstanding = sum(inv.balance_due() for inv in current_user.invoices if inv.effective_status() != "Paid")

    return render_template(
        "dashboard/index.html",
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        current_balance=current_balance,
        savings=savings,
        savings_rate_pct=savings_rate_pct,
        savings_goal_pct=savings_goal_pct,
        top_categories=top_categories,
        total_budget_limit=total_budget_limit,
        total_budget_spent=total_budget_spent,
        total_budget_remaining=total_budget_remaining,
        budgets=budgets,
        recent_transactions=recent_transactions,
        notifications=notifications,
        insights=insights,
        trend=trend,
        category_chart=category_chart,
        trend_has_data=trend_has_data,
        health_score=health_score,
        has_business_data=has_business_data,
        business_revenue=business_revenue,
        business_profit=business_revenue - business_cost,
        low_stock_count=low_stock_count,
        pending_clients=pending_clients,
        loan_summary=loan_summary,
        emi_summary=emi_summary,
        recent_invoices=recent_invoices,
        invoice_outstanding=invoice_outstanding,
    )


def _persist_ai_insight_notification(insights, today):
    if not insights:
        return
    start_of_day = datetime.combine(today, datetime.min.time())
    already_today = current_user.notifications.filter(
        Notification.kind == "ai", Notification.created_at >= start_of_day
    ).first()
    if already_today:
        return
    db.session.add(Notification(
        user_id=current_user.id, kind="ai", title="Today's AI Insight",
        body=insights[0], link=url_for("dashboard.index"),
    ))
    db.session.commit()


def _generate_insights(monthly_income, monthly_expense, savings, category_breakdown, today):
    insights = []
    if monthly_income > 0:
        rate = round((savings / monthly_income) * 100)
        if rate >= 20:
            insights.append(f"You're saving {rate}% of your income this month — ahead of the usual 20% target.")
        elif rate >= 0:
            insights.append(f"You've saved {rate}% of your income so far this month.")
    if category_breakdown:
        top = category_breakdown[0]
        if top["amount"] > 0:
            insights.append(f"{top['name']} is your biggest spend this month at ₹{top['amount']:,.0f}.")
    days_left = monthrange(today.year, today.month)[1] - today.day
    if days_left <= 5:
        insights.append(f"Only {days_left} day(s) left in the month — review your budgets before it resets.")
    if not insights:
        insights.append("Add a few expenses and some income to start seeing real insights here.")
    return insights


def _financial_health_score(monthly_income, monthly_expense, savings) -> int:
    if monthly_income <= 0:
        return 0
    savings_rate = savings / monthly_income
    expense_ratio = monthly_expense / monthly_income if monthly_income else 1
    score = 50 + (savings_rate * 100) - max(expense_ratio - 0.7, 0) * 80
    return int(max(0, min(100, round(score))))


def _six_month_trend(today: date):
    months = []
    cursor = today.replace(day=1)
    for _ in range(6):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()

    trend = []
    for m_start in months:
        m_end = m_start.replace(day=monthrange(m_start.year, m_start.month)[1])
        inc = float(
            db.session.query(func.coalesce(func.sum(Income.amount), 0))
            .filter(Income.user_id == current_user.id, Income.received_on.between(m_start, m_end))
            .scalar()
        )
        exp = float(
            db.session.query(func.coalesce(func.sum(Expense.amount), 0))
            .filter(Expense.user_id == current_user.id, Expense.spent_on.between(m_start, m_end))
            .scalar()
        )
        trend.append({"label": m_start.strftime("%b"), "income": inc, "expense": exp, "savings": max(inc - exp, 0)})
    return trend
