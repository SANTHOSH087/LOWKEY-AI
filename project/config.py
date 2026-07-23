import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _database_uri() -> str:
    """Reads DATABASE_URL from the environment, falling back to a local
    SQLite file for development. Render/Railway/Heroku-style providers
    sometimes still hand out the old `postgres://` scheme, which SQLAlchemy
    1.4+ no longer accepts — normalize it to `postgresql://` so a copy-pasted
    DATABASE_URL just works instead of failing at db.create_all()."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return f"sqlite:///{os.path.join(BASE_DIR, 'lowkey.db')}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    """Shared, environment-agnostic defaults."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-this-in-production")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    WTF_CSRF_ENABLED = True
    CURRENCY_SYMBOL = "₹"
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8MB — matches ocr blueprint's own check

    # No cache-busting/versioned filenames on static assets, so keep this
    # short enough that a CSS/JS deploy doesn't leave people on stale
    # cached files for long, while still avoiding a re-fetch on every request.
    SEND_FILE_MAX_AGE_DEFAULT = 86400  # 1 day, in seconds

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # ---- session timeout ----
    # A session is considered expired after this many minutes of inactivity.
    # Flask's own cookie lifetime (PERMANENT_SESSION_LIFETIME) is set to the
    # same value; actual enforcement (and the "last active" tracking used to
    # judge inactivity, independent of the cookie's own expiry) lives in the
    # UserSession table + app.py's before_request check.
    SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "30"))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    SESSION_REFRESH_EACH_REQUEST = True

    # ---- rate limiting ----
    # See extensions.py — defaults to in-memory storage, fine for a single
    # Gunicorn worker. Set RATELIMIT_STORAGE_URI (e.g. a Redis URL) for a
    # multi-worker/multi-instance deployment so limits are shared correctly.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    # ---- email (password reset + suspicious-login alerts) ----
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "no-reply@lowkey.ai")
    # If no real mail server is configured, emails are logged instead of sent
    # (see security_utils.send_email) so password reset / 2FA / registration
    # keep working end-to-end in local development without SMTP set up.
    MAIL_SUPPRESS_SEND = os.environ.get("MAIL_USERNAME") is None

    # ---- malware scanning (optional — see DEPLOYMENT.md) ----
    # If unset, uploads skip the ClamAV scan step entirely (extension +
    # size + real MIME-sniffing checks still apply) rather than failing
    # closed, so OCR isn't silently broken for anyone who hasn't set up a
    # ClamAV daemon.
    CLAMD_HOST = os.environ.get("CLAMD_HOST")
    CLAMD_PORT = int(os.environ.get("CLAMD_PORT", "3310"))

    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    """Local development — `python app.py` uses this via FLASK_ENV/FLASK_CONFIG."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    """Used when FLASK_CONFIG=production (see wsgi.py / gunicorn_config.py).
    Fails fast at startup rather than silently running with an insecure
    default secret key or debug mode left on in a real deployment.

    PREFERRED_URL_SCHEME only affects URL generation (url_for(_external=True)
    etc.) — it does NOT make Flask treat incoming requests as HTTPS. That
    detection instead comes from ProxyFix reading X-Forwarded-Proto, which
    app.py wires up whenever this config is active (Render/Railway terminate
    TLS at their proxy and forward plain HTTP internally, so without
    ProxyFix, request.is_secure would be False even in production and the
    HSTS header below would never actually be sent)."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"


def _validate_production_config(app_config: dict) -> None:
    """Raises at startup if the app is about to run in production with an
    insecure or missing configuration, instead of silently accepting a
    dev-only default that would leak session security."""
    if app_config.get("SECRET_KEY") in (None, "", "dev-secret-change-this-in-production"):
        raise RuntimeError(
            "SECRET_KEY is not set (or is left at the insecure development default). "
            "Set a real SECRET_KEY environment variable before running in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str = None) -> type:
    name = name or os.environ.get("FLASK_CONFIG", "development")
    return CONFIG_MAP.get(name, DevelopmentConfig)
