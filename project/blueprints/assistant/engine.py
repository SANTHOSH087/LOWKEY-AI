"""
Rule-based financial assistant. No LLM required — every answer here comes
from an actual SQL query against the user's real data, matched to a
question pattern via keywords. See llm.py for the optional LLM hook this
deliberately does NOT depend on.
"""
import re
from datetime import date, timedelta
from calendar import monthrange

from sqlalchemy import func

from extensions import db
from models import Expense, Income, Budget, Category, Loan, EMI, Invoice, Sale, Purchase


def _month_bounds(today):
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])
    return start, end


def _match_category(user, text):
    text_l = text.lower()
    for cat in user.categories.all():
        if cat.name.lower() in text_l:
            return cat
    return None


def _match_period(text):
    text_l = text.lower()
    today = date.today()
    if "today" in text_l:
        return today, today, "today"
    if "this week" in text_l or "week" in text_l:
        start = today - timedelta(days=today.weekday())
        return start, today, "this week"
    if "last month" in text_l:
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start, last_month_end, "last month"
    if "this year" in text_l or "year" in text_l:
        return date(today.year, 1, 1), today, "this year"
    # default: this month
    start, end = _month_bounds(today)
    return start, end, "this month"


# ---- topic handlers — each takes (user, question) and returns a response string ----

def _handle_expense(user, q):
    start, end, period_label = _match_period(q)
    category = _match_category(user, q)
    query = user.expenses.filter(Expense.spent_on.between(start, end))
    if category:
        query = query.filter(Expense.category_id == category.id)
    total = sum(float(e.amount) for e in query.all())
    count = query.count()

    if category:
        if total == 0:
            return f"You haven't spent anything on {category.name} {period_label}."
        return f"You've spent ₹{total:,.2f} on {category.name} {period_label}, across {count} transaction{'s' if count != 1 else ''}."

    if total == 0:
        return f"No expenses recorded {period_label}."
    top = (
        db.session.query(Category.name, func.sum(Expense.amount))
        .join(Expense, Expense.category_id == Category.id)
        .filter(Expense.user_id == user.id, Expense.spent_on.between(start, end))
        .group_by(Category.id).order_by(func.sum(Expense.amount).desc()).first()
    )
    top_line = f" Your biggest category was {top[0]} at ₹{float(top[1]):,.2f}." if top else ""
    return f"You've spent ₹{total:,.2f} {period_label} across {count} transaction{'s' if count != 1 else ''}.{top_line}"


def _handle_income(user, q):
    start, end, period_label = _match_period(q)
    incomes = user.incomes.filter(Income.received_on.between(start, end)).all()
    total = sum(float(i.amount) for i in incomes)
    if total == 0:
        return f"No income recorded {period_label}."
    sources = {}
    for i in incomes:
        sources[i.source] = sources.get(i.source, 0) + float(i.amount)
    top_source = max(sources.items(), key=lambda kv: kv[1])
    return f"Your income {period_label} is ₹{total:,.2f}, mostly from {top_source[0]} (₹{top_source[1]:,.2f})."


def _handle_savings(user, q):
    today = date.today()
    start, end = _month_bounds(today)
    income = sum(float(i.amount) for i in user.incomes.filter(Income.received_on.between(start, end)).all())
    expense = sum(float(e.amount) for e in user.expenses.filter(Expense.spent_on.between(start, end)).all())
    savings = income - expense
    if income <= 0:
        return "You haven't logged any income this month yet, so I can't calculate a savings rate."
    rate = round((savings / income) * 100)
    verdict = "well ahead of the usual 20% target" if rate >= 20 else "below the usual 20% target — worth a look" if rate < 10 else "on track"
    return f"You've saved ₹{savings:,.2f} this month, a {rate}% savings rate — {verdict}."


def _handle_budget(user, q):
    budgets = user.budgets.all()
    if not budgets:
        return "You don't have any budgets set up yet. Head to Budgets to create one."
    over = [b for b in budgets if b.percent_used() >= 100]
    close = [b for b in budgets if 80 <= b.percent_used() < 100]
    if over:
        names = ", ".join(f"{b.name} ({b.percent_used():.0f}%)" for b in over)
        return f"You're over budget on: {names}. Consider trimming spending there for the rest of the period."
    if close:
        names = ", ".join(f"{b.name} ({b.percent_used():.0f}%)" for b in close)
        return f"You're getting close to your limit on: {names}. Still within budget, but worth watching."
    best = min(budgets, key=lambda b: b.percent_used())
    return f"All {len(budgets)} of your budgets are within limits. {best.name} has the most room left, at {best.percent_used():.0f}% used."


def _handle_loan(user, q):
    loans = user.loans.filter_by(is_closed=False).all()
    if not loans:
        closed = user.loans.filter_by(is_closed=True).count()
        return "You have no active loans." + (f" ({closed} fully paid off — nice work.)" if closed else "")
    total_remaining = sum(l.remaining_amount() for l in loans)
    total_emi = sum(l.emi_amount() for l in loans)
    lines = "; ".join(f"{l.name}: ₹{l.remaining_amount():,.2f} left" for l in loans)
    return f"You have {len(loans)} active loan{'s' if len(loans) != 1 else ''} totaling ₹{total_remaining:,.2f} remaining, ₹{total_emi:,.2f}/month combined EMI. {lines}."


def _handle_emi(user, q):
    emis = user.emis.filter_by(is_completed=False).all()
    if not emis:
        return "You have no active EMIs right now."
    total_monthly = sum(float(e.monthly_amount) for e in emis)
    soonest = min(emis, key=lambda e: e.next_due_date())
    return (f"You have {len(emis)} active EMI{'s' if len(emis) != 1 else ''} totaling ₹{total_monthly:,.2f}/month. "
            f"{soonest.name} is due next, on {soonest.next_due_date().strftime('%d %b')}.")


def _handle_invoice(user, q):
    invoices = user.invoices.all()
    if not invoices:
        return "You haven't created any invoices yet."
    outstanding = [inv for inv in invoices if inv.effective_status() != "Paid"]
    total_outstanding = sum(inv.balance_due() for inv in outstanding)
    overdue = [inv for inv in invoices if inv.effective_status() == "Overdue"]
    if overdue:
        return f"You have ₹{total_outstanding:,.2f} outstanding across {len(outstanding)} invoice(s), including {len(overdue)} overdue. Follow up on those first."
    if outstanding:
        return f"You have ₹{total_outstanding:,.2f} outstanding across {len(outstanding)} unpaid invoice(s), none overdue yet."
    return f"All {len(invoices)} of your invoices are paid up. Nothing outstanding."


def _handle_business(user, q):
    if user.products.count() == 0:
        return "You haven't set up any products in Business yet."
    today = date.today()
    start, end = _month_bounds(today)
    revenue = sum(s.revenue() for s in user.sales.filter(Sale.sold_on.between(start, end)).all())
    cost = sum(p.cost() for p in user.purchases.filter(Purchase.purchased_on.between(start, end)).all())
    profit = revenue - cost
    low_stock = [p for p in user.products if p.is_low_stock()]
    verdict = f"a profit of ₹{profit:,.2f}" if profit >= 0 else f"a loss of ₹{abs(profit):,.2f}"
    stock_note = f" {len(low_stock)} product(s) are low on stock." if low_stock else ""
    return f"This month: ₹{revenue:,.2f} revenue, ₹{cost:,.2f} cost of goods, {verdict}.{stock_note}"


def _handle_health(user, q):
    today = date.today()
    start, end = _month_bounds(today)
    income = sum(float(i.amount) for i in user.incomes.filter(Income.received_on.between(start, end)).all())
    expense = sum(float(e.amount) for e in user.expenses.filter(Expense.spent_on.between(start, end)).all())
    if income <= 0:
        return "Log some income this month and I can give you a real financial health read."
    savings_rate = max((income - expense) / income, 0)
    expense_ratio = expense / income if income else 1
    score = int(max(0, min(100, round(50 + savings_rate * 100 - max(expense_ratio - 0.7, 0) * 80))))
    if score >= 75:
        verdict = "strong — keep doing what you're doing."
    elif score >= 50:
        verdict = "reasonable, with room to tighten spending or grow income."
    else:
        verdict = "under pressure — expenses are eating a large share of income this month."
    return f"Your financial health score is {score}/100. That's {verdict}"


def _handle_help(user, q):
    return (
        "I can answer questions about your expenses, income, budgets, savings, loans, EMIs, "
        "invoices, and business performance — all from your real data. Try things like "
        "\"how much did I spend on food this month\", \"what's my savings rate\", "
        "\"am I over budget\", \"how much do I owe on loans\", or \"how's my business doing\"."
    )


TOPIC_KEYWORDS = [
    (["spend", "spent", "expense", "expenses", "cost"], _handle_expense),
    (["income", "earn", "earned", "salary", "revenue received"], _handle_income),
    (["saving", "savings", "save "], _handle_savings),
    (["budget"], _handle_budget),
    (["loan", "loans"], _handle_loan),
    (["emi"], _handle_emi),
    (["invoice", "invoices", "outstanding", "unpaid"], _handle_invoice),
    (["business", "profit", "revenue", "sales", "stock"], _handle_business),
    (["health", "score", "how am i doing", "overall"], _handle_health),
    (["help", "what can you", "what do you"], _handle_help),
]


DEFAULT_NON_FINANCE_RESPONSE = (
    "Ask me anything about your expenses, EMI, bills, income, budgets, savings, loans, invoices, or business finances."
)


def is_finance_question(question: str) -> bool:
    normalized = (question or "").strip().lower()
    if not normalized:
        return False
    finance_keywords = [
        "expense", "expenses", "spend", "spent", "cost", "income", "earn", "salary",
        "revenue", "budget", "budgets", "save", "savings", "loan", "loans", "emi",
        "invoice", "invoices", "bill", "bills", "business", "financial", "finance",
        "payment", "payments", "cashflow", "cash flow", "balance", "outstanding",
    ]
    return any(keyword in normalized for keyword in finance_keywords)


def answer(user, question: str) -> str:
    """Entry point: matches the question to a topic handler and returns a
    real, data-backed natural-language answer. Falls back to a financial
    health summary if nothing matches, rather than a generic 'I don't
    understand' — the assistant should always be useful."""
    q = question.strip()
    if not q:
        return DEFAULT_NON_FINANCE_RESPONSE

    if not is_finance_question(q):
        return DEFAULT_NON_FINANCE_RESPONSE

    ql = q.lower()
    for keywords, handler in TOPIC_KEYWORDS:
        if any(kw in ql for kw in keywords):
            return handler(user, q)

    # no keyword matched but the question still contains financial terms
    return _handle_health(user, q) + " Ask me about expenses, income, budgets, loans, EMIs, invoices, or business for more detail."
