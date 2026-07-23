"""
Real PDF generation for invoices via reportlab, and a real QR code (not a
placeholder image) via the qrcode library. Both produce actual bytes that
were verified in testing — the PDF's text was extracted and checked, and
the QR was decoded back to its original payload.
"""
import io
import os
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Helvetica (reportlab's default) has no glyph for ₹ (U+20B9) — it silently
# prints a box/missing-glyph character instead of erroring, which is why
# this needed a real PDF text-extraction test to catch, not just "does a
# PDF get produced." DejaVu Sans does have the glyph, so it's bundled with
# the project (static/fonts/) rather than depended on as a system font,
# which may not be present wherever this actually gets deployed.
_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "fonts")
FONT_REGULAR, FONT_BOLD, FONT_OBLIQUE = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
try:
    pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", os.path.join(_FONT_DIR, "DejaVuSans-Oblique.ttf")))
    FONT_REGULAR, FONT_BOLD, FONT_OBLIQUE = "DejaVuSans", "DejaVuSans-Bold", "DejaVuSans-Oblique"
except Exception:
    # falls back to Helvetica — the ₹ symbol will render incorrectly, but the
    # PDF still generates rather than 500ing if the font files are missing
    pass


def generate_invoice_qr(invoice, currency_symbol="₹") -> bytes:
    """QR encodes a simple structured payload — enough for a phone camera
    to read the invoice number and amount due without opening an app.

    Deliberately ASCII-only ('INR', not '₹'): QR byte-mode without an
    explicit ECI segment is ambiguous for non-ASCII text, and real-world
    scanners are inconsistent about resolving it — confirmed here by
    testing that this environment's zbar mangles ANY non-ASCII character
    (₹, €, £ alike), not something specific to the Rupee sign. Production
    payment QR formats (UPI intents included) stick to ASCII for exactly
    this reason."""
    payload = (
        f"Invoice: {invoice.invoice_number}\n"
        f"Amount: INR {invoice.grand_total():,.2f}\n"
        f"Status: {invoice.effective_status()}"
    )
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_invoice_pdf(invoice, user, currency_symbol="₹") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    y = height - margin

    # ---- Header ----
    c.setFont(FONT_BOLD, 20)
    c.drawString(margin, y, "Lowkey AI")
    c.setFont(FONT_REGULAR, 9)
    c.setFillColor(colors.grey)
    c.drawString(margin, y - 14, "Invoice")
    c.setFillColor(colors.black)

    c.setFont(FONT_BOLD, 14)
    c.drawRightString(width - margin, y, invoice.invoice_number)
    c.setFont(FONT_REGULAR, 9)
    c.setFillColor(colors.grey)
    c.drawRightString(width - margin, y - 14, f"Status: {invoice.effective_status()}")
    c.setFillColor(colors.black)

    y -= 40
    c.line(margin, y, width - margin, y)
    y -= 20

    # ---- Meta: dates + client ----
    c.setFont(FONT_REGULAR, 10)
    c.drawString(margin, y, f"Issued: {invoice.issued_on.strftime('%d %b %Y')}")
    if invoice.due_on:
        c.drawString(margin + 90, y, f"Due: {invoice.due_on.strftime('%d %b %Y')}")

    if invoice.client:
        c.setFont(FONT_BOLD, 10)
        c.drawRightString(width - margin, y, invoice.client.name)
        c.setFont(FONT_REGULAR, 9)
        c.setFillColor(colors.grey)
        if invoice.client.phone:
            y -= 12
            c.drawRightString(width - margin, y, invoice.client.phone)
        if invoice.client.email:
            y -= 12
            c.drawRightString(width - margin, y, invoice.client.email)
        c.setFillColor(colors.black)

    y -= 30

    # ---- Line items table ----
    col_desc, col_qty, col_price, col_gst, col_total = margin, width - margin - 220, width - margin - 160, width - margin - 100, width - margin
    c.setFont(FONT_BOLD, 9)
    c.drawString(col_desc, y, "DESCRIPTION")
    c.drawRightString(col_qty, y, "QTY")
    c.drawRightString(col_price, y, "PRICE")
    c.drawRightString(col_gst, y, "GST")
    c.drawRightString(col_total, y, "TOTAL")
    y -= 6
    c.line(margin, y, width - margin, y)
    y -= 14

    c.setFont(FONT_REGULAR, 9)
    for item in invoice.items:
        if y < 100:  # simple pagination guard
            c.showPage()
            y = height - margin
            c.setFont(FONT_REGULAR, 9)
        c.drawString(col_desc, y, item.description[:48])
        c.drawRightString(col_qty, y, f"{float(item.quantity):g}")
        c.drawRightString(col_price, y, f"{currency_symbol}{float(item.unit_price):,.2f}")
        c.drawRightString(col_gst, y, f"{float(item.gst_rate):g}%")
        c.drawRightString(col_total, y, f"{currency_symbol}{item.line_total():,.2f}")
        y -= 16

    y -= 10
    c.line(width / 2, y, width - margin, y)
    y -= 18

    # ---- Totals ----
    def totals_row(label, value, bold=False):
        nonlocal y
        c.setFont(FONT_BOLD if bold else FONT_REGULAR, 10 if bold else 9)
        c.drawString(width / 2 + 10, y, label)
        c.drawRightString(col_total, y, f"{currency_symbol}{value:,.2f}")
        y -= 16

    totals_row("Subtotal", invoice.subtotal())
    if invoice.discount_amount():
        totals_row("Discount", -invoice.discount_amount())
    for rate, amount in sorted(invoice.tax_summary().items()):
        if amount:
            totals_row(f"GST {rate:g}%", amount)
    totals_row("Grand Total", invoice.grand_total(), bold=True)
    if invoice.paid_amount():
        totals_row("Paid", invoice.paid_amount())
        totals_row("Balance Due", invoice.balance_due(), bold=True)

    # ---- QR code ----
    qr_bytes = generate_invoice_qr(invoice, currency_symbol)
    qr_img = ImageReader(io.BytesIO(qr_bytes))
    qr_size = 28 * mm
    c.drawImage(qr_img, margin, margin, width=qr_size, height=qr_size)

    if invoice.notes:
        c.setFont(FONT_OBLIQUE, 8)
        c.setFillColor(colors.grey)
        c.drawString(margin + qr_size + 10, margin + qr_size / 2, invoice.notes[:100])
        c.setFillColor(colors.black)

    c.showPage()
    c.save()
    return buf.getvalue()
