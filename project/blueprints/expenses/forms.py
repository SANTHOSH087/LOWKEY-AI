from flask_wtf import FlaskForm
from wtforms import DecimalField, StringField, SelectField, DateField, BooleanField
from wtforms.validators import DataRequired, NumberRange, Optional, Length

PAYMENT_METHODS = ["Cash", "Card", "UPI", "Net Banking", "Wallet", "Other"]


class ExpenseForm(FlaskForm):
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    description = StringField("Description", validators=[Optional(), Length(max=255)])
    payment_method = SelectField("Payment method", choices=[(m, m) for m in PAYMENT_METHODS], validators=[Optional()])
    location = StringField("Location", validators=[Optional(), Length(max=120)])
    tags = StringField("Tags (comma-separated)", validators=[Optional(), Length(max=255)])
    spent_on = DateField("Date", validators=[DataRequired()])
    is_recurring = BooleanField("Recurring")
    recurring_interval = SelectField(
        "Repeats",
        choices=[("", "—"), ("weekly", "Weekly"), ("monthly", "Monthly"), ("yearly", "Yearly")],
        validators=[Optional()],
    )
