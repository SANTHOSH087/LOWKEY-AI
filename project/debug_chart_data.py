import urllib.request

for url in [
    'http://127.0.0.1:5000/dashboard',
    'http://127.0.0.1:5000/reports?type=summary&period=monthly',
    'http://127.0.0.1:5000/reports?type=expense&period=monthly',
    'http://127.0.0.1:5000/reports?type=income&period=monthly',
]:
    print('\n--- URL:', url)
    try:
        r = urllib.request.urlopen(url, timeout=10)
        html = r.read().decode('utf-8', errors='replace')
        print('status', r.status)
        print('trendChart present', 'id="trendChart"' in html)
        print('summary chart present', 'id="chart_income_vs_expense"' in html)
        print('expense chart present', 'id="chart_category_pie"' in html)
        print('income chart present', 'id="chart_source_pie"' in html)
        print('chart script present', 'chart.umd.min.js' in html)
        if 'const trend =' in html:
            idx = html.index('const trend =')
            print('trend snippet:', html[idx:idx+260].replace('\n',' '))
        if 'const chartsData =' in html:
            idx = html.index('const chartsData =')
            print('chartsData snippet:', html[idx:idx+260].replace('\n',' '))
    except Exception as e:
        print('ERROR', e)
