"""
Core reports logic. One function builds the data for a given (report_type,
period) pair; the page view and all three exporters (PDF/Excel/CSV) call
the exact same function, so "what you see is what you export" instead of
three separately-maintained (and inevitably drifting) implementations.
"""
from datetime import date, timedelta
from calendar import monthrange

from sqlalchemy import func

from extensions import db
from models import (
    Expense, Income, Category, Sale, Purchase, Loan, LoanPayment,
    EMI, EMIPayment, Budget,
)

REPORT_TYPES = ["expense", "income", "business", "loan", "emi", "category", "summary"]
PERIODS = ["daily", "weekly", "monthly", "yearly", "custom"]


def resolve_period(period: str, custom_start: str = None, custom_end: str = None):
    """Returns (start_date, end_date, label) for a named period, or a
    custom range. Falls back to 'monthly' for anything unrecognized rather
    than erroring, since this is driven by a query string a user can edit."""
    today = date.today()

    if period == "daily":
        return today, today, today.strftime("%d %b %Y")

    if period == "weekly":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end, f"Week of {start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"

    if period == "yearly":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
        return start, end, str(today.year)

    if period == "custom" and custom_start and custom_end:
        try:
            start = date.fromisoformat(custom_start)
            end = date.fromisoformat(custom_end)
            if start > end:
                start, end = end, start
            return start, end, f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
        except ValueError:
            pass  # fall through to monthly default below

    # "monthly" and any unrecognized/incomplete-custom value
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])
    return start, end, start.strftime("%B %Y")


def build_report(user, report_type: str, start: date, end: date) -> dict:
    if report_type not in REPORT_TYPES:
        report_type = "summary"
    builder = {
        "expense": _expense_report,
        "income": _income_report,
        "business": _business_report,
        "loan": _loan_report,
        "emi": _emi_report,
        "category": _category_report,
        "summary": _summary_report,
    }[report_type]
    return builder(user, start, end)


def _expense_report(user, start, end):
    expenses = user.expenses.filter(Expense.spent_on.between(start, end)).order_by(Expense.spent_on).all()
    total = sum(float(e.amount) for e in expenses)
    days = max((end - start).days + 1, 1)

    by_category = {}
    for e in expenses:
        name = e.category.name if e.category else "Others"
        by_category[name] = by_category.get(name, 0) + float(e.amount)
    top_category = max(by_category.items(), key=lambda kv: kv[1])[0] if by_category else "—"

    return {
        "type": "expense",
        "summary": {
            "Total Expenses": f"₹{total:,.2f}",
            "Transactions": len(expenses),
            "Average per Day": f"₹{total/days:,.2f}",
            "Top Category": top_category,
        },
        "table_headers": ["Date", "Category", "Description", "Payment Method", "Amount"],
        "table_rows": [
            [e.spent_on.isoformat(), e.category.name if e.category else "Others",
             e.description or "", e.payment_method or "", float(e.amount)]
            for e in expenses
        ],
        "charts": {
            "category_pie": {"labels": list(by_category.keys()), "values": list(by_category.values())},
            "trend": _daily_series(expenses, "spent_on", start, end),
        },
    }


def _income_report(user, start, end):
    incomes = user.incomes.filter(Income.received_on.between(start, end)).order_by(Income.received_on).all()
    total = sum(float(i.amount) for i in incomes)

    by_source = {}
    for i in incomes:
        by_source[i.source] = by_source.get(i.source, 0) + float(i.amount)

    return {
        "type": "income",
        "summary": {
            "Total Income": f"₹{total:,.2f}",
            "Transactions": len(incomes),
            "Top Source": max(by_source.items(), key=lambda kv: kv[1])[0] if by_source else "—",
        },
        "table_headers": ["Date", "Source", "Description", "Amount"],
        "table_rows": [
            [i.received_on.isoformat(), i.source, i.description or "", float(i.amount)]
            for i in incomes
        ],
        "charts": {
            "source_pie": {"labels": list(by_source.keys()), "values": list(by_source.values())},
            "trend": _daily_series(incomes, "received_on", start, end),
        },
    }


def _business_report(user, start, end):
    sales = user.sales.filter(Sale.sold_on.between(start, end)).order_by(Sale.sold_on).all()
    purchases = user.purchases.filter(Purchase.purchased_on.between(start, end)).all()
    revenue = sum(s.revenue() for s in sales)
    cost = sum(p.cost() for p in purchases)

    return {
        "type": "business",
        "summary": {
            "Revenue": f"₹{revenue:,.2f}",
            "Cost of Goods": f"₹{cost:,.2f}",
            "Profit" if revenue >= cost else "Loss": f"₹{abs(revenue - cost):,.2f}",
            "Sales Count": len(sales),
        },
        "table_headers": ["Date", "Product", "Qty", "Unit Price", "Total"],
        "table_rows": [
            [s.sold_on.isoformat(), s.product.name, s.quantity, float(s.sale_price), s.revenue()]
            for s in sales
        ],
        "charts": {
            "revenue_trend": _daily_series(sales, "sold_on", start, end, value_fn=lambda s: s.revenue()),
        },
    }


def _loan_report(user, start, end):
    payments = (
        db.session.query(LoanPayment, Loan)
        .join(Loan, LoanPayment.loan_id == Loan.id)
        .filter(Loan.user_id == user.id, LoanPayment.paid_on.between(start, end))
        .order_by(LoanPayment.paid_on)
        .all()
    )
    total_paid = sum(float(p.amount) for p, l in payments)
    active_loans = user.loans.filter_by(is_closed=False).all()
    total_remaining = sum(l.remaining_amount() for l in active_loans)

    return {
        "type": "loan",
        "summary": {
            "Paid This Period": f"₹{total_paid:,.2f}",
            "Active Loans": len(active_loans),
            "Total Remaining (all active loans)": f"₹{total_remaining:,.2f}",
        },
        "table_headers": ["Date", "Loan", "Note", "Amount"],
        "table_rows": [
            [p.paid_on.isoformat(), l.name, p.note or "", float(p.amount)]
            for p, l in payments
        ],
        "charts": {
            "by_loan": _group_sum([(l.name, float(p.amount)) for p, l in payments]),
        },
    }


def _emi_report(user, start, end):
    payments = (
        db.session.query(EMIPayment, EMI)
        .join(EMI, EMIPayment.emi_id == EMI.id)
        .filter(EMI.user_id == user.id, EMIPayment.paid_on.between(start, end))
        .order_by(EMIPayment.paid_on)
        .all()
    )
    total_paid = sum(float(p.amount) for p, e in payments)
    active_emis = user.emis.filter_by(is_completed=False).all()
    total_pending = sum(e.pending_amount() for e in active_emis)

    return {
        "type": "emi",
        "summary": {
            "Paid This Period": f"₹{total_paid:,.2f}",
            "Active EMIs": len(active_emis),
            "Total Pending (all active EMIs)": f"₹{total_pending:,.2f}",
        },
        "table_headers": ["Date", "EMI", "Amount"],
        "table_rows": [[p.paid_on.isoformat(), e.name, float(p.amount)] for p, e in payments],
        "charts": {
            "by_emi": _group_sum([(e.name, float(p.amount)) for p, e in payments]),
        },
    }


def _category_report(user, start, end):
    rows = (
        db.session.query(Category.name, Category.icon, func.coalesce(func.sum(Expense.amount), 0))
        .outerjoin(Expense, (Expense.category_id == Category.id) & (Expense.spent_on.between(start, end)))
        .filter(Category.user_id == user.id)
        .group_by(Category.id)
        .all()
    )
    rows = [(name, icon, float(amount)) for name, icon, amount in rows if amount]
    rows.sort(key=lambda r: r[2], reverse=True)
    total = sum(r[2] for r in rows) or 1

    return {
        "type": "category",
        "summary": {"Total Categorized Spend": f"₹{total:,.2f}", "Categories Used": len(rows)},
        "table_headers": ["Category", "Amount", "% of Total"],
        "table_rows": [[f"{icon} {name}", amount, f"{round(amount / total * 100, 1)}%"] for name, icon, amount in rows],
        "charts": {"category_pie": {"labels": [r[0] for r in rows], "values": [r[2] for r in rows]}},
    }


def _summary_report(user, start, end):
    income_total = float(
        db.session.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.user_id == user.id, Income.received_on.between(start, end)).scalar()
    )
    expense_total = float(
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.user_id == user.id, Expense.spent_on.between(start, end)).scalar()
    )
    net = income_total - expense_total

    revenue = float(
        db.session.query(func.coalesce(func.sum(Sale.sale_price * Sale.quantity), 0))
        .filter(Sale.user_id == user.id, Sale.sold_on.between(start, end)).scalar()
    )
    loan_paid = float(
        db.session.query(func.coalesce(func.sum(LoanPayment.amount), 0))
        .join(Loan, LoanPayment.loan_id == Loan.id)
        .filter(Loan.user_id == user.id, LoanPayment.paid_on.between(start, end)).scalar()
    )
    emi_paid = float(
        db.session.query(func.coalesce(func.sum(EMIPayment.amount), 0))
        .join(EMI, EMIPayment.emi_id == EMI.id)
        .filter(EMI.user_id == user.id, EMIPayment.paid_on.between(start, end)).scalar()
    )

    return {
        "type": "summary",
        "summary": {
            "Income": f"₹{income_total:,.2f}",
            "Expenses": f"₹{expense_total:,.2f}",
            "Net Savings": f"₹{net:,.2f}",
            "Business Revenue": f"₹{revenue:,.2f}",
            "Loan Payments": f"₹{loan_paid:,.2f}",
            "EMI Payments": f"₹{emi_paid:,.2f}",
        },
        "table_headers": ["Metric", "Amount"],
        "table_rows": [
            ["Income", income_total], ["Expenses", expense_total], ["Net Savings", net],
            ["Business Revenue", revenue], ["Loan Payments", loan_paid], ["EMI Payments", emi_paid],
        ],
        "charts": {
            "income_vs_expense": {"labels": ["Income", "Expenses"], "values": [income_total, expense_total]},
        },
    }


def _daily_series(rows, date_attr, start, end, value_fn=None):
    """Buckets rows into a day-by-day series across the range, for trend charts."""
    totals = {}
    cursor = start
    while cursor <= end:
        totals[cursor.isoformat()] = 0.0
        cursor += timedelta(days=1)
    for r in rows:
        d = getattr(r, date_attr)
        val = value_fn(r) if value_fn else float(r.amount)
        totals[d.isoformat()] = totals.get(d.isoformat(), 0) + val
    return {"labels": list(totals.keys()), "values": list(totals.values())}


def _group_sum(pairs):
    totals = {}
    for label, value in pairs:
        totals[label] = totals.get(label, 0) + value
    return {"labels": list(totals.keys()), "values": list(totals.values())}
