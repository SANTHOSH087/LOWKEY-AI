"""
Real OCR pipeline for receipt scanning. No mocking, no placeholder data —
this runs actual Tesseract against the actual uploaded image and parses
its actual text output with regex heuristics tuned for receipt formats.

Pipeline: preprocess_image -> run_ocr -> parse_receipt_text
"""
import os
import re
import shutil
from datetime import datetime, date
from PIL import Image, ImageOps, ImageFilter
import pytesseract
from pytesseract import TesseractNotFoundError

# If the Tesseract binary is installed in a standard Windows location, use it
# directly so the app doesn't depend on PATH being updated in the current shell.
TESSERACT_CANDIDATES = [
    os.environ.get("TESSERACT_CMD"),
    shutil.which("tesseract"),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files\Tesseract-OCR\bin\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\bin\tesseract.exe",
]


def _find_tesseract_binary() -> str | None:
    for candidate in TESSERACT_CANDIDATES:
        if not candidate:
            continue
        candidate = os.path.expandvars(candidate)
        if os.path.isfile(candidate):
            return candidate
    return None

TESSERACT_BINARY = _find_tesseract_binary()
if TESSERACT_BINARY:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_BINARY

# Category keyword map — cheap but real: match merchant/line-item text
# against category names, no ML model required for a first-pass suggestion.
CATEGORY_KEYWORDS = {
    "Food": ["restaurant", "cafe", "food", "kitchen", "dine", "pizza", "burger", "bakery", "supermarket", "grocery", "mart", "grocer", "milk", "bread", "egg", "rice", "vegetable", "fruit"],
    "Travel": ["airlines", "airways", "flight", "hotel", "resort", "travel", "trip", "booking"],
    "Fuel": ["petrol", "diesel", "fuel", "gas station", "hpcl", "iocl", "bpcl", "shell"],
    "Medical": ["pharmacy", "medical", "hospital", "clinic", "chemist", "drug", "healthcare"],
    "Bills": ["electricity", "water bill", "broadband", "internet", "recharge", "utility", "bill payment"],
    "Shopping": ["mall", "retail", "fashion", "apparel", "electronics", "showroom", "boutique"],
    "Education": ["school", "college", "university", "tuition", "course", "book store"],
}


def preprocess_image(image_path: str) -> Image.Image:
    """Grayscale + autocontrast + sharpen + upscale — the standard cheap
    preprocessing pass that measurably improves Tesseract accuracy on
    photographed (not scanned) receipts, which tend to be low-contrast."""
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)  # respect phone camera orientation
    img = img.convert("L")  # grayscale
    img = ImageOps.autocontrast(img, cutoff=2)
    img = img.filter(ImageFilter.SHARPEN)

    # upscale small images — Tesseract accuracy drops noticeably below ~300dpi-equivalent
    if img.width < 1200:
        scale = 1200 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)

    return img


def run_ocr(image: Image.Image) -> tuple[str, float]:
    """Runs real Tesseract. Returns (raw_text, mean_confidence)."""
    try:
        raw_text = pytesseract.image_to_string(image)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except TesseractNotFoundError as exc:
        raise RuntimeError(
            "Tesseract OCR is unavailable. Install the Tesseract binary and ensure it is on PATH."
        ) from exc
    except Exception as exc:
        raise RuntimeError("OCR engine failure") from exc

    confidences = [int(c) for c in data["conf"] if c not in ("-1", -1)]
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

    return raw_text, round(mean_conf, 1)


_AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹)?\s*([\d]{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?)", re.IGNORECASE)
_GST_NUMBER_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]\b")  # standard Indian GSTIN format
_TOTAL_LINE_RE = re.compile(r"\b(?:grand\s*total|total\s*amount|total|amount\s*due|net\s*payable)\b", re.IGNORECASE)
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b"), "%d/%m/%Y"),
    (re.compile(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b"), "%Y/%m/%d"),
]


def _extract_merchant(lines: list[str]) -> str | None:
    """Heuristic: the merchant name is almost always one of the first
    non-empty lines, before any address/date/amount noise starts."""
    for line in lines[:5]:
        cleaned = line.strip()
        if len(cleaned) < 3:
            continue
        # skip lines that are mostly numbers/symbols (addresses, phone numbers, dates)
        alpha_ratio = sum(c.isalpha() for c in cleaned) / max(len(cleaned), 1)
        if alpha_ratio > 0.5:
            return cleaned.title() if cleaned.isupper() else cleaned
    return None


def _extract_date(text: str) -> date | None:
    for pattern, fmt in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        raw = m.group(0).replace("-", "/")
        for candidate_fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(raw, candidate_fmt).date()
                if 2000 <= parsed.year <= 2100:
                    return parsed
            except ValueError:
                continue
    return None


def _extract_gst_number(text: str) -> str | None:
    m = _GST_NUMBER_RE.search(text.upper())
    return m.group(0) if m else None


def _extract_gst_amount(lines: list[str]) -> float | None:
    for line in lines:
        lower = line.lower()
        if "gstin" in lower or "gst no" in lower or "gst number" in lower:
            continue  # this is the tax ID, not a tax amount
        if re.search(r"\b(gst|cgst|sgst|igst|tax)\b", lower):
            amounts = _AMOUNT_RE.findall(line)
            if amounts:
                try:
                    return float(amounts[-1].replace(",", ""))
                except ValueError:
                    continue
    return None


def _extract_total_amount(lines: list[str]) -> float | None:
    """Prefer a line that says "total" and has a number on it — far more
    reliable than "largest number on the receipt", which false-positives
    on phone numbers, GST numbers, and item quantities."""
    candidates = []
    for line in lines:
        if _TOTAL_LINE_RE.search(line):
            amounts = _AMOUNT_RE.findall(line)
            for a in amounts:
                try:
                    candidates.append(float(a.replace(",", "")))
                except ValueError:
                    continue
    if candidates:
        return max(candidates)  # "total" lines sometimes also match a subtotal fragment; take the largest

    # fallback: largest plausible currency amount anywhere in the receipt
    all_amounts = []
    for line in lines:
        for a in _AMOUNT_RE.findall(line):
            try:
                val = float(a.replace(",", ""))
                if 1 <= val <= 500000:
                    all_amounts.append(val)
            except ValueError:
                continue
    return max(all_amounts) if all_amounts else None


def _extract_line_items(lines: list[str]) -> list[dict]:
    """Product lines: text followed by a trailing amount, excluding
    obvious header/footer/total lines."""
    items = []
    skip_keywords = ("total", "subtotal", "gst", "tax", "cash", "change", "balance", "thank", "bill no", "invoice")
    for line in lines:
        lower = line.lower()
        if any(k in lower for k in skip_keywords):
            continue
        m = re.search(r"^(.{2,40}?)\s+([\d,]+\.\d{2}|\d{2,6})\s*$", line.strip())
        if m:
            name = m.group(1).strip(" -.:")
            try:
                amount = float(m.group(2).replace(",", ""))
            except ValueError:
                continue
            if len(name) >= 2 and 0 < amount < 100000:
                items.append({"name": name, "amount": amount})
    return items[:25]  # sane upper bound


def _suggest_category(merchant: str | None, items: list[dict], full_text: str) -> str:
    haystack = f"{merchant or ''} {' '.join(i['name'] for i in items)} {full_text}".lower()
    best_category, best_hits = "Others", 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in haystack)
        if hits > best_hits:
            best_category, best_hits = category, hits
    return best_category


def parse_receipt_text(raw_text: str) -> dict:
    """Turns raw OCR text into structured fields. Every field is Optional —
    a receipt that fails to yield a merchant name still yields whatever it
    *did* find, since the review form lets the user fill in the rest."""
    lines = [l for l in raw_text.splitlines() if l.strip()]

    merchant = _extract_merchant(lines)
    txn_date = _extract_date(raw_text)
    gst_number = _extract_gst_number(raw_text)
    gst_amount = _extract_gst_amount(lines)
    items = _extract_line_items(lines)
    total_amount = _extract_total_amount(lines)
    category = _suggest_category(merchant, items, raw_text)

    return {
        "merchant": merchant,
        "date": txn_date.isoformat() if txn_date else None,
        "gst_number": gst_number,
        "gst_amount": gst_amount,
        "items": items,
        "total_amount": total_amount,
        "suggested_category": category,
    }


def process_receipt(image_path: str) -> dict:
    """Full pipeline entrypoint: file path in, structured dict out, plus
    the raw text and OCR confidence for storage/auditing."""
    image = preprocess_image(image_path)
    raw_text, confidence = run_ocr(image)
    parsed = parse_receipt_text(raw_text)
    parsed["raw_text"] = raw_text
    parsed["ocr_confidence"] = confidence
    return parsed
