from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, StringField, DecimalField
from wtforms.validators import DataRequired, Optional, Length, NumberRange

from models import INVOICE_STATUSES


class InvoiceForm(FlaskForm):
    client_id = SelectField("Client", coerce=int, validators=[Optional()])
    status = SelectField("Status", choices=[(s, s) for s in INVOICE_STATUSES], validators=[DataRequired()])
    issued_on = DateField("Issue date", validators=[DataRequired()])
    due_on = DateField("Due date", validators=[Optional()])
    discount_type = SelectField("Discount type", choices=[("flat", "Flat amount"), ("percent", "Percentage")])
    discount_value = DecimalField("Discount value", validators=[Optional(), NumberRange(min=0)], places=2, default=0)
    notes = StringField("Notes", validators=[Optional(), Length(max=500)])


class InvoicePaymentForm(FlaskForm):
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    paid_on = DateField("Payment date", validators=[DataRequired()])
    method = SelectField("Method", choices=[("Cash", "Cash"), ("Card", "Card"), ("UPI", "UPI"), ("Bank Transfer", "Bank Transfer"), ("Other", "Other")])
