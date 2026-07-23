from flask_wtf import FlaskForm
from wtforms import DecimalField, StringField, SelectField, DateField, BooleanField
from wtforms.validators import DataRequired, NumberRange, Optional, Length

from models import INCOME_SOURCES


class IncomeForm(FlaskForm):
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    source = SelectField("Source", choices=[(s, s) for s in INCOME_SOURCES], validators=[DataRequired()])
    description = StringField("Description", validators=[Optional(), Length(max=255)])
    received_on = DateField("Date received", validators=[DataRequired()])
    is_recurring = BooleanField("Recurring")
