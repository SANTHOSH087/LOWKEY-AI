from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()

# Storage defaults to in-memory, which is fine for a single-process/single-
# dyno deployment (matches this app's SQLite-by-default posture). For a
# multi-worker/multi-instance production deployment behind Gunicorn with
# more than one worker, set RATELIMIT_STORAGE_URI to a shared Redis instance
# — otherwise each worker process tracks its own separate counts. Documented
# in .env.example / DEPLOYMENT.md.
limiter = Limiter(key_func=get_remote_address, default_limits=[])

login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"
