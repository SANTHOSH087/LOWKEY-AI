import hashlib
import json
import secrets
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import func
from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    photo_url = db.Column(db.String(255))
    currency = db.Column(db.String(8), default="INR")
    theme = db.Column(db.String(20), default="lavender")  # lavender | white | dark
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ---- account lockout ----
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)

    # ---- 2FA (TOTP) ----
    totp_secret = db.Column(db.String(32), nullable=True)
    totp_enabled = db.Column(db.Boolean, default=False, nullable=False)
    backup_codes_json = db.Column(db.Text, nullable=True)  # JSON list of hashed one-time codes

    password_changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    categories = db.relationship("Category", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    expenses = db.relationship("Expense", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    incomes = db.relationship("Income", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    budgets = db.relationship("Budget", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    receipts = db.relationship("Receipt", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    suppliers = db.relationship("Supplier", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    products = db.relationship("Product", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    sales = db.relationship("Sale", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    purchases = db.relationship("Purchase", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    clients = db.relationship("Client", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    loans = db.relationship("Loan", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    emis = db.relationship("EMI", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    invoices = db.relationship("Invoice", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    chat_messages = db.relationship("ChatMessage", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    audit_logs = db.relationship("AuditLog", backref="user", lazy="dynamic")
    reset_tokens = db.relationship("PasswordResetToken", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    sessions = db.relationship("UserSession", backref="user", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)
        self.password_changed_at = datetime.utcnow()

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    # ---- account lockout ----

    LOCKOUT_THRESHOLD = 5
    LOCKOUT_MINUTES = 15

    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    def register_failed_login(self) -> None:
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= self.LOCKOUT_THRESHOLD:
            self.locked_until = datetime.utcnow() + timedelta(minutes=self.LOCKOUT_MINUTES)

    def reset_failed_logins(self) -> None:
        self.failed_login_attempts = 0
        self.locked_until = None

    # ---- 2FA (TOTP) ----

    def totp_uri(self) -> str:
        import pyotp
        return pyotp.totp.TOTP(self.totp_secret).provisioning_uri(name=self.email, issuer_name="Lowkey AI")

    def verify_totp(self, code: str) -> bool:
        import pyotp
        if not self.totp_secret or not code:
            return False
        return pyotp.TOTP(self.totp_secret).verify(code.strip(), valid_window=1)

    def generate_backup_codes(self, count: int = 8) -> list:
        """Returns the plaintext codes (show once, never stored in plaintext)
        and stores only their hashes."""
        codes = [secrets.token_hex(4) for _ in range(count)]
        self.backup_codes_json = json.dumps([generate_password_hash(c) for c in codes])
        return codes

    def verify_and_consume_backup_code(self, code: str) -> bool:
        if not self.backup_codes_json or not code:
            return False
        hashes = json.loads(self.backup_codes_json)
        for h in hashes:
            if check_password_hash(h, code.strip()):
                hashes.remove(h)
                self.backup_codes_json = json.dumps(hashes)
                return True
        return False

    def __repr__(self):
        return f"<User {self.username}>"


DEFAULT_CATEGORIES = [
    ("Food", "🍔", "#ff8a5c"),
    ("Travel", "✈️", "#4fc3ff"),
    ("Fuel", "⛽", "#ffb347"),
    ("Medical", "💊", "#ff6b8b"),
    ("Bills", "🧾", "#8f7bff"),
    ("Shopping", "🛍️", "#ff7bd1"),
    ("Education", "🎓", "#4fe3ac"),
    ("Business", "💼", "#d79f2c"),
    ("Salary", "💰", "#26b285"),
    ("Investment", "📈", "#3fa3ff"),
    ("Loan", "🏦", "#ef5675"),
    ("EMI", "📅", "#a78bff"),
    ("Others", "•••", "#8a8ea8"),
]


class Category(db.Model):
    """Powers the Expense Wheel — users can add/edit/delete on top of the defaults."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(60), nullable=False)
    icon = db.Column(db.String(10), default="•")
    color = db.Column(db.String(9), default="#8f7bff")
    is_default = db.Column(db.Boolean, default=False)

    expenses = db.relationship("Expense", backref="category", lazy="dynamic")

    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_user_category_name"),)

    @staticmethod
    def seed_defaults_for(user: "User") -> None:
        for name, icon, color in DEFAULT_CATEGORIES:
            db.session.add(Category(user_id=user.id, name=name, icon=icon, color=color, is_default=True))


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey("receipts.id"), nullable=True)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    gst_amount = db.Column(db.Numeric(12, 2), nullable=True)
    description = db.Column(db.String(255))
    payment_method = db.Column(db.String(40))  # Cash, Card, UPI, Net Banking...
    location = db.Column(db.String(120))
    tags = db.Column(db.String(255))  # comma-separated, simple v1
    receipt_url = db.Column(db.String(255))

    is_recurring = db.Column(db.Boolean, default=False)
    recurring_interval = db.Column(db.String(20))  # weekly | monthly | yearly

    spent_on = db.Column(db.Date, default=date.today, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "amount": float(self.amount),
            "description": self.description,
            "category": self.category.name if self.category else "Others",
            "payment_method": self.payment_method,
            "spent_on": self.spent_on.isoformat(),
        }


class Receipt(db.Model):
    """A scanned bill: the stored image + the raw OCR text + the parsed
    structured fields, kept as JSON so the parser can improve later without
    a migration, and so what-Tesseract-actually-saw stays auditable."""

    __tablename__ = "receipts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    image_path = db.Column(db.String(255), nullable=False)  # relative to instance/uploads/receipts
    raw_text = db.Column(db.Text)
    parsed_json = db.Column(db.Text)  # json.dumps of the parsed fields (merchant, date, gst, items, total, category)
    ocr_confidence = db.Column(db.Float)  # mean word confidence from Tesseract, 0-100

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    expenses = db.relationship("Expense", backref="receipt", lazy="dynamic")

    def parsed(self) -> dict:
        import json
        return json.loads(self.parsed_json) if self.parsed_json else {}


INCOME_SOURCES = ["Salary", "Business", "Freelancing", "Investment", "Rental", "Other Income"]


class Income(db.Model):
    __tablename__ = "incomes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    source = db.Column(db.String(40), nullable=False)  # one of INCOME_SOURCES
    description = db.Column(db.String(255))
    is_recurring = db.Column(db.Boolean, default=False)

    received_on = db.Column(db.Date, default=date.today, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Budget(db.Model):
    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)

    name = db.Column(db.String(80), nullable=False)
    period = db.Column(db.String(10), default="monthly")  # weekly | monthly | yearly
    amount = db.Column(db.Numeric(12, 2), nullable=False)

    period_start = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    category = db.relationship("Category")

    def spent_amount(self) -> float:
        from sqlalchemy import func
        q = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
            Expense.user_id == self.user_id,
            Expense.spent_on >= self.period_start,
        )
        if self.category_id:
            q = q.filter(Expense.category_id == self.category_id)
        return float(q.scalar() or 0)

    def percent_used(self) -> float:
        if not self.amount:
            return 0
        return min(round((self.spent_amount() / float(self.amount)) * 100, 1), 999)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.String(255))
    kind = db.Column(db.String(30), default="info")  # budget | emi | loan | invoice | stock | summary | ai
    link = db.Column(db.String(255))  # optional direct URL to the source record
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================= BUSINESS MODULE =============================

class Supplier(db.Model):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship("Product", backref="supplier", lazy="dynamic")


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True)

    name = db.Column(db.String(120), nullable=False)
    sku = db.Column(db.String(60))
    purchase_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    selling_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    stock_qty = db.Column(db.Integer, nullable=False, default=0)
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=5)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales = db.relationship("Sale", backref="product", lazy="dynamic")
    purchases = db.relationship("Purchase", backref="product", lazy="dynamic")

    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_user_product_name"),)

    def is_low_stock(self) -> bool:
        return self.stock_qty <= self.low_stock_threshold

    def margin_percent(self) -> float:
        if not self.selling_price:
            return 0
        return round(((float(self.selling_price) - float(self.purchase_price)) / float(self.selling_price)) * 100, 1)


class Sale(db.Model):
    __tablename__ = "sales"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)

    quantity = db.Column(db.Integer, nullable=False)
    sale_price = db.Column(db.Numeric(12, 2), nullable=False)  # price per unit at time of sale
    sold_on = db.Column(db.Date, default=date.today, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def revenue(self) -> float:
        return float(self.sale_price) * self.quantity


class Purchase(db.Model):
    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True)

    quantity = db.Column(db.Integer, nullable=False)
    purchase_price = db.Column(db.Numeric(12, 2), nullable=False)  # price per unit at time of purchase
    purchased_on = db.Column(db.Date, default=date.today, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def cost(self) -> float:
        return float(self.purchase_price) * self.quantity


# ============================= CLIENTS MODULE =============================

class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    pending_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales = db.relationship("Sale", backref="client", lazy="dynamic")
    invoices = db.relationship("Invoice", backref="client", lazy="dynamic")

    def total_purchased(self) -> float:
        return sum(s.revenue() for s in self.sales)


# ============================= LOANS MODULE =============================

class Loan(db.Model):
    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    name = db.Column(db.String(120), nullable=False)
    bank = db.Column(db.String(120))
    principal = db.Column(db.Numeric(12, 2), nullable=False)
    interest_rate = db.Column(db.Numeric(5, 2), nullable=False)  # annual %, e.g. 9.5
    tenure_months = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, default=date.today, nullable=False)
    is_closed = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship("LoanPayment", backref="loan", lazy="dynamic", cascade="all, delete-orphan")

    def monthly_rate(self) -> float:
        return float(self.interest_rate) / 12 / 100

    def emi_amount(self) -> float:
        """Standard reducing-balance EMI formula."""
        p = float(self.principal)
        r = self.monthly_rate()
        n = self.tenure_months
        if n <= 0:
            return 0
        if r == 0:
            return round(p / n, 2)
        emi = p * r * (1 + r) ** n / ((1 + r) ** n - 1)
        return round(emi, 2)

    def total_payable(self) -> float:
        return round(self.emi_amount() * self.tenure_months, 2)

    def total_interest(self) -> float:
        return round(self.total_payable() - float(self.principal), 2)

    def paid_amount(self) -> float:
        return float(db.session.query(func.coalesce(func.sum(LoanPayment.amount), 0)).filter(
            LoanPayment.loan_id == self.id
        ).scalar())

    def remaining_amount(self) -> float:
        return max(self.total_payable() - self.paid_amount(), 0)

    def percent_paid(self) -> float:
        total = self.total_payable()
        if not total:
            return 0
        return min(round((self.paid_amount() / total) * 100, 1), 100)

    def amortization_schedule(self) -> list:
        """Full month-by-month reducing-balance schedule."""
        p = float(self.principal)
        r = self.monthly_rate()
        emi = self.emi_amount()
        balance = p
        schedule = []
        for month in range(1, self.tenure_months + 1):
            interest_component = round(balance * r, 2)
            principal_component = round(emi - interest_component, 2)
            balance = round(balance - principal_component, 2)
            schedule.append({
                "month": month,
                "emi": emi,
                "principal": principal_component,
                "interest": interest_component,
                "balance": max(balance, 0),
            })
        return schedule


class LoanPayment(db.Model):
    __tablename__ = "loan_payments"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_on = db.Column(db.Date, default=date.today, nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================= EMI MODULE =============================
# (Standalone recurring EMIs not tied to a formal Loan record — e.g. a
# phone/appliance EMI where the user just wants due-date tracking, distinct
# from the full amortization-schedule Loan module above.)

class EMI(db.Model):
    __tablename__ = "emis"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    name = db.Column(db.String(120), nullable=False)
    bank = db.Column(db.String(120))
    interest_rate = db.Column(db.Numeric(5, 2))
    monthly_amount = db.Column(db.Numeric(12, 2), nullable=False)
    total_installments = db.Column(db.Integer, nullable=False)
    installments_paid = db.Column(db.Integer, nullable=False, default=0)
    due_day = db.Column(db.Integer, nullable=False, default=5)  # day of month, 1-28
    start_date = db.Column(db.Date, default=date.today, nullable=False)
    is_completed = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship("EMIPayment", backref="emi", lazy="dynamic", cascade="all, delete-orphan")

    def remaining_installments(self) -> int:
        return max(self.total_installments - self.installments_paid, 0)

    def pending_amount(self) -> float:
        return round(float(self.monthly_amount) * self.remaining_installments(), 2)

    def percent_complete(self) -> float:
        if not self.total_installments:
            return 0
        return min(round((self.installments_paid / self.total_installments) * 100, 1), 100)

    def next_due_date(self) -> date:
        today = date.today()
        year, month = today.year, today.month
        if today.day >= self.due_day:
            month += 1
            if month > 12:
                month = 1
                year += 1
        day = min(self.due_day, 28)
        return date(year, month, day)


class EMIPayment(db.Model):
    __tablename__ = "emi_payments"

    id = db.Column(db.Integer, primary_key=True)
    emi_id = db.Column(db.Integer, db.ForeignKey("emis.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_on = db.Column(db.Date, default=date.today, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================= AI ASSISTANT MODULE =============================

# ============================= INVOICE MODULE =============================

INVOICE_STATUSES = ["Draft", "Sent", "Paid", "Overdue"]


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)

    invoice_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Draft")  # Draft | Sent | Paid | Overdue

    discount_type = db.Column(db.String(10), default="flat")  # flat | percent
    discount_value = db.Column(db.Numeric(12, 2), default=0)

    notes = db.Column(db.String(500))
    issued_on = db.Column(db.Date, default=date.today, nullable=False)
    due_on = db.Column(db.Date, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship("InvoiceItem", backref="invoice", lazy="dynamic", cascade="all, delete-orphan")
    payments = db.relationship("InvoicePayment", backref="invoice", lazy="dynamic", cascade="all, delete-orphan")

    # ---- money math — every number on the invoice derives from here, nothing is stored redundantly ----
    #
    # `items` is a lazy="dynamic" relationship, so each access re-runs a DB
    # query. subtotal()/discount_amount()/taxable_amount()/tax_summary() all
    # need the item list, and grand_total()/balance_due() call through
    # several of those — so without caching, one balance_due() call fired a
    # new items query for every method in the chain. _line_items() fetches
    # the list once per instance and every method below reuses it; this is
    # safe because invoice items are only ever mutated right before a
    # redirect in the create/edit routes, never re-read from the same
    # instance afterward in the same request.

    def _line_items(self) -> list:
        if not hasattr(self, "_line_items_cache"):
            self._line_items_cache = list(self.items)
        return self._line_items_cache

    def subtotal(self) -> float:
        return round(sum(item.line_subtotal() for item in self._line_items()), 2)

    def discount_amount(self) -> float:
        sub = self.subtotal()
        if self.discount_type == "percent":
            return round(sub * (float(self.discount_value or 0) / 100), 2)
        return round(min(float(self.discount_value or 0), sub), 2)

    def taxable_amount(self) -> float:
        return round(self.subtotal() - self.discount_amount(), 2)

    def tax_summary(self) -> dict:
        """GST grouped by rate, applied proportionally after discount —
        so a discount reduces the taxable base fairly across every rate
        rather than just being subtracted from the final total."""
        sub = self.subtotal()
        discount_ratio = (self.discount_amount() / sub) if sub else 0
        summary = {}
        for item in self._line_items():
            rate = float(item.gst_rate or 0)
            item_taxable = item.line_subtotal() * (1 - discount_ratio)
            tax = round(item_taxable * (rate / 100), 2)
            summary.setdefault(rate, 0)
            summary[rate] = round(summary[rate] + tax, 2)
        return summary

    def total_tax(self) -> float:
        return round(sum(self.tax_summary().values()), 2)

    def grand_total(self) -> float:
        return round(self.taxable_amount() + self.total_tax(), 2)

    def paid_amount(self) -> float:
        return float(db.session.query(func.coalesce(func.sum(InvoicePayment.amount), 0)).filter(
            InvoicePayment.invoice_id == self.id
        ).scalar())

    def balance_due(self) -> float:
        return max(round(self.grand_total() - self.paid_amount(), 2), 0)

    def is_overdue(self) -> bool:
        return bool(self.due_on) and self.due_on < date.today() and self.status not in ("Paid",)

    def effective_status(self) -> str:
        """What the badge should actually show — Paid/Draft/Sent are
        explicit user actions, but Overdue is always computed live from
        today's date rather than trusted as a stored, staleness-prone flag."""
        if self.status == "Paid":
            return "Paid"
        if self.is_overdue():
            return "Overdue"
        return self.status


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)

    description = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    gst_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)  # percent, e.g. 18.00

    def line_subtotal(self) -> float:
        return round(float(self.quantity) * float(self.unit_price), 2)

    def line_tax(self) -> float:
        return round(self.line_subtotal() * (float(self.gst_rate) / 100), 2)

    def line_total(self) -> float:
        return round(self.line_subtotal() + self.line_tax(), 2)


class InvoicePayment(db.Model):
    __tablename__ = "invoice_payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_on = db.Column(db.Date, default=date.today, nullable=False)
    method = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============================= AI ASSISTANT =============================

# ============================= AI ASSISTANT MODULE =============================

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # "user" | "assistant"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


# ============================= SECURITY MODULE =============================

class AuditLog(db.Model):
    """Records security-relevant events — logins (success/failure), logouts,
    password changes, profile edits, 2FA toggles, account deletion, and
    flagged suspicious activity. user_id is nullable so failed logins against
    an email that doesn't exist can still be logged (for abuse monitoring)
    without a foreign key to attach them to."""
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    event_type = db.Column(db.String(40), nullable=False, index=True)
    detail = db.Column(db.String(255))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    EVENT_LABELS = {
        "login_success": "Signed in",
        "login_failed": "Failed sign-in attempt",
        "login_locked": "Sign-in blocked — account locked",
        "logout": "Signed out",
        "password_changed": "Password changed",
        "password_reset_requested": "Password reset requested",
        "password_reset_completed": "Password reset completed",
        "profile_updated": "Profile updated",
        "account_deleted": "Account deleted",
        "2fa_enabled": "Two-factor authentication enabled",
        "2fa_disabled": "Two-factor authentication disabled",
        "2fa_failed": "Failed two-factor code",
        "backup_code_used": "Backup code used for sign-in",
        "suspicious_login": "Sign-in from a new device or location",
        "session_revoked": "A session was revoked",
        "upload_blocked": "Blocked file upload",
    }

    def label(self) -> str:
        return self.EVENT_LABELS.get(self.event_type, self.event_type)


class PasswordResetToken(db.Model):
    """Only a SHA-256 hash of the token is stored — the raw token only ever
    exists in the emailed link and this row can't be used to forge a valid
    reset link even if the database is read. `used_at` prevents the same
    link from being replayed after a successful reset."""
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def is_valid(self) -> bool:
        return self.used_at is None and self.expires_at > datetime.utcnow()


class UserSession(db.Model):
    """A lightweight, server-side record of each active login, so a user can
    see 'where am I logged in' and revoke a session remotely. Flask's session
    cookie itself stays a normal signed client-side cookie (no infra change
    needed) — this table just tracks a random per-login token that's also
    stashed in that cookie; a before_request check confirms the token is
    still present and not revoked, and updates last_active_at for the
    inactivity timeout."""
    __tablename__ = "user_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    session_token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked_at = db.Column(db.DateTime, nullable=True)

    def is_active(self, timeout_minutes: int) -> bool:
        if self.revoked_at:
            return False
        return self.last_active_at > datetime.utcnow() - timedelta(minutes=timeout_minutes)

    def device_label(self) -> str:
        ua = (self.user_agent or "").lower()
        if "mobile" in ua or "android" in ua or "iphone" in ua:
            device = "Mobile"
        elif "tablet" in ua or "ipad" in ua:
            device = "Tablet"
        else:
            device = "Desktop"
        browser = "Browser"
        for name in ["Edg", "Chrome", "Firefox", "Safari", "OPR"]:
            if name.lower() in ua:
                browser = {"edg": "Edge", "opr": "Opera"}.get(name.lower(), name)
                break
        return f"{browser} on {device}"
