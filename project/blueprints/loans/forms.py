from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, IntegerField, DateField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional, Length


class LoanForm(FlaskForm):
    name = StringField("Loan name", validators=[DataRequired(), Length(max=120)])
    bank = StringField("Bank / lender", validators=[Optional(), Length(max=120)])
    principal = DecimalField("Principal amount", validators=[DataRequired(), NumberRange(min=1)], places=2)
    interest_rate = DecimalField("Annual interest rate (%)", validators=[InputRequired(), NumberRange(min=0, max=100)], places=2)
    tenure_months = IntegerField("Tenure (months)", validators=[DataRequired(), NumberRange(min=1, max=600)])
    start_date = DateField("Start date", validators=[DataRequired()])


class LoanPaymentForm(FlaskForm):
    amount = DecimalField("Payment amount", validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    paid_on = DateField("Payment date", validators=[DataRequired()])
    note = StringField("Note", validators=[Optional(), Length(max=255)])
