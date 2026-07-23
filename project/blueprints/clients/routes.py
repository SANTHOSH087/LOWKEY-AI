from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models import Client, Sale
from blueprints.clients.forms import ClientForm

clients_bp = Blueprint("clients", __name__, template_folder="../../templates/clients")


@clients_bp.route("/")
@login_required
def list_view():
    clients = current_user.clients.order_by(Client.name).all()
    total_pending = float(
        db.session.query(func.coalesce(func.sum(Client.pending_amount), 0))
        .filter(Client.user_id == current_user.id).scalar()
    )
    return render_template("clients/list.html", clients=clients, total_pending=total_pending)


@clients_bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = ClientForm()
    if form.validate_on_submit():
        db.session.add(Client(
            user_id=current_user.id, name=form.name.data, phone=form.phone.data,
            email=form.email.data, address=form.address.data,
            pending_amount=form.pending_amount.data or 0, notes=form.notes.data,
        ))
        db.session.commit()
        flash("Client added.", "success")
        return redirect(url_for("clients.list_view"))
    return render_template("clients/form.html", form=form, mode="create")


@clients_bp.route("/<int:client_id>")
@login_required
def detail(client_id):
    client = current_user.clients.filter_by(id=client_id).first_or_404()
    sales = client.sales.order_by(Sale.sold_on.desc()).all()
    return render_template("clients/detail.html", client=client, sales=sales)


@clients_bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit(client_id):
    client = current_user.clients.filter_by(id=client_id).first_or_404()
    form = ClientForm(obj=client)
    if form.validate_on_submit():
        form.populate_obj(client)
        db.session.commit()
        flash("Client updated.", "success")
        return redirect(url_for("clients.detail", client_id=client.id))
    return render_template("clients/form.html", form=form, mode="edit", client=client)


@clients_bp.route("/<int:client_id>/delete", methods=["POST"])
@login_required
def delete(client_id):
    client = current_user.clients.filter_by(id=client_id).first_or_404()
    if client.sales.count():
        flash("Can't delete a client with sales history — it would erase those records.", "error")
        return redirect(url_for("clients.list_view"))
    db.session.delete(client)
    db.session.commit()
    flash("Client deleted.", "info")
    return redirect(url_for("clients.list_view"))
