import urllib.request

urls = [
    'http://127.0.0.1:5000/dashboard',
    'http://127.0.0.1:5000/reports?type=summary&period=monthly',
    'http://127.0.0.1:5000/reports?type=expense&period=monthly',
    'http://127.0.0.1:5000/reports?type=income&period=monthly',
]
for url in urls:
    print('\n=== URL:', url)
    try:
        r = urllib.request.urlopen(url, timeout=10)
        html = r.read().decode('utf-8', errors='replace')
        print('status', r.status)
        print('title', html.split('<title>', 1)[1].split('</title>', 1)[0] if '<title>' in html else 'missing')
        print('body snippet', html[html.find('<body'):html.find('<body')+500] if '<body' in html else 'missing')
        print('trendCanvas', 'id="trendChart"' in html)
        print('chartIncome', 'id="chart_income_vs_expense"' in html)
        print('chartSourcePie', 'id="chart_source_pie"' in html)
        print('chartScript', 'chart.umd.min.js' in html or 'cdnjs.cloudflare.com' in html)
        print('contains login', 'login' in html.lower() or 'password' in html.lower())
    except Exception as e:
        print('ERROR', e)
