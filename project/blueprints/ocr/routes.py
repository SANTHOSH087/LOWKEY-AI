import os
import json
import uuid
from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Receipt, Expense, Category
from blueprints.ocr.pipeline import process_receipt
from blueprints.expenses.forms import ExpenseForm
from security_utils import validate_upload_mime, scan_for_malware, log_event

ocr_bp = Blueprint("ocr", __name__, template_folder="../../templates/ocr")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _receipts_dir() -> str:
    path = os.path.join(current_app.instance_path, "uploads", "receipts", str(current_user.id))
    os.makedirs(path, exist_ok=True)
    return path


@ocr_bp.route("/")
@login_required
def scanner():
    return render_template("ocr/scanner.html")


@ocr_bp.route("/scan", methods=["POST"])
@login_required
def scan():
    file = request.files.get("receipt_image")
    if not file or file.filename == "":
        flash("No image received — try again.", "error")
        return redirect(url_for("ocr.scanner"))

    if not _allowed(file.filename):
        flash("Unsupported file type. Upload a PNG, JPG, or WEBP.", "error")
        return redirect(url_for("ocr.scanner"))

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        flash("Image is too large (max 8MB).", "error")
        return redirect(url_for("ocr.scanner"))

    # Extension whitelist (above) only checks the filename, which is
    # trivially spoofable — sniff the actual file content (magic bytes) so
    # a renamed non-image file doesn't pass just because it's called
    # "receipt.jpg".
    file_bytes = file.read()
    file.seek(0)
    mime_ok, mime_reason = validate_upload_mime(file_bytes)
    if not mime_ok:
        log_event("upload_blocked", user=current_user, detail=f"MIME check failed: {mime_reason}")
        current_app.logger.warning("Blocked upload from user_id=%s: %s", current_user.id, mime_reason)
        flash("That file doesn't look like a valid image — try a different photo.", "error")
        return redirect(url_for("ocr.scanner"))

    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    save_path = os.path.join(_receipts_dir(), secure_filename(filename))
    file.save(save_path)

    # Optional ClamAV scan (no-op if CLAMD_HOST isn't configured — see
    # DEPLOYMENT.md). Runs after save since clamd scans a file path, not a
    # stream; the file is removed immediately if anything is found.
    clean, scan_reason = scan_for_malware(save_path)
    if not clean:
        os.remove(save_path)
        log_event("upload_blocked", user=current_user, detail=f"Malware scan: {scan_reason}")
        current_app.logger.warning("Blocked malicious upload from user_id=%s: %s", current_user.id, scan_reason)
        flash("That file was rejected by malware scanning and has not been saved.", "error")
        return redirect(url_for("ocr.scanner"))

    try:
        parsed = process_receipt(save_path)
    except RuntimeError as exc:  # OCR/image failures shouldn't 500 the request
        current_app.logger.exception("OCR pipeline failed")
        message = str(exc)
        if "Tesseract OCR is unavailable" in message:
            flash(
                "OCR is unavailable because the Tesseract binary isn't installed or is not on PATH. "
                "Install Tesseract and try again, or add the expense manually.",
                "error",
            )
        else:
            flash(
                f"Couldn't read that image ({message}). Try a clearer photo, or enter the expense manually.",
                "error",
            )
        os.remove(save_path)
        return redirect(url_for("ocr.scanner"))
    except Exception as exc:
        current_app.logger.exception("OCR pipeline failed")
        flash(
            f"Couldn't read that image ({exc}). Try a clearer photo, or enter the expense manually.",
            "error",
        )
        os.remove(save_path)
        return redirect(url_for("ocr.scanner"))

    receipt = Receipt(
        user_id=current_user.id,
        image_path=os.path.relpath(save_path, current_app.instance_path),
        raw_text=parsed["raw_text"],
        ocr_confidence=parsed["ocr_confidence"],
        parsed_json=json.dumps(parsed),
    )
    db.session.add(receipt)
    db.session.commit()

    return redirect(url_for("ocr.review", receipt_id=receipt.id))


@ocr_bp.route("/<int:receipt_id>/review", methods=["GET", "POST"])
@login_required
def review(receipt_id):
    receipt = current_user.receipts.filter_by(id=receipt_id).first_or_404()
    parsed = receipt.parsed()

    form = ExpenseForm()
    form.category_id.choices = [(c.id, f"{c.icon} {c.name}") for c in current_user.categories.order_by(Category.name)]

    if request.method == "GET":
        # pre-populate the real Add Expense form with what OCR found —
        # the user reviews/edits every field before anything is saved
        if parsed.get("total_amount"):
            form.amount.data = parsed["total_amount"]
        if parsed.get("date"):
            try:
                form.spent_on.data = datetime.strptime(parsed["date"], "%Y-%m-%d").date()
            except ValueError:
                form.spent_on.data = date.today()
        else:
            form.spent_on.data = date.today()
        if parsed.get("merchant"):
            form.description.data = parsed["merchant"]

        suggested = parsed.get("suggested_category")
        if suggested:
            match = current_user.categories.filter_by(name=suggested).first()
            if match:
                form.category_id.data = match.id

    if form.validate_on_submit():
        gst_raw = request.form.get("gst_amount", "").strip()
        gst_amount = float(gst_raw) if gst_raw else parsed.get("gst_amount")

        expense = Expense(
            user_id=current_user.id,
            receipt_id=receipt.id,
            amount=form.amount.data,
            gst_amount=gst_amount,
            category_id=form.category_id.data,
            description=form.description.data,
            payment_method=form.payment_method.data,
            location=form.location.data,
            tags=form.tags.data,
            receipt_url=url_for("ocr.receipt_image", receipt_id=receipt.id),
            spent_on=form.spent_on.data,
            is_recurring=form.is_recurring.data,
            recurring_interval=form.recurring_interval.data or None,
        )
        db.session.add(expense)
        db.session.commit()
        flash("Expense saved from scanned receipt.", "success")
        return redirect(url_for("expenses.list_view"))

    return render_template(
        "ocr/review.html",
        form=form,
        receipt=receipt,
        parsed=parsed,
    )


@ocr_bp.route("/receipt/<int:receipt_id>/image")
@login_required
def receipt_image(receipt_id):
    from flask import send_from_directory

    receipt = current_user.receipts.filter_by(id=receipt_id).first_or_404()
    full_path = os.path.join(current_app.instance_path, receipt.image_path)
    directory, filename = os.path.split(full_path)
    if not os.path.exists(full_path):
        abort(404)
    return send_from_directory(directory, filename)
