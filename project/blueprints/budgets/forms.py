from flask_wtf import FlaskForm
from wtforms import DecimalField, StringField, SelectField, DateField
from wtforms.validators import DataRequired, NumberRange, Optional, Length


class BudgetForm(FlaskForm):
    name = StringField("Budget name", validators=[DataRequired(), Length(max=80)])
    period = SelectField(
        "Period", choices=[("weekly", "Weekly"), ("monthly", "Monthly"), ("yearly", "Yearly")],
        validators=[DataRequired()],
    )
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0.01)], places=2)
    category_id = SelectField("Category (choose \"Overall\" for a total budget)", coerce=int, validators=[Optional()])
    period_start = DateField("Starts on", validators=[DataRequired()])
