import logging
import os
import sys

from flask import Flask, render_template, request, flash, session
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config, _validate_production_config
from extensions import db, login_manager, csrf, limiter, mail


def create_app(config_class: type = None) -> Flask:
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1)
    config_class = config_class or get_config()
    app.config.from_object(config_class)

    if os.environ.get("FLASK_CONFIG") == "production":
        _validate_production_config(app.config)

    _configure_logging(app)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ---- blueprints ----
    from blueprints.auth.routes import auth_bp
    from blueprints.core.routes import core_bp
    from blueprints.dashboard.routes import dashboard_bp
    from blueprints.expenses.routes import expenses_bp
    from blueprints.income.routes import income_bp
    from blueprints.budgets.routes import budgets_bp
    from blueprints.ocr.routes import ocr_bp
    from blueprints.business.routes import business_bp
    from blueprints.clients.routes import clients_bp
    from blueprints.loans.routes import loans_bp
    from blueprints.emi.routes import emi_bp
    from blueprints.invoices.routes import invoices_bp
    from blueprints.reports.routes import reports_bp
    from blueprints.notifications.routes import notifications_bp
    from blueprints.assistant.routes import assistant_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(expenses_bp, url_prefix="/expenses")
    app.register_blueprint(income_bp, url_prefix="/income")
    app.register_blueprint(budgets_bp, url_prefix="/budgets")
    app.register_blueprint(ocr_bp, url_prefix="/ocr")
    app.register_blueprint(business_bp, url_prefix="/business")
    app.register_blueprint(clients_bp, url_prefix="/clients")
    app.register_blueprint(loans_bp, url_prefix="/loans")
    app.register_blueprint(emi_bp, url_prefix="/emi")
    app.register_blueprint(invoices_bp, url_prefix="/invoices")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(notifications_bp, url_prefix="/notifications")
    app.register_blueprint(assistant_bp, url_prefix="/assistant")

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        unread = current_user.notifications.filter_by(is_read=False).count() if current_user.is_authenticated else 0
        return {"currency": app.config["CURRENCY_SYMBOL"], "unread_notification_count": unread}

    @app.before_request
    def _enforce_session_tracking():
        """Backs the inactivity timeout and remote session revocation. The
        Flask-Login cookie alone doesn't know about SESSION_TIMEOUT_MINUTES
        or a "revoke this device" click from the profile page — this checks
        the server-side UserSession row that start_tracked_session() created
        at login and logs the user out if it's missing, revoked, or stale."""
        from flask_login import current_user, logout_user
        from security_utils import touch_current_session, SESSION_TOKEN_KEY

        if not current_user.is_authenticated:
            return
        if request.path.startswith("/static/"):
            return

        token = session.get(SESSION_TOKEN_KEY)
        entry = touch_current_session(token)
        if entry is None:
            logout_user()
            session.clear()
            flash("Your session has expired — please sign in again.", "info")

    @app.errorhandler(429)
    def rate_limited(e):
        message = "Too many attempts — please wait a minute and try again."
        if request.path.startswith("/assistant/ask"):
            from flask import jsonify
            return jsonify({"error": message}), 429
        return render_template("500.html", code=429, override_message=message), 429

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def too_large(e):
        max_mb = app.config.get("MAX_CONTENT_LENGTH", 0) // (1024 * 1024)
        return render_template("500.html", code=413, override_message=f"That file is too large (max {max_mb}MB)."), 413

    @app.errorhandler(500)
    def server_error(e):
        # A failed request can leave the SQLAlchemy session in a broken
        # state for anything rendered afterward (e.g. the error page's own
        # nav queries) — roll back before rendering so those don't also fail.
        db.session.rollback()
        app.logger.exception("Unhandled server error on %s %s", request.method, request.path)
        return render_template("500.html"), 500

    @app.after_request
    def set_static_cache_headers(response):
        if request.path.startswith("/static/") and not app.config.get("DEBUG"):
            response.headers["Cache-Control"] = "public, max-age=604800"  # 7 days
        return response

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(self)"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        # The UI relies heavily on inline style="" attributes and a few
        # inline <script> blocks (theme switcher, mobile nav) that predate
        # this audit — a strict CSP would break rendering across most pages.
        # This is the practical middle ground: block third-party script/object
        # injection while still allowing the app's existing inline styles.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob: https:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none';"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    with app.app_context():
        db.create_all()

    return app


def _configure_logging(app: Flask) -> None:
    """Render/Railway/most PaaS providers capture stdout/stderr directly —
    logging to a local file would silently vanish on their ephemeral
    filesystems, so this logs to stdout instead and lets the platform
    handle persistence/rotation."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    ))
    level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    app.logger.handlers = [handler]
    app.logger.setLevel(level)
    logging.getLogger("werkzeug").setLevel(logging.WARNING if not app.config.get("DEBUG") else logging.INFO)


if __name__ == "__main__":
    app = create_app()
    # debug is driven entirely by config (DevelopmentConfig.DEBUG = True,
    # ProductionConfig.DEBUG = False) — never hardcoded here, so this can't
    # accidentally ship with Werkzeug's interactive debugger/reloader on
    # in production.
    app.run(debug=app.config["DEBUG"], host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
