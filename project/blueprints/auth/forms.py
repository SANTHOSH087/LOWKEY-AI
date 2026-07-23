from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError

from security_utils import password_policy_errors


def strong_password(form, field):
    errors = password_policy_errors(field.data)
    if errors:
        raise ValidationError(errors[0])


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")


class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=60)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), strong_password])
    confirm_password = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )


class TwoFactorForm(FlaskForm):
    """Shown as a second step after a correct password, when the account
    has 2FA enabled. Accepts either a live 6-digit TOTP code or an unused
    backup recovery code."""
    code = StringField("Authentication code", validators=[DataRequired(), Length(min=6, max=20)])


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), strong_password])
    confirm_password = PasswordField(
        "Confirm new password", validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )
