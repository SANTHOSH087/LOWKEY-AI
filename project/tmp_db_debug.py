import os, sys
sys.path.insert(0, os.getcwd())
from app import create_app
from extensions import db
from models import User, Expense, Income

app = create_app()
with app.app_context():
    user = db.session.query(User).first()
    print('user:', user.id, user.email)
    expenses = db.session.query(Expense).filter(Expense.user_id == user.id).order_by(Expense.spent_on.desc()).limit(5).all()
    incomes = db.session.query(Income).filter(Income.user_id == user.id).order_by(Income.received_on.desc()).limit(5).all()
    print('expenses count', db.session.query(Expense).filter(Expense.user_id == user.id).count())
    print('incomes count', db.session.query(Income).filter(Income.user_id == user.id).count())
    print('recent expenses', [(e.spent_on.isoformat(), float(e.amount), e.category.name if e.category else None) for e in expenses])
    print('recent incomes', [(i.received_on.isoformat(), float(i.amount), i.source) for i in incomes])
