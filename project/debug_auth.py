import os
import sys
sys.path.insert(0, os.getcwd())
from app import create_app
from extensions import db
from models import User

app = create_app()

with app.app_context():
    user = db.session.query(User).first()
    print('user', user.id, getattr(user, 'email', None))

with app.test_client() as client:
    login_data = {
        'email': user.email,
        'password': 'password123',
        'remember': 'y',
    }
    # Attempt to determine the user's actual password if available in test data
    print('NOTE: This script assumes the test user password is password123.')
    response = client.post('/auth/login', data=login_data, follow_redirects=True)
    print('login status', response.status_code)
    if b'Invalid email or password' in response.data:
        print('Login failed: invalid credentials; cannot render authenticated pages.')
    else:
        for url in ['/dashboard', '/reports?type=summary&period=monthly', '/reports?type=expense&period=monthly', '/reports?type=income&period=monthly']:
            resp = client.get(url)
            html = resp.data.decode('utf-8', errors='replace')
            print('\nURL', url)
            print('status', resp.status_code)
            print('trendChart', 'id="trendChart"' in html)
            print('income_vs_expense', 'id="chart_income_vs_expense"' in html)
            print('category_pie', 'id="chart_category_pie"' in html)
            print('source_pie', 'id="chart_source_pie"' in html)
            print('chart script', 'chart.umd.min.js' in html or 'cdnjs.cloudflare.com' in html)
            if 'const trend =' in html:
                idx = html.index('const trend =')
                print('trend snippet', html[idx:idx+200].replace('\n', ' '))
            if 'const chartsData =' in html:
                idx = html.index('const chartsData =')
                print('chartsData snippet', html[idx:idx+200].replace('\n', ' '))
