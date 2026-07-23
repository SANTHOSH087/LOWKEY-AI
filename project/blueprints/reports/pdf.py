import io
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "fonts")
FONT_REGULAR, FONT_BOLD = "Helvetica", "Helvetica-Bold"
try:
    pdfmetrics.registerFont(TTFont("DejaVuSans", os.path.join(_FONT_DIR, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")))
    FONT_REGULAR, FONT_BOLD = "DejaVuSans", "DejaVuSans-Bold"
except Exception:
    pass  # falls back to Helvetica (₹ will render incorrectly) rather than 500ing


def _fmt_cell(value) -> str:
    if isinstance(value, float):
        return f"₹{value:,.2f}"
    return str(value)


def render_report_pdf(report: dict, period_label: str, report_type_label: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 20 * 2.834645  # ~20mm in points, kept simple without extra unit import

    y = height - 50
    c.setFont(FONT_BOLD, 18)
    c.drawString(margin, y, "Lowkey AI")
    c.setFont(FONT_REGULAR, 10)
    c.setFillColor(colors.grey)
    c.drawString(margin, y - 16, f"{report_type_label} Report — {period_label}")
    c.setFillColor(colors.black)
    y -= 50

    c.line(margin, y, width - margin, y)
    y -= 24

    # summary key/value block
    c.setFont(FONT_BOLD, 12)
    c.drawString(margin, y, "Summary")
    y -= 18
    c.setFont(FONT_REGULAR, 10)
    for key, value in report["summary"].items():
        if y < 80:
            c.showPage()
            y = height - 50
            c.setFont(FONT_REGULAR, 10)
        c.drawString(margin, y, str(key))
        c.drawRightString(width - margin, y, str(value))
        y -= 16

    y -= 16
    c.line(margin, y, width - margin, y)
    y -= 24

    # table
    headers = report["table_headers"]
    rows = report["table_rows"]
    col_count = len(headers)
    col_width = (width - 2 * margin) / col_count

    def draw_header():
        nonlocal y
        c.setFont(FONT_BOLD, 9)
        c.setFillColor(colors.grey)
        for i, h in enumerate(headers):
            x = margin + i * col_width
            if i == col_count - 1:
                c.drawRightString(width - margin, y, str(h))
            else:
                c.drawString(x, y, str(h))
        c.setFillColor(colors.black)
        y -= 14
        c.line(margin, y + 4, width - margin, y + 4)
        y -= 10

    draw_header()
    c.setFont(FONT_REGULAR, 9)
    for row in rows:
        if y < 60:
            c.showPage()
            y = height - 50
            draw_header()
            c.setFont(FONT_REGULAR, 9)
        for i, cell in enumerate(row):
            x = margin + i * col_width
            text = _fmt_cell(cell) if isinstance(cell, float) else str(cell)
            if i == col_count - 1 and isinstance(cell, float):
                c.drawRightString(width - margin, y, text)
            else:
                c.drawString(x, y, text[:40])
        y -= 13

    if not rows:
        c.setFillColor(colors.grey)
        c.drawString(margin, y, "No data in this period.")
        c.setFillColor(colors.black)

    c.showPage()
    c.save()
    return buf.getvalue()
