"""
Optional LLM-backed assistant path. Disabled unless an API key is present
in the environment — never hardcoded here or anywhere else in this repo.

Honesty check: this code path has NOT been run against a real API in
this build, since no key is configured in this environment. It's written
defensively (see the try/except in ask_llm) so a bad key, a network
failure, or a provider outage falls back to the rule-based engine in
engine.py rather than breaking the assistant — but "falls back correctly"
and "produces good answers when it succeeds" are two different claims,
and only the first one has actually been exercised here.

To enable: set OPENAI_API_KEY (or adapt call_provider for another
provider) as an environment variable. Never commit it to a .env file
that gets checked into version control.
"""
import os

LLM_ENABLED = bool(os.environ.get("OPENAI_API_KEY"))


def ask_llm(user, question: str, data_context: str) -> str | None:
    """Returns a free-form answer from the configured LLM, given a summary
    of the user's real financial data as context — or None if disabled,
    misconfigured, or the call fails for any reason, so the caller can
    fall back to the rule-based engine.
    """
    if not LLM_ENABLED:
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    try:
        import openai  # only imported if actually enabled — not a hard dependency otherwise
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": (
                    "You are Lowkey AI's financial assistant. Answer using ONLY the data "
                    "provided below — never invent numbers. Keep responses concise (2-4 "
                    "sentences), in ₹, and actionable.\n\n" + data_context
                )},
                {"role": "user", "content": question},
            ],
            max_tokens=250,
            timeout=10,
        )
        return response.choices[0].message.content
    except Exception:
        # Any failure (bad key, network, rate limit, unexpected response shape) — fall
        # back silently. The user still gets a real, data-backed answer either way.
        return None


def build_data_context(user) -> str:
    """A compact text summary of the user's real numbers, for the LLM prompt
    if/when that path is used. Kept separate from engine.py's per-topic
    handlers so it's easy to see exactly what would be sent to a third party."""
    from datetime import date
    from calendar import monthrange
    from models import Expense, Income

    today = date.today()
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])

    income = sum(float(i.amount) for i in user.incomes.filter(Income.received_on.between(start, end)).all())
    expense = sum(float(e.amount) for e in user.expenses.filter(Expense.spent_on.between(start, end)).all())
    active_loans = user.loans.filter_by(is_closed=False).count()
    active_emis = user.emis.filter_by(is_completed=False).count()

    return (
        f"This month — Income: ₹{income:,.2f}, Expenses: ₹{expense:,.2f}, "
        f"Net: ₹{income - expense:,.2f}. Active loans: {active_loans}. Active EMIs: {active_emis}."
    )
