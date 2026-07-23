from flask import Blueprint, render_template, redirect, url_for, request, flash, Response, current_app
from flask_login import current_user, login_required, logout_user
import pyotp
import qrcode
import io

from extensions import db, limiter
from models import User, Expense, Income, Client, Product, Invoice, Loan, EMI, Category, AuditLog, UserSession
from blueprints.core.forms import (
    ProfileForm, ChangePasswordForm, DeleteAccountForm,
    TwoFactorSetupForm, TwoFactorDisableForm, ExportPassphraseForm,
)
from security_utils import log_event, revoke_all_sessions, SESSION_TOKEN_KEY

core_bp = Blueprint("core", __name__)

# Sidebar modules that exist as real, working features right now.
BUILT_MODULES = {"dashboard", "expenses", "income", "budgets"}

# Every module the approved sidebar promises. The ones not in BUILT_MODULES
# render a real page (not a 404, not a fake screenshot) that says plainly
# what's implemented so far — this list is what CONTINUATION RULE picks up
# from next.
ALL_MODULES = [
    ("dashboard", "Dashboard", "dashboard.index"),
    ("expenses", "Expenses", "expenses.list_view"),
    ("income", "Income", "income.list_view"),
    ("budgets", "Budgets", "budgets.list_view"),
    ("business", "Business", None),
    ("clients", "Clients", None),
    ("invoices", "Invoices", None),
    ("reports", "Reports", None),
    ("ocr", "OCR Scanner", None),
    ("assistant", "AI Assistant", None),
    ("loans", "Loans", None),
    ("emi", "EMI", None),
    ("notifications", "Notifications", None),
    ("settings", "Settings", "core.settings"),
    ("profile", "Profile", "core.profile"),
]


@core_bp.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("landing.html")


@core_bp.route("/module/<slug>")
@login_required
def module_placeholder(slug):
    entry = next((m for m in ALL_MODULES if m[0] == slug), None)
    label = entry[1] if entry else slug.title()
    return render_template("module_placeholder.html", label=label, slug=slug)


@core_bp.route("/settings")
@login_required
def settings():
    return render_template("settings.html", delete_form=DeleteAccountForm())


@core_bp.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    results = {"expenses": [], "income": [], "clients": [], "products": [], "invoices": [], "loans": [], "emis": []}
    report_shortcut = None

    if q and len(q) >= 2:
        like = f"%{q}%"
        results["expenses"] = current_user.expenses.filter(Expense.description.ilike(like)).limit(8).all()
        results["income"] = current_user.incomes.filter(Income.description.ilike(like) | Income.source.ilike(like)).limit(8).all()
        results["clients"] = current_user.clients.filter(Client.name.ilike(like)).limit(8).all()
        results["products"] = current_user.products.filter(Product.name.ilike(like) | Product.sku.ilike(like)).limit(8).all()
        results["invoices"] = current_user.invoices.filter(Invoice.invoice_number.ilike(like)).limit(8).all()
        results["loans"] = current_user.loans.filter(Loan.name.ilike(like)).limit(8).all()
        results["emis"] = current_user.emis.filter(EMI.name.ilike(like)).limit(8).all()

        # Reports has no persisted records to search by keyword — it's computed
        # on the fly from a date range — so "integrating" it with search means
        # surfacing a direct shortcut when the query looks report-related,
        # rather than faking a searchable Report entity that doesn't exist.
        ql = q.lower()
        matched_type = next((rt for rt in ["expense", "income", "business", "loan", "emi", "category", "summary"] if rt in ql), None)
        if matched_type:
            report_shortcut = matched_type
        elif "report" in ql:
            report_shortcut = "summary"

    total = sum(len(v) for v in results.values())
    return render_template("search.html", q=q, results=results, total=total, report_shortcut=report_shortcut)


@core_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_form = ProfileForm(obj=current_user)
    password_form = ChangePasswordForm()

    if request.method == "POST" and request.form.get("form_name") == "profile":
        if profile_form.validate_on_submit():
            new_email = profile_form.email.data.lower()
            new_username = profile_form.username.data

            existing_email = User.query.filter(User.email == new_email, User.id != current_user.id).first()
            existing_username = User.query.filter(User.username == new_username, User.id != current_user.id).first()

            if existing_email:
                flash("Another account already uses that email.", "error")
            elif existing_username:
                flash("That username is taken.", "error")
            else:
                current_user.username = new_username
                current_user.email = new_email
                current_user.phone = profile_form.phone.data or None
                current_user.photo_url = profile_form.photo_url.data or None
                db.session.commit()
                log_event("profile_updated", user=current_user)
                flash("Profile updated.", "success")
                return redirect(url_for("core.profile"))

    return render_template("profile.html", profile_form=profile_form, password_form=password_form)


@core_bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            log_event("password_changed", user=current_user)
            revoke_all_sessions(current_user, except_token=None)  # force re-login everywhere, including here
            logout_user()
            flash("Password changed successfully. Please sign in again.", "success")
            return redirect(url_for("auth.login"))
    else:
        for error_list in form.errors.values():
            for error in error_list:
                flash(error, "error")

    profile_form = ProfileForm(obj=current_user)
    return render_template("profile.html", profile_form=profile_form, password_form=form), 400


@core_bp.route("/settings/delete-account", methods=["POST"])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if not form.validate_on_submit():
        flash("Please fill in both fields correctly to delete your account.", "error")
        return redirect(url_for("core.settings"))

    if form.confirm_text.data.strip().upper() != "DELETE":
        flash('Type DELETE exactly to confirm account deletion.', "error")
        return redirect(url_for("core.settings"))

    if not current_user.check_password(form.password.data):
        flash("Incorrect password — account not deleted.", "error")
        return redirect(url_for("core.settings"))

    user = User.query.get(current_user.id)
    log_event("account_deleted", user=user, detail=f"username={user.username}")
    db.session.commit()  # persist the log entry before detaching it from the user below

    user.audit_logs.update({"user_id": None})  # keep the audit trail after the account itself is gone
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Your account and all associated data have been deleted.", "info")
    return redirect(url_for("core.landing"))


# =============================== security page ===============================

@core_bp.route("/profile/security")
@login_required
def security():
    sessions = current_user.sessions.filter_by(revoked_at=None).order_by(UserSession.last_active_at.desc()).all()
    from flask import session as flask_session
    current_token = flask_session.get(SESSION_TOKEN_KEY)
    audit_log = current_user.audit_logs.order_by(AuditLog.created_at.desc()).limit(30).all()
    return render_template(
        "security.html",
        sessions=sessions, current_token=current_token, audit_log=audit_log,
        two_factor_form=TwoFactorSetupForm(), disable_form=TwoFactorDisableForm(),
    )


@core_bp.route("/profile/2fa/setup", methods=["GET"])
@login_required
def two_factor_setup():
    if current_user.totp_enabled:
        flash("Two-factor authentication is already enabled.", "info")
        return redirect(url_for("core.security"))

    from flask import session as flask_session
    secret = pyotp.random_base32()
    flask_session["pending_totp_secret"] = secret
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=current_user.email, issuer_name="Lowkey AI")
    return render_template("two_factor_setup.html", secret=secret, uri=uri, form=TwoFactorSetupForm())


@core_bp.route("/profile/2fa/qr.png")
@login_required
def two_factor_qr():
    from flask import session as flask_session
    secret = flask_session.get("pending_totp_secret")
    if not secret:
        return Response(status=404)
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=current_user.email, issuer_name="Lowkey AI")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


@core_bp.route("/profile/2fa/enable", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def two_factor_enable():
    from flask import session as flask_session
    secret = flask_session.get("pending_totp_secret")
    form = TwoFactorSetupForm()

    if not secret:
        flash("Your 2FA setup session expired — start again.", "error")
        return redirect(url_for("core.security"))

    if not form.validate_on_submit() or not pyotp.TOTP(secret).verify(form.code.data.strip(), valid_window=1):
        flash("That code didn't match — check your authenticator app and try again.", "error")
        return render_template("two_factor_setup.html", secret=secret,
                                uri=pyotp.totp.TOTP(secret).provisioning_uri(name=current_user.email, issuer_name="Lowkey AI"),
                                form=form)

    current_user.totp_secret = secret
    current_user.totp_enabled = True
    codes = current_user.generate_backup_codes()
    db.session.commit()
    flask_session.pop("pending_totp_secret", None)
    log_event("2fa_enabled", user=current_user)

    return render_template("two_factor_backup_codes.html", codes=codes)


@core_bp.route("/profile/2fa/disable", methods=["POST"])
@login_required
def two_factor_disable():
    form = TwoFactorDisableForm()
    if not form.validate_on_submit() or not current_user.check_password(form.password.data):
        flash("Incorrect password — two-factor authentication was not disabled.", "error")
        return redirect(url_for("core.security"))

    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.backup_codes_json = None
    db.session.commit()
    log_event("2fa_disabled", user=current_user)
    flash("Two-factor authentication has been disabled.", "info")
    return redirect(url_for("core.security"))


# ================================ sessions ====================================

@core_bp.route("/profile/sessions/<int:session_id>/revoke", methods=["POST"])
@login_required
def revoke_session_view(session_id):
    from security_utils import revoke_session
    from flask import session as flask_session

    entry = current_user.sessions.filter_by(id=session_id).first()
    if entry and entry.session_token == flask_session.get(SESSION_TOKEN_KEY):
        flash("You can't revoke the session you're currently using — log out instead.", "error")
        return redirect(url_for("core.security"))

    if revoke_session(session_id, current_user):
        log_event("session_revoked", user=current_user, detail=f"session_id={session_id}")
        flash("That session has been signed out.", "success")
    else:
        flash("Session not found.", "error")
    return redirect(url_for("core.security"))


# =========================== encrypted data export =============================

@core_bp.route("/profile/export", methods=["GET", "POST"])
@login_required
def export_data():
    form = ExportPassphraseForm()
    if form.validate_on_submit():
        from security_utils import encrypt_export
        import json as _json

        payload = {
            "username": current_user.username,
            "email": current_user.email,
            "exported_at": str(current_user.created_at),
            "expenses": [{"amount": float(e.amount), "date": str(e.spent_on), "description": e.description}
                         for e in current_user.expenses],
            "income": [{"amount": float(i.amount), "date": str(i.received_on), "source": i.source}
                       for i in current_user.incomes],
        }
        blob = encrypt_export(_json.dumps(payload, indent=2).encode(), form.passphrase.data)

        response = Response(blob, mimetype="application/octet-stream")
        response.headers["Content-Disposition"] = "attachment; filename=lowkey-export.enc"
        return response

    return render_template("export_data.html", form=form)


@core_bp.route("/profile/restore", methods=["GET", "POST"])
@login_required
def restore_data():
    """Decrypts an uploaded export and shows its contents for verification.
    Deliberately read-only rather than writing decrypted records back into
    the live database — merging an old export against current data raises
    conflict-resolution questions (duplicate expenses? overwritten edits?)
    that are a separate feature in their own right. This confirms a backup
    is genuine and recoverable, which is the actual point of testing a
    backup, without silently mutating live financial data.
    """
    form = ExportPassphraseForm()
    restored = None

    if form.validate_on_submit():
        file = request.files.get("export_file")
        if not file or file.filename == "":
            flash("Choose an exported .enc file first.", "error")
            return render_template("restore_data.html", form=form, restored=None)

        from security_utils import decrypt_export
        import json as _json

        try:
            blob = file.read()
            decrypted = decrypt_export(blob, form.passphrase.data)
            restored = _json.loads(decrypted)
        except ValueError as exc:
            flash(str(exc), "error")
        except Exception:
            current_app.logger.exception("Failed to parse a decrypted export")
            flash("That file couldn't be read — it may not be a Lowkey AI export.", "error")

    return render_template("restore_data.html", form=form, restored=restored)
