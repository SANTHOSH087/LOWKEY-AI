from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, IntegerField, DateField
from wtforms.validators import DataRequired, NumberRange, Optional, Length


class EMIForm(FlaskForm):
    name = StringField("EMI name", validators=[DataRequired(), Length(max=120)])
    bank = StringField("Bank / provider", validators=[Optional(), Length(max=120)])
    interest_rate = DecimalField("Interest rate (%, optional)", validators=[Optional(), NumberRange(min=0, max=100)], places=2)
    monthly_amount = DecimalField("Monthly EMI amount", validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    total_installments = IntegerField("Total installments", validators=[DataRequired(), NumberRange(min=1, max=600)])
    installments_paid = IntegerField("Installments already paid", validators=[Optional(), NumberRange(min=0)], default=0)
    due_day = IntegerField("Due day of month (1-28)", validators=[DataRequired(), NumberRange(min=1, max=28)], default=5)
    start_date = DateField("Start date", validators=[DataRequired()])


class EMIPaymentForm(FlaskForm):
    amount = DecimalField("Payment amount", validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    paid_on = DateField("Payment date", validators=[DataRequired()])
