import os, sys, re
sys.path.insert(0, os.getcwd())
from app import create_app

app = create_app()
with app.test_client() as client:
    resp = client.get('/auth/login')
    html = resp.data.decode('utf-8', errors='replace')
    print('status', resp.status_code)
    print('csrf hidden', 'name="csrf_token"' in html)
    m = re.search(r'<input[^>]+name="csrf_token"[^>]+value="([^"]+)"', html)
    print('token found', bool(m))
    if m:
        print('token', m.group(1))
    print('login title present', 'Welcome back' in html)
    print(html[:800].replace('\n', ' '))
