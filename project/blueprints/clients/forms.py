from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField
from wtforms.validators import DataRequired, Optional, Length, NumberRange


class ClientForm(FlaskForm):
    name = StringField("Client name", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Phone", validators=[Optional(), Length(max=20)])
    email = StringField("Email", validators=[Optional(), Length(max=120)])
    address = StringField("Address", validators=[Optional(), Length(max=255)])
    pending_amount = DecimalField("Pending amount", validators=[Optional(), NumberRange(min=0)], places=2, default=0)
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=1000)])
