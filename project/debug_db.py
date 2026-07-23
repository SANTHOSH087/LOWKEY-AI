import os
import sys
sys.path.insert(0, os.getcwd())
from app import create_app
from extensions import db
from models import User, Expense, Income
from datetime import date
import calendar

app = create_app()
with app.app_context():
    users = db.session.query(User).limit(3).all()
    print('DB URI:', app.config.get('SQLALCHEMY_DATABASE_URI'))
    for user in users:
        exp_count = db.session.query(Expense).filter(Expense.user_id == user.id).count()
        inc_count = db.session.query(Income).filter(Income.user_id == user.id).count()
        print('USER', user.id, getattr(user, 'email', None), 'EXP', exp_count, 'INC', inc_count)
        today = date.today()
        start = today.replace(day=1)
        end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        exp_month = db.session.query(Expense).filter(Expense.user_id == user.id, Expense.spent_on.between(start, end)).all()
        inc_month = db.session.query(Income).filter(Income.user_id == user.id, Income.received_on.between(start, end)).all()
        print('  this month exp count', len(exp_month), 'inc count', len(inc_month))
        print('  exp dates', [e.spent_on.isoformat() for e in exp_month])
        print('  inc dates', [i.received_on.isoformat() for i in inc_month])
