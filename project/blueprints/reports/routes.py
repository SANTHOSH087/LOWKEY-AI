import csv
import io

from flask import Blueprint, render_template, request, Response
from flask_login import login_required, current_user

from blueprints.reports.engine import build_report, resolve_period, REPORT_TYPES, PERIODS
from blueprints.reports.pdf import render_report_pdf
from blueprints.reports.excel import render_report_xlsx

reports_bp = Blueprint("reports", __name__, template_folder="../../templates/reports")

REPORT_TYPE_LABELS = {
    "expense": "Expense", "income": "Income", "business": "Business",
    "loan": "Loan", "emi": "EMI", "category": "Category-wise", "summary": "Financial Summary",
}


def _get_filters():
    report_type = request.args.get("type", "summary")
    period = request.args.get("period", "monthly")
    custom_start = request.args.get("start")
    custom_end = request.args.get("end")
    if report_type not in REPORT_TYPES:
        report_type = "summary"
    if period not in PERIODS:
        period = "monthly"
    start, end, label = resolve_period(period, custom_start, custom_end)
    return report_type, period, custom_start, custom_end, start, end, label


@reports_bp.route("/", strict_slashes=False)
@login_required
def index():
    report_type, period, custom_start, custom_end, start, end, label = _get_filters()
    report = build_report(current_user, report_type, start, end)
    return render_template(
        "reports/index.html",
        report=report, period_label=label, report_type=report_type, period=period,
        custom_start=custom_start or start.isoformat(), custom_end=custom_end or end.isoformat(),
        report_types=REPORT_TYPES, periods=PERIODS, type_labels=REPORT_TYPE_LABELS,
        start=start, end=end,
    )


@reports_bp.route("/export.pdf")
@login_required
def export_pdf():
    report_type, period, custom_start, custom_end, start, end, label = _get_filters()
    report = build_report(current_user, report_type, start, end)
    pdf_bytes = render_report_pdf(report, label, REPORT_TYPE_LABELS[report_type])
    filename = f"lowkey-{report_type}-report-{start.isoformat()}-to-{end.isoformat()}.pdf"
    return Response(pdf_bytes, mimetype="application/pdf",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


@reports_bp.route("/export.xlsx")
@login_required
def export_xlsx():
    report_type, period, custom_start, custom_end, start, end, label = _get_filters()
    report = build_report(current_user, report_type, start, end)
    xlsx_bytes = render_report_xlsx(report, label, REPORT_TYPE_LABELS[report_type])
    filename = f"lowkey-{report_type}-report-{start.isoformat()}-to-{end.isoformat()}.xlsx"
    return Response(xlsx_bytes, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


@reports_bp.route("/export.csv")
@login_required
def export_csv():
    report_type, period, custom_start, custom_end, start, end, label = _get_filters()
    report = build_report(current_user, report_type, start, end)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Lowkey AI", f"{REPORT_TYPE_LABELS[report_type]} Report", label])
    writer.writerow([])
    writer.writerow(["Summary"])
    for key, value in report["summary"].items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(report["table_headers"])
    for row in report["table_rows"]:
        writer.writerow([f"{v:.2f}" if isinstance(v, float) else v for v in row])

    filename = f"lowkey-{report_type}-report-{start.isoformat()}-to-{end.isoformat()}.csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})
