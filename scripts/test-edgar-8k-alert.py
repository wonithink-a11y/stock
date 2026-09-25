"""edgar-8k-alert.py 회귀 - 피드 파싱·거르기 (네트워크 없음)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('e8k', Path(__file__).parent / 'edgar-8k-alert.py')
e8k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e8k)

FEED = '''<?xml version="1.0" encoding="ISO-8859-1" ?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>8-K - ABBVIE INC. (0001551152) (Filer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/x-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-09-25 &lt;br&gt;Item 5.02: Departure of Directors
&lt;br&gt;Item 9.01: Financial Statements and Exhibits</summary>
<updated>2026-09-25T10:00:17-04:00</updated>
<id>urn:tag:sec.gov,2008:accession-number=0001213900-26-103299</id></entry>
<entry><title>8-K - APPLE INC (0000320193) (Filer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/y-index.htm"/>
<summary type="html">&lt;br&gt;Item 2.02: Results &lt;br&gt;Item 9.01: Exhibits</summary>
<updated>2026-09-25T16:30:00-04:00</updated>
<id>urn:tag:sec.gov,2008:accession-number=0000320193-26-000001</id></entry>
</feed>'''

entries = e8k.parse_feed(FEED)
assert [(x['cik'], x['items']) for x in entries] == [(1551152, ['5.02', '9.01']), (320193, ['2.02', '9.01'])], entries
watch = {1551152: ('ABBV', '애브비'), 320193: ('AAPL', '애플')}
alerts = e8k.pick_alerts(entries, watch, seen={})
assert [a['watch'][0] for a in alerts] == ['ABBV'], '실적(2.02)만 있는 공시는 안 알린다'
assert alerts[0]['hit'] == ['5.02']
assert e8k.pick_alerts(entries, watch, seen={'0001213900-26-103299': 1}) == [], '본 공시는 다시 안 알린다'
assert e8k.pick_alerts(entries, {}, seen={}) == [], '관심종목이 아니면 안 알린다'
msg = e8k.format_alert(alerts[0])
assert '애브비(ABBV)' in msg and '5.02 임원·이사 변동' in msg and msg.startswith('🟡'), msg
print('test-edgar-8k-alert: 통과')
