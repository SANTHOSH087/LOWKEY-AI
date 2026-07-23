"""Shared security helpers used across auth, profile, and OCR routes.

Kept in one module (rather than scattered per-blueprint) so the audit-log
schema, session-token handling, and password-policy rules stay consistent
everywhere they're enforced or recorded.
"""
import base64
import hashlib
import json
import re
import secrets
from datetime import datetime

from flask import request, current_app, render_template
from flask_login import current_user

from extensions import db, mail
from models import AuditLog, UserSession


# =============================== audit log ===============================

def log_event(event_type: str, user=None, detail: str = None) -> None:
    """Records a security event. Never raises — a logging failure should
    never break the request that triggered it."""
    try:
        user = user if user is not None else (current_user if current_user and current_user.is_authenticated else None)
        entry = AuditLog(
            user_id=getattr(user, "id", None),
            event_type=event_type,
            detail=detail,
            ip_address=request.remote_addr if request else None,
            user_agent=((request.user_agent.string or "")[:255] if request else None),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        current_app.logger.exception("Failed to write audit log entry for event_type=%s", event_type)
        db.session.rollback()


# ================================ email ====================================

def send_email(to: str, subject: str, html_body: str) -> None:
    """Sends via Flask-Mail, or logs the email instead if MAIL_SUPPRESS_SEND
    is on (the default when no MAIL_USERNAME is configured) — this keeps the
    password-reset and suspicious-login flows fully testable/runnable in
    local development without real SMTP credentials."""
    from flask_mail import Message

    if current_app.config.get("MAIL_SUPPRESS_SEND"):
        current_app.logger.info("[email suppressed — no MAIL_USERNAME set] To: %s | Subject: %s\n%s", to, subject, html_body)
        return
    try:
        msg = Message(subject=subject, recipients=[to], html=html_body,
                      sender=current_app.config.get("MAIL_DEFAULT_SENDER"))
        mail.send(msg)
    except Exception:
        current_app.logger.exception("Failed to send email to %s", to)


# ============================== sessions ====================================

SESSION_TOKEN_KEY = "lk_session_token"


def start_tracked_session(user) -> str:
    """Creates a UserSession row and returns the token to stash in the
    Flask session cookie. Called once, right after login_user()."""
    token = secrets.token_hex(32)
    entry = UserSession(
        user_id=user.id,
        session_token=token,
        ip_address=request.remote_addr,
        user_agent=(request.user_agent.string or "")[:255],
    )
    db.session.add(entry)
    db.session.commit()
    return token


def touch_current_session(token: str) -> UserSession | None:
    """Updates last_active_at for inactivity-timeout tracking. Returns the
    row, or None if it's missing, revoked, or has already gone stale beyond
    SESSION_TIMEOUT_MINUTES (caller should then log the user out)."""
    if not token:
        return None
    entry = UserSession.query.filter_by(session_token=token).first()
    if not entry or entry.revoked_at:
        return None
    timeout_minutes = current_app.config.get("SESSION_TIMEOUT_MINUTES", 30)
    if not entry.is_active(timeout_minutes):
        return None
    entry.last_active_at = datetime.utcnow()
    db.session.commit()
    return entry


def revoke_session(session_id: int, user) -> bool:
    entry = user.sessions.filter_by(id=session_id).first()
    if not entry or entry.revoked_at:
        return False
    entry.revoked_at = datetime.utcnow()
    db.session.commit()
    return True


def revoke_all_sessions(user, except_token: str = None) -> None:
    q = user.sessions.filter_by(revoked_at=None)
    for s in q:
        if except_token and s.session_token == except_token:
            continue
        s.revoked_at = datetime.utcnow()
    db.session.commit()


def is_new_device(user, ip: str, user_agent: str) -> bool:
    """A login counts as 'known' if the same IP+user-agent pair has ever
    been recorded for this user (via a past session). First-ever login is
    never flagged as suspicious."""
    if user.sessions.count() == 0:
        return False
    ua = (user_agent or "")[:255]
    return not user.sessions.filter_by(ip_address=ip, user_agent=ua).first()


# ========================== password policy =================================

PASSWORD_RULES = [
    (r".{8,}", "at least 8 characters"),
    (r"[A-Z]", "one uppercase letter"),
    (r"[a-z]", "one lowercase letter"),
    (r"\d", "one number"),
    (r"[^A-Za-z0-9]", "one special character"),
]


def password_policy_errors(raw_password: str) -> list:
    if not raw_password:
        return ["Password is required."]
    missing = [desc for pattern, desc in PASSWORD_RULES if not re.search(pattern, raw_password)]
    if missing:
        return [f"Password needs {', '.join(missing)}."]
    return []


# ========================== file upload security =============================

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


def validate_upload_mime(file_bytes: bytes) -> tuple[bool, str]:
    """Sniffs the actual file content (magic bytes) rather than trusting the
    extension or the browser-supplied Content-Type — a file renamed
    `receipt.jpg` that's actually something else won't pass this check even
    though it passed the extension whitelist."""
    import filetype
    kind = filetype.guess(file_bytes)
    if kind is None or kind.mime not in ALLOWED_MIME_TYPES:
        return False, f"File content doesn't match an allowed image type (detected: {kind.mime if kind else 'unknown'})."
    return True, ""


def scan_for_malware(file_path: str) -> tuple[bool, str]:
    """Returns (is_clean, reason). If CLAMD_HOST isn't configured, this is a
    no-op that reports clean — extension/size/MIME checks still apply
    regardless. See DEPLOYMENT.md for setting up a real ClamAV daemon."""
    host = current_app.config.get("CLAMD_HOST")
    if not host:
        return True, ""
    try:
        import clamd
        cd = clamd.ClamdNetworkSocket(host=host, port=current_app.config.get("CLAMD_PORT", 3310), timeout=10)
        result = cd.scan(file_path)
        if result is None:
            return True, ""
        status = list(result.values())[0]
        if status[0] == "FOUND":
            return False, f"Malware signature detected: {status[1]}"
        return True, ""
    except Exception as exc:
        current_app.logger.warning("ClamAV scan unavailable (%s) — allowing upload through other checks only.", exc)
        return True, ""


# ============================ encrypted export ================================

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def encrypt_export(data: bytes, passphrase: str) -> bytes:
    """Returns salt(16 bytes) + Fernet-encrypted ciphertext. The salt is
    stored alongside the ciphertext (it's not secret) so the same passphrase
    can re-derive the key on restore."""
    from cryptography.fernet import Fernet
    salt = secrets.token_bytes(16)
    key = _derive_key(passphrase, salt)
    token = Fernet(key).encrypt(data)
    return salt + token


def decrypt_export(blob: bytes, passphrase: str) -> bytes:
    from cryptography.fernet import Fernet
    from cryptography.fernet import InvalidToken
    salt, token = blob[:16], blob[16:]
    key = _derive_key(passphrase, salt)
    try:
        return Fernet(key).decrypt(token)
    except InvalidToken:
        raise ValueError("Wrong passphrase, or the file is corrupted.")
