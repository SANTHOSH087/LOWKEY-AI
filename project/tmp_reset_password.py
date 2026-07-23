import os, sys
sys.path.insert(0, os.getcwd())
from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    user = db.session.query(User).first()
    if not user:
        print('No user found')
        sys.exit(1)
    user.set_password('password123')
    db.session.commit()
    print('Set password123 for', user.email)
