from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from extensions import db
from models import Notification

notifications_bp = Blueprint("notifications", __name__, template_folder="../../templates/notifications")

KIND_LABELS = {
    "budget": "Budget", "emi": "EMI", "loan": "Loan", "invoice": "Invoice",
    "stock": "Low Stock", "ai": "AI Insight", "summary": "Summary", "info": "Info",
}
PER_PAGE = 15


@notifications_bp.route("/")
@login_required
def list_view():
    kind_filter = request.args.get("kind", "")
    page = request.args.get("page", 1, type=int)

    query = current_user.notifications.order_by(Notification.created_at.desc())
    if kind_filter and kind_filter in KIND_LABELS:
        query = query.filter_by(kind=kind_filter)

    pagination = query.paginate(page=page, per_page=PER_PAGE, error_out=False)
    unread_count = current_user.notifications.filter_by(is_read=False).count()

    return render_template(
        "notifications/list.html",
        pagination=pagination, notifications=pagination.items,
        kind_filter=kind_filter, kind_labels=KIND_LABELS, unread_count=unread_count,
    )


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id):
    notif = current_user.notifications.filter_by(id=notification_id).first_or_404()
    notif.is_read = True
    db.session.commit()
    next_url = request.form.get("next") or url_for("notifications.list_view")
    return redirect(next_url)


@notifications_bp.route("/mark-all-read", methods=["POST"])
@login_required
def mark_all_read():
    current_user.notifications.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(request.form.get("next") or url_for("notifications.list_view"))


@notifications_bp.route("/<int:notification_id>/delete", methods=["POST"])
@login_required
def delete(notification_id):
    notif = current_user.notifications.filter_by(id=notification_id).first_or_404()
    db.session.delete(notif)
    db.session.commit()
    flash("Notification deleted.", "info")
    return redirect(request.form.get("next") or url_for("notifications.list_view"))


@notifications_bp.route("/<int:notification_id>/open", methods=["POST"])
@login_required
def open_notification(notification_id):
    """Mark read AND jump straight to the linked module in one action —
    what a bell-icon dropdown click should feel like."""
    notif = current_user.notifications.filter_by(id=notification_id).first_or_404()
    notif.is_read = True
    db.session.commit()
    return redirect(notif.link or url_for("notifications.list_view"))
