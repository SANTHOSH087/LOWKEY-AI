from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email, Length, EqualTo, Optional, Regexp

from security_utils import password_policy_errors


def strong_password(form, field):
    from wtforms.validators import ValidationError
    errors = password_policy_errors(field.data)
    if errors:
        raise ValidationError(errors[0])


class ProfileForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=60)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    phone = StringField(
        "Phone",
        validators=[Optional(), Length(max=20), Regexp(r"^[0-9+\-\s]*$", message="Phone can only contain numbers, spaces, + and -.")],
    )
    photo_url = StringField("Photo URL", validators=[Optional(), Length(max=255)])


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField("New password", validators=[DataRequired(), strong_password])
    confirm_password = PasswordField(
        "Confirm new password", validators=[DataRequired(), EqualTo("new_password", message="Passwords must match")]
    )


class DeleteAccountForm(FlaskForm):
    password = PasswordField("Password", validators=[DataRequired()])
    confirm_text = StringField("Type DELETE to confirm", validators=[DataRequired()])


class TwoFactorSetupForm(FlaskForm):
    """Confirms the user's authenticator app is actually working before
    2FA is turned on — enabling it purely on a "click to enable" button
    with no verification risks locking the user out of their own account."""
    code = StringField("6-digit code", validators=[DataRequired(), Length(min=6, max=6)])


class TwoFactorDisableForm(FlaskForm):
    password = PasswordField("Password", validators=[DataRequired()])


class ExportPassphraseForm(FlaskForm):
    passphrase = PasswordField("Export passphrase", validators=[DataRequired(), Length(min=8)])
