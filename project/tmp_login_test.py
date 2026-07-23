import os, sys, re
sys.path.insert(0, os.getcwd())
from app import create_app
from extensions import db
from models import User

app = create_app()
with app.app_context():
    user = db.session.query(User).first()
    print('user:', user.id, user.email)
    print('password123 matches:', user.check_password('password123'))
    with app.test_client() as client:
        login_page = client.get('/auth/login')
        html = login_page.data.decode('utf-8', errors='replace')
        token = None
        m = re.search(r'<input[^>]+name="csrf_token"[^>]+value="([^"]+)"', html)
        if m:
            token = m.group(1)
        print('csrf token:', bool(token))
        response = client.post('/auth/login', data={
            'email': user.email,
            'password': 'password123',
            'remember': 'y',
            'csrf_token': token,
        }, follow_redirects=True)
        print('login status:', response.status_code)
        body = response.data.decode('utf-8', errors='replace')
        print('login failed message:', 'Invalid email or password.' in body)
        print('dashboard canvas present:', 'id="trendChart"' in body)
        print('login title present:', 'Log in to your Lowkey account' in body)
        print('starts with', body[:400].replace('\n',' '))
