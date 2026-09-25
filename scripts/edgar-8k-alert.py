#!/usr/bin/env python3
"""
SEC EDGAR 8-K 공시 → 텔레그램 1:1 방 (관심종목 US 만, 중요 항목만).

미국 종목 뉴스는 네이버 한국어 검색이 안 맞아서(본문 언급뿐, 2026-09-25 실측) 공시로 대신한다.
EDGAR '최신 공시' atom 피드 한 개가 전체 기업의 새 8-K 를 준다 - 종목별 호출이 없다.
방향을 키워드로 추측하지 않고 8-K 항목 번호로 거른다.

  VM: deploy/edgar-8k-alert.{service,timer} (15분). 상태 = EDGAR_STATE_DIR (본 공시 원장·티커맵 캐시)
  env: SEC_USER_AGENT (SEC 가 연락처를 요구한다 - 저장소가 공개라 코드에 안 쓴다, VM .env)
       TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID
  python3 scripts/edgar-8k-alert.py            # 실행
  python3 scripts/edgar-8k-alert.py --dry-run  # 보내지 않고 출력만, 원장도 안 쓴다

과거 공시·재무는 EDGAR 가 영구 보관하므로(submissions·companyfacts API) 여기서 쌓지 않는다.
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=100&start={}&output=atom'
TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
NS = {'a': 'http://www.w3.org/2005/Atom'}
SEEN_TTL_DAYS = 7
MAX_PAGES = 5  # 15분에 500건을 넘는 8-K 는 없다(평일 하루 300~500건)

# 알릴 항목. 2.02(실적)는 시즌에 수백 건이라 뺀다. 9.01(첨부)·7.01/8.01(기타)도 뺀다.
ALERT_ITEMS = {
    '1.01': '중요 계약 체결',
    '1.02': '중요 계약 해지',
    '1.03': '파산·회생',
    '2.01': '인수·매각 완료',
    '2.05': '구조조정 비용',
    '2.06': '자산 손상',
    '3.01': '상장폐지·상장요건 미달 통지',
    '4.01': '감사인 교체',
    '4.02': '과거 재무제표 신뢰 불가',
    '5.02': '임원·이사 변동',
}
RED = {'1.03', '3.01', '4.01', '4.02', '2.06'}


def parse_feed(xml_text):
    """atom → [{acc, cik, items[], updated, link}]"""
    out = []
    for e in ET.fromstring(xml_text).findall('a:entry', NS):
        title = e.findtext('a:title', '', NS)
        m = re.search(r'\((\d{10})\)', title)
        acc = re.search(r'accession-number=([\d-]+)', e.findtext('a:id', '', NS))
        if not m or not acc:
            continue
        summary = html.unescape(e.findtext('a:summary', '', NS))
        out.append({
            'acc': acc.group(1),
            'cik': int(m.group(1)),
            'items': re.findall(r'Item (\d\.\d\d)', summary),
            'updated': e.findtext('a:updated', '', NS),
            'link': e.find('a:link', NS).get('href'),
        })
    return out


def pick_alerts(entries, watch_by_cik, seen):
    """관심종목 + 알릴 항목 + 처음 보는 공시만."""
    alerts = []
    for x in entries:
        if x['acc'] in seen or x['cik'] not in watch_by_cik:
            continue
        hit = [i for i in x['items'] if i in ALERT_ITEMS]
        if hit:
            alerts.append({**x, 'watch': watch_by_cik[x['cik']], 'hit': hit})
    return alerts


def format_alert(a):
    code, name = a['watch']
    icon = '🔴' if RED & set(a['hit']) else '🟡'
    what = ' · '.join(f"{i} {ALERT_ITEMS[i]}" for i in a['hit'])
    return f"{icon} {name}({code}) {what}\n{a['updated'][:16].replace('T', ' ')} ET\n{a['link']}"


def get(url, ua):
    req = urllib.request.Request(url, headers={'User-Agent': ua, 'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8')


def watch_map(state_dir, ua):
    """관심종목 US 티커 → CIK. SEC 티커맵은 하루 1번만 받는다(~1MB)."""
    cache = state_dir / 'company_tickers.json'
    if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
        cache.write_text(get(TICKERS_URL, ua), encoding='utf-8')
    cik_by_ticker = {v['ticker']: v['cik_str'] for v in json.loads(cache.read_text(encoding='utf-8')).values()}
    wl = json.loads((ROOT / 'config' / 'watchlist.json').read_text(encoding='utf-8'))['tickers']
    us = [t for t in wl if t.get('market') == 'US']
    out = {cik_by_ticker[t['code']]: (t['code'], t['name']) for t in us if t['code'] in cik_by_ticker}
    missing = [t['code'] for t in us if t['code'] not in cik_by_ticker]
    if missing:
        print(f'  [안내] SEC 티커맵에 없는 종목 {len(missing)}개: {missing[:10]}')
    return out


def send_telegram(text):
    token, chat = os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        return False
    body = urllib.parse.urlencode({'chat_id': chat, 'text': text, 'disable_web_page_preview': 'true'}).encode()
    with urllib.request.urlopen(f'https://api.telegram.org/bot{token}/sendMessage', body, timeout=30) as r:
        return r.status == 200


def main():
    dry = '--dry-run' in sys.argv
    ua = os.environ.get('SEC_USER_AGENT')
    if not ua:
        sys.exit('❌ SEC_USER_AGENT 가 없습니다(SEC 는 연락처 없는 요청을 막는다).')
    state_dir = Path(os.environ.get('EDGAR_STATE_DIR', Path.home() / '.edgar-state'))
    state_dir.mkdir(parents=True, exist_ok=True)
    seen_path = state_dir / 'seen.json'
    seen = json.loads(seen_path.read_text(encoding='utf-8')) if seen_path.exists() else {}
    cut = time.time() - SEEN_TTL_DAYS * 86400
    seen = {k: t for k, t in seen.items() if t >= cut}

    watch = watch_map(state_dir, ua)
    entries = []
    for page in range(MAX_PAGES):  # 이미 본 공시가 나올 때까지 넘긴다 - 한 번에 100건 넘게 몰려도 안 빠지게
        batch = parse_feed(get(FEED.format(page * 100), ua))
        entries += batch
        if not batch or any(x['acc'] in seen for x in batch) or not seen:
            break
        time.sleep(0.2)
    alerts = pick_alerts(entries, watch, seen)
    print(f'관심 US {len(watch)}종목 · 피드 {len(entries)}건 · 알림 {len(alerts)}건')

    if alerts:
        text = f'🇺🇸 미국 관심종목 8-K 공시 {len(alerts)}건\n\n' + '\n\n'.join(format_alert(a) for a in alerts[:30])
        print(text)
        if dry:
            return
        if not send_telegram(text):
            sys.exit('❌ 텔레그램 전송 실패 - 원장을 안 쓴다(다음 실행에 다시 뜬다)')
    if dry:
        return
    now = time.time()
    for x in entries:
        seen.setdefault(x['acc'], now)
    seen_path.write_text(json.dumps(seen), encoding='utf-8')


if __name__ == '__main__':
    main()
