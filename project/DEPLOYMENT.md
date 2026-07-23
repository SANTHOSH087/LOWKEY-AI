# Deploying Lowkey AI

This covers pushing the project to GitHub and deploying it on Render (Railway steps are nearly identical — noted inline where they differ).

## 1. Push to GitHub

```bash
cd lowkey-ai
git init
git add .
git commit -m "Lowkey AI — production ready"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

`.gitignore` already excludes `*.db`, `.env`, `instance/`, and `__pycache__/` — double check `git status` before your first commit that nothing sensitive (a real `.env`, a local `lowkey.db` with real data) is staged.

## 2. Generate a production SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Save this — you'll paste it into Render's environment variables in step 4. The app will refuse to start in production without it (see `config.py`).

## 3. Create the Render Web Service

1. [render.com](https://render.com) → **New +** → **Web Service**
2. Connect your GitHub account and select the repo
3. Settings:
   | Setting | Value |
   |---|---|
   | Environment | Python 3 |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn -c gunicorn.conf.py wsgi:app` |
   | Instance Type | Free or Starter (Starter recommended — Free tier spins down on idle, which is rough for a finance app) |

Render reads `runtime.txt` automatically to pick the Python version.

## 4. Environment variables (Render dashboard → Environment)

| Key | Value | Required |
|---|---|---|
| `FLASK_CONFIG` | `production` | Yes |
| `SECRET_KEY` | the value from step 2 | Yes — app won't boot without it |
| `DATABASE_URL` | see step 5 | Recommended |
| `OPENAI_API_KEY` | your key | Optional — enables LLM-enhanced assistant replies |
| `OPENAI_MODEL` | e.g. `gpt-4o-mini` | Optional |
| `LOG_LEVEL` | `info` | Optional |
| `SESSION_TIMEOUT_MINUTES` | e.g. `30` | Optional — defaults to 30 |
| `RATELIMIT_STORAGE_URI` | Redis URL | Only if running >1 worker/instance — see step 10 |
| `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_SERVER` / `MAIL_PORT` | your SMTP provider's values | Optional — see step 11 |
| `CLAMD_HOST` / `CLAMD_PORT` | your ClamAV daemon's address | Optional — see step 12 |

Full reference with comments: `.env.example`.

## 5. Database — read this before you deploy

The app works out of the box with SQLite (no `DATABASE_URL` set) and will create `instance/lowkey.db` automatically on first boot. **This is fine for trying things out, but not for real use on Render/Railway**: their free/starter filesystems are ephemeral, so the SQLite file (and any OCR receipt images saved under `instance/uploads/`) can be wiped on every redeploy or restart.

For anything beyond a quick demo:

1. Render → **New +** → **PostgreSQL** (or use Railway's built-in Postgres plugin)
2. Copy the **Internal Database URL**
3. Paste it into your web service's `DATABASE_URL` environment variable

`config.py` accepts both `postgres://` and `postgresql://` schemes (Render/Railway sometimes hand out the older `postgres://` prefix — it's normalized automatically) and `psycopg2-binary` is already in `requirements.txt`, so no extra setup is needed beyond setting the variable.

The app calls `db.create_all()` on startup, which creates any missing tables but does **not** run migrations — there's no Alembic/Flask-Migrate in this project yet. That's fine for the current schema; if you add or change columns after going live, you'll need to either add a migration tool or handle the schema change manually (e.g. via Render's Postgres shell).

## 6. Receipt uploads (OCR module) in production

Uploaded receipt images are saved under `instance/uploads/receipts/<user_id>/` on local disk. On Render/Railway's ephemeral filesystem, these are lost on redeploy — same caveat as SQLite above. For production use beyond testing, this would need to move to persistent object storage (e.g. an S3-compatible bucket); that's not implemented in the current codebase and is a reasonable next step, not something silently broken.

## 7. Tesseract OCR system dependency

The OCR scanner uses `pytesseract`, which shells out to the `tesseract` binary — it is **not** a Python package and won't be installed by `pip install -r requirements.txt` alone. Render's default Python environment does not include it.

Add a `render-build.sh` (or use Render's "Native Environment" with a build command) that installs it, e.g.:

```bash
apt-get update && apt-get install -y tesseract-ocr
```

Alternatively, deploy via a Dockerfile that installs `tesseract-ocr` in the image — this gives you more control and is the more reliable long-term option if OCR is a core feature. Without this step, every other module works normally; only the OCR scanner will fail.

## 8. Deploy

Click **Create Web Service**. Render will build and start the app. Watch the logs — with `FLASK_CONFIG=production` and a missing `SECRET_KEY`, you'll see it fail fast with a clear error rather than starting insecurely; that's intentional (see `config.py`).

Once it's live, smoke-test:
- Register a new account
- Add an expense and check the dashboard updates
- Open the AI Assistant and ask a question
- Try the OCR scanner (only after step 7, if you need it)

## 9. Custom domain + HTTPS

Render provisions a free TLS certificate automatically for both its `*.onrender.com` subdomain and any custom domain you attach (Settings → Custom Domains). No extra configuration needed — `wsgi.py`'s `ProxyFix` middleware and `config.py`'s `SESSION_COOKIE_SECURE=True` already assume you're running behind exactly this kind of TLS-terminating proxy.

## 10. Rate limiting storage — single vs. multi-worker deployments

Login/registration/password-reset/2FA/AI-chat rate limits (Flask-Limiter) default to in-memory storage. That's correct and sufficient for a single Gunicorn worker (see `gunicorn.conf.py` — check how many workers it's configured for). If you scale to more than one worker or more than one instance, each process keeps its own separate counters, so the real effective limit becomes your configured limit multiplied by the number of processes — not a security hole exactly, but not what you configured either.

Fix: add a Redis instance (Render and Railway both offer one as an add-on) and set `RATELIMIT_STORAGE_URI` to its connection string. No code changes needed — `extensions.py` reads it from config automatically.

## 11. Two-factor authentication — no setup required

2FA is TOTP-based (RFC 6238), using the `pyotp` library — it works entirely by generating a shared secret and comparing time-based codes, with no external service, API key, or account to set up. Users enable it from Profile → Security, scan the QR code with Google Authenticator, Authy, 1Password, or any standard TOTP app, and it works immediately. Nothing to configure here.

## 12. Email configuration (password reset + suspicious-login alerts)

If `MAIL_USERNAME` is left unset, the app doesn't fail — it writes the email content to the application log instead of sending it (see `security_utils.send_email`). This means password reset and the rest of the auth flow are fully testable locally without setting up SMTP. For real delivery in production, set:

```
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=1
MAIL_USERNAME=you@yourdomain.com
MAIL_PASSWORD=your-smtp-password-or-app-password
MAIL_DEFAULT_SENDER=no-reply@yourdomain.com
```

**Gmail**: you can't use your regular password — enable 2-Step Verification on the Google account, then generate an [App Password](https://myaccount.google.com/apppasswords) and use that as `MAIL_PASSWORD`.

**SendGrid / Mailgun / Postmark / etc.**: any of these work fine — use the SMTP credentials they give you (`MAIL_SERVER` is usually something like `smtp.sendgrid.net`, and `MAIL_USERNAME` is often a fixed value like `apikey` with the real key as `MAIL_PASSWORD` — check your provider's SMTP docs). These are generally more reliable than Gmail for transactional email at any real volume and less likely to get flagged as spam.

## 13. ClamAV malware scanning (optional)

This is opt-in — if `CLAMD_HOST` is unset, uploaded receipt images skip the ClamAV scan step entirely, and extension whitelist + size limit + real MIME-sniffing (via the `filetype` library, which checks actual file bytes rather than trusting the filename) still apply regardless. OCR isn't broken for anyone who hasn't set this up.

To enable it, you need a running `clamd` daemon the app can reach over the network — this is a separate long-running process, not something `pip install` gives you.

**Render/Railway**: run ClamAV as a sidecar via Docker. A minimal setup:
1. Deploy a second service from the `clamav/clamav` Docker image, exposing port 3310
2. Point `CLAMD_HOST` at that service's internal address and `CLAMD_PORT=3310`
3. Note ClamAV's virus definitions are several hundred MB and take a minute or two to load on cold start — the first scan after a restart may need to wait for that

**Local development / self-hosted**:
```bash
# Debian/Ubuntu
sudo apt-get install clamav-daemon
sudo freshclam        # download virus definitions
sudo systemctl start clamav-daemon
```
Then set `CLAMD_HOST=localhost` and `CLAMD_PORT=3310`.

If the daemon is unreachable when a scan is attempted (wrong host, still starting up, etc.), the app logs a warning and lets the upload through on the other checks rather than blocking all uploads — a misconfigured or temporarily-down scanner shouldn't take down the OCR feature for everyone.

## Railway differences

- Build/start commands are set the same way in Railway's service settings
- Railway injects `PORT` automatically, same as Render — `gunicorn.conf.py` already reads it
- Railway's Postgres plugin gives you a `DATABASE_URL` variable directly — same format, same caveats as step 5
- Railway containers are also ephemeral by default — same OCR/SQLite caveats apply
