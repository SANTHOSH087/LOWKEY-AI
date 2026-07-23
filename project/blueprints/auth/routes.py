import secrets
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db, limiter
from models import User, Category, PasswordResetToken
from blueprints.auth.forms import LoginForm, RegisterForm, TwoFactorForm, ForgotPasswordForm, ResetPasswordForm
from security_utils import (
    log_event, send_email, start_tracked_session, revoke_all_sessions,
    is_new_device, SESSION_TOKEN_KEY,
)

auth_bp = Blueprint("auth", __name__, template_folder="../../templates/auth")

RESET_TOKEN_MINUTES = 15
PENDING_2FA_KEY = "pending_2fa_user_id"
PENDING_REMEMBER_KEY = "pending_2fa_remember"


def _complete_login(user, remember: bool) -> None:
    """Shared tail end of a successful login (with or without a 2FA step):
    regenerates the session (mitigates session fixation — a pre-login
    session ID/CSRF token can never be reused post-login), logs the user
    in, starts a tracked UserSession row, and flags+emails on a new device."""
    is_new = is_new_device(user, request.remote_addr, request.user_agent.string or "")

    session.clear()  # session fixation mitigation — drop anything set pre-login
    login_user(user, remember=remember)
    session.permanent = True
    token = start_tracked_session(user)
    session[SESSION_TOKEN_KEY] = token

    user.reset_failed_logins()
    db.session.commit()
    log_event("login_success", user=user)

    if is_new:
        log_event("suspicious_login", user=user, detail="Sign-in from a new device or IP address.")
        send_email(
            user.email, "New sign-in to your Lowkey AI account",
            render_template("email/suspicious_login.html", user=user, ip=request.remote_addr,
                             user_agent=request.user_agent.string if request.user_agent else "Unknown device",
                             when=datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")),
        )
        flash("We noticed this is a new device — we've sent you an email about it.", "info")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash("An account with that email already exists.", "error")
            return render_template("auth/register.html", form=form)
        if User.query.filter_by(username=form.username.data).first():
            flash("That username is taken.", "error")
            return render_template("auth/register.html", form=form)

        user = User(username=form.username.data, email=form.email.data.lower())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()  # get user.id before seeding categories
        Category.seed_defaults_for(user)
        db.session.commit()

        _complete_login(user, remember=False)
        flash("Welcome to Lowkey AI — your account is ready.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"], error_message="Too many login attempts. Please wait a minute and try again.")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()

        if user and user.is_locked():
            log_event("login_locked", user=user)
            flash("This account is temporarily locked due to repeated failed sign-in attempts. "
                  f"Try again in a few minutes.", "error")
            return render_template("auth/login.html", form=form)

        if user is None or not user.check_password(form.password.data):
            if user:
                user.register_failed_login()
                db.session.commit()
                if user.is_locked():
                    log_event("login_locked", user=user, detail="Locked after 5 failed attempts.")
                    flash(f"Too many failed attempts — this account is locked for {user.LOCKOUT_MINUTES} minutes.", "error")
                    return render_template("auth/login.html", form=form)
            log_event("login_failed", user=user, detail=f"email={form.email.data.lower()}")
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html", form=form)

        if user.totp_enabled:
            session[PENDING_2FA_KEY] = user.id
            session[PENDING_REMEMBER_KEY] = form.remember.data
            return redirect(url_for("auth.verify_2fa"))

        _complete_login(user, remember=form.remember.data)
        next_url = request.args.get("next")
        return redirect(next_url or url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/verify-2fa", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def verify_2fa():
    user_id = session.get(PENDING_2FA_KEY)
    if not user_id:
        return redirect(url_for("auth.login"))
    user = db.session.get(User, user_id)
    if not user:
        session.pop(PENDING_2FA_KEY, None)
        return redirect(url_for("auth.login"))

    form = TwoFactorForm()
    if form.validate_on_submit():
        used_backup_code = False
        ok = user.verify_totp(form.code.data)
        if not ok:
            ok = user.verify_and_consume_backup_code(form.code.data)
            used_backup_code = ok

        if not ok:
            log_event("2fa_failed", user=user)
            flash("That code didn't work — try again.", "error")
            return render_template("auth/verify_2fa.html", form=form)

        if used_backup_code:
            db.session.commit()  # persist the consumed backup code
            log_event("backup_code_used", user=user)

        remember = session.pop(PENDING_REMEMBER_KEY, False)
        session.pop(PENDING_2FA_KEY, None)
        _complete_login(user, remember=remember)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/verify_2fa.html", form=form)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        # Always show the same message whether or not the account exists —
        # confirming/denying an email's existence here is its own leak.
        if user:
            raw_token = secrets.token_urlsafe(32)
            entry = PasswordResetToken(
                user_id=user.id,
                token_hash=PasswordResetToken.hash_token(raw_token),
                expires_at=datetime.utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES),
            )
            db.session.add(entry)
            db.session.commit()
            log_event("password_reset_requested", user=user)
            reset_url = url_for("auth.reset_password", token=raw_token, _external=True)
            send_email(
                user.email, "Reset your Lowkey AI password",
                render_template("email/password_reset.html", user=user, reset_url=reset_url,
                                 minutes=RESET_TOKEN_MINUTES),
            )
        flash("If an account exists for that email, we've sent a password reset link.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    token_hash = PasswordResetToken.hash_token(token)
    entry = PasswordResetToken.query.filter_by(token_hash=token_hash).first()

    if not entry or not entry.is_valid():
        flash("That reset link is invalid or has expired — request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = db.session.get(User, entry.user_id)
        user.set_password(form.password.data)
        entry.used_at = datetime.utcnow()
        db.session.commit()

        revoke_all_sessions(user)  # a leaked/reset password shouldn't leave old sessions valid
        log_event("password_reset_completed", user=user)
        flash("Your password has been reset — sign in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    from models import UserSession
    token = session.get(SESSION_TOKEN_KEY)
    if token:
        entry = UserSession.query.filter_by(session_token=token).first()
        if entry:
            entry.revoked_at = datetime.utcnow()
            db.session.commit()
    log_event("logout", user=current_user)
    logout_user()
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("core.landing"))
