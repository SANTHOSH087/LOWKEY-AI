"""Gunicorn configuration for production.

Usage: gunicorn -c gunicorn.conf.py wsgi:app
(this is exactly what the Procfile does)
"""
import multiprocessing
import os

# Render/Railway inject PORT — bind to it, not a hardcoded port.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# A common, conservative starting point for a single small-to-medium dyno/
# instance. (2 x CPU) + 1 is the usual Gunicorn recommendation, but capped
# at 4 here since free/starter tiers on Render and Railway are usually
# 1-2 vCPUs and more workers than that just fights over the same RAM.
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)
worker_class = "sync"
threads = 2

timeout = 60          # generous enough for OCR/PDF/Excel generation requests
graceful_timeout = 30
keepalive = 5

# Render/Railway capture stdout/stderr directly — logging to a file would
# just vanish on their ephemeral filesystems.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Restarting workers periodically guards against slow memory creep over a
# long-running process (e.g. from PDF/OCR libraries); jitter avoids every
# worker restarting at the same moment.
max_requests = 1000
max_requests_jitter = 100

preload_app = True
