from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, IntegerField, SelectField, DateField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional, Length


class SupplierForm(FlaskForm):
    name = StringField("Supplier name", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Phone", validators=[Optional(), Length(max=20)])
    email = StringField("Email", validators=[Optional(), Length(max=120)])
    notes = StringField("Notes", validators=[Optional(), Length(max=255)])


class ProductForm(FlaskForm):
    name = StringField("Product name", validators=[DataRequired(), Length(max=120)])
    sku = StringField("SKU", validators=[Optional(), Length(max=60)])
    purchase_price = DecimalField("Purchase price", validators=[InputRequired(), NumberRange(min=0)], places=2)
    selling_price = DecimalField("Selling price", validators=[InputRequired(), NumberRange(min=0)], places=2)
    stock_qty = IntegerField("Current stock", validators=[InputRequired(), NumberRange(min=0)])
    low_stock_threshold = IntegerField("Low stock alert threshold", validators=[InputRequired(), NumberRange(min=0)], default=5)
    supplier_id = SelectField("Supplier (optional)", coerce=int, validators=[Optional()])


class SaleForm(FlaskForm):
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    client_id = SelectField("Client (optional)", coerce=int, validators=[Optional()])
    quantity = IntegerField("Quantity", validators=[DataRequired(), NumberRange(min=1)])
    sale_price = DecimalField("Sale price per unit", validators=[InputRequired(), NumberRange(min=0)], places=2)
    sold_on = DateField("Date", validators=[DataRequired()])


class PurchaseForm(FlaskForm):
    product_id = SelectField("Product", coerce=int, validators=[DataRequired()])
    supplier_id = SelectField("Supplier (optional)", coerce=int, validators=[Optional()])
    quantity = IntegerField("Quantity", validators=[DataRequired(), NumberRange(min=1)])
    purchase_price = DecimalField("Purchase price per unit", validators=[InputRequired(), NumberRange(min=0)], places=2)
    purchased_on = DateField("Date", validators=[DataRequired()])
