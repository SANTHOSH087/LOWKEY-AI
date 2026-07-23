"""Production WSGI entry point.

Gunicorn imports `app` from this module (see Procfile / gunicorn.conf.py:
`gunicorn wsgi:app`). This is intentionally separate from app.py's
`if __name__ == "__main__"` block, which is only for local development via
`python app.py` and binds Werkzeug's dev server -- never used in production.

FLASK_CONFIG should be set to "production" in the deployment environment
(Render/Railway env vars) so this picks up ProductionConfig, which enforces
a real SECRET_KEY, secure cookies, and DEBUG=False. See config.py.
"""
from app import create_app

app = create_app()
