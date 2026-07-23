from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db, limiter
from models import ChatMessage
from blueprints.assistant.engine import answer as rule_based_answer, is_finance_question
from blueprints.assistant.llm import ask_llm, build_data_context, LLM_ENABLED

assistant_bp = Blueprint("assistant", __name__, template_folder="../../templates/assistant")

MAX_HISTORY = 50


@assistant_bp.route("/")
@login_required
def chat():
    history = current_user.chat_messages.order_by(ChatMessage.created_at.asc()).limit(MAX_HISTORY).all()
    return render_template("assistant/chat.html", history=history, llm_enabled=LLM_ENABLED)


@assistant_bp.route("/ask", methods=["POST"])
@login_required
@limiter.limit("20 per minute", error_message="You're asking questions faster than I can answer — give it a moment.")
def ask():
    question = (request.form.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Ask me something first."}), 400
    if len(question) > 500:
        return jsonify({"error": "That's a long question — try to keep it under 500 characters."}), 400

    db.session.add(ChatMessage(user_id=current_user.id, role="user", content=question))

    # Only answer finance-related queries. Avoid unrelated LLM chatter.
    if not is_finance_question(question):
        reply = (
            "Ask me anything about your expenses, EMI, bills, income, budgets, savings, loans, invoices, or business finances."
        )
    else:
        reply = None
        if LLM_ENABLED:
            reply = ask_llm(current_user, question, build_data_context(current_user))
        if not reply:
            reply = rule_based_answer(current_user, question)

    db.session.add(ChatMessage(user_id=current_user.id, role="assistant", content=reply))
    db.session.commit()
    return jsonify({"reply": reply})


@assistant_bp.route("/clear", methods=["POST"])
@login_required
def clear():
    current_user.chat_messages.delete()
    db.session.commit()
    flash("Conversation cleared.", "info")
    return redirect(url_for("assistant.chat"))
