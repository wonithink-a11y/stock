#!/usr/bin/env python3
"""장 마감 리포트 → 카카오톡 '나에게 보내기'. VM 타이머(deploy/kakao-report.{service,timer})가 10분마다 부른다.

  python3 scripts/send-kakao-report.py              새 리포트가 있으면 보낸다(없으면 조용히 끝)
  python3 scripts/send-kakao-report.py --login      최초 1회(또는 토큰 만료 뒤) 카카오 로그인 — 사람이 직접 친다
  python3 scripts/send-kakao-report.py 2026-10-13-kr   그 리포트를 다시 보낸다(보낸 기록 무시)

왜 VM 인가: 카카오 갱신 토큰은 약 2개월이고 만료 1개월 전부터 갱신할 때 새 토큰이 나온다 — 그 새 값을
어딘가 써 둬야 한다. Actions 는 시크릿을 스스로 못 고치고(저장소는 공개), VM 은 상태 파일에 쓰면 된다.
리포트는 git 이 아니라 raw.githubusercontent.com 에서 읽는다 — collector-pull(06:30, 장중 pull 금지)과 안 엮이게.

env(~/collector-venv/.env): KAKAO_REST_API_KEY · KAKAO_CLIENT_SECRET(앱에서 켰을 때만) · KAKAO_REDIRECT_URI(기본 http://localhost:8765)
상태: KAKAO_STATE_DIR(기본 ~/collector-venv/kakao) — token.json(600) · sent.json(보낸 리포트 이름)
텍스트 템플릿 본문은 200자 상한 → 지수·한 줄 요약만, 전체는 '전체 보기' 버튼(대시보드 #mreport=)으로.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RAW = "https://raw.githubusercontent.com/wonithink-a11y/stock/main/reports/market-daily/"
DASH = "https://wonithink-a11y.github.io/stock/"
KST = dt.timezone(dt.timedelta(hours=9))
STATE = os.path.expanduser(os.environ.get("KAKAO_STATE_DIR", "~/collector-venv/kakao"))
REDIRECT = os.environ.get("KAKAO_REDIRECT_URI", "http://localhost:8765")


def _p(v):
    return "−" if v is None else f"{v:+.2f}%".replace("-", "−")


def build_text(stem, facts, summary):
    day, mkt = stem[:10], stem[11:]
    wd = "월화수목금토일"[dt.date.fromisoformat(day).weekday()]
    L = [f"{'📊 한국장' if mkt == 'kr' else '🌎 미국장'} 마감 {day[5:]}({wd})"]
    L += [f"{r['name']} {r['close']:,.2f} {_p(r['chgPct'])}" for r in facts.get("series", [])
          if r.get("group") == "지수" and "close" in r]
    if (summary or {}).get("headline"):
        L += ["", summary["headline"]]
    text = "\n".join(L)
    return text if len(text) <= 200 else text[:199] + "…"


def candidates(now):
    d, y = now.date().isoformat(), (now.date() - dt.timedelta(days=1)).isoformat()
    return [f"{d}-kr", f"{y}-kr", f"{y}-us"]  # us 파일 날짜 = 미국 날짜 = 한국 아침 기준 어제


def fetch_json(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # 아직 안 올라옴 — 정상
        raise


def post(url, data, token=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {url}: {e.read().decode(errors='replace')[:300]}") from None


def load(name, default):
    try:
        with open(os.path.join(STATE, name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(name, obj):
    os.makedirs(STATE, mode=0o700, exist_ok=True)
    path = os.path.join(STATE, name)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def token_request(extra):
    data = {"client_id": os.environ["KAKAO_REST_API_KEY"], **extra}
    if os.environ.get("KAKAO_CLIENT_SECRET"):
        data["client_secret"] = os.environ["KAKAO_CLIENT_SECRET"]
    return post("https://kauth.kakao.com/oauth/token", data)


def store_tokens(r, tok):
    now = time.time()
    tok["access_token"], tok["access_expires_at"] = r["access_token"], now + r["expires_in"]
    if r.get("refresh_token"):  # 갱신 때는 만료 1개월 전부터만 새로 온다
        tok["refresh_token"], tok["refresh_expires_at"] = r["refresh_token"], now + r["refresh_token_expires_in"]
    tok.pop("broken", None)
    save("token.json", tok)
    return tok


def access_token():
    tok = load("token.json", None)
    if not tok:
        raise SystemExit("token.json 없음 — 먼저 --login")
    if tok.get("access_expires_at", 0) - time.time() > 600:
        return tok["access_token"]
    try:
        return store_tokens(token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}), tok)["access_token"]
    except RuntimeError as e:
        # 갱신 토큰 만료·철회: 장애 방 알림은 한 번만(10분마다 실패하면 알림 폭탄). 다시 --login 하면 풀린다.
        if tok.get("broken"):
            print(f"토큰 갱신 실패(이미 알림) — --login 필요: {e}")
            sys.exit(0)
        tok["broken"] = True
        save("token.json", tok)
        raise SystemExit(f"토큰 갱신 실패 — VM 에서 --login 다시: {e}")


def send(token, stem, text):
    url = f"{DASH}#mreport={stem}"
    tpl = {"object_type": "text", "text": text, "link": {"web_url": url, "mobile_web_url": url}, "button_title": "전체 보기"}
    r = post("https://kapi.kakao.com/v2/api/talk/memo/default/send",
             {"template_object": json.dumps(tpl, ensure_ascii=False)}, token)
    if r.get("result_code") != 0:
        raise RuntimeError(f"카카오 전송 실패 {stem}: {r}")


def login():
    # 사람이 셸에서 바로 치는 경로 — systemd 처럼 EnvironmentFile 을 안 읽으므로 KAKAO_* 줄만 직접 읽는다.
    # PC(브라우저 있는 곳)에서 setup-keys.bat 로 넣은 저장소 .env 도 본다 → 만든 token.json 은 VM 으로 복사.
    for env in (os.path.expanduser("~/collector-venv/.env"), os.path.join(os.path.dirname(__file__), "..", ".env")):
        if not os.path.exists(env):
            continue
        with open(env, encoding="utf-8") as f:
            for line in f:
                if line.startswith("KAKAO_") and "=" in line:
                    key, val = line.strip().split("=", 1)
                    os.environ.setdefault(key, val.strip("'\""))
    q =urllib.parse.urlencode({"response_type": "code", "client_id": os.environ["KAKAO_REST_API_KEY"],
                                "redirect_uri": REDIRECT, "scope": "talk_message"})
    print("1) PC 브라우저에서 이 주소를 열고 카카오 로그인·동의:\n\n   https://kauth.kakao.com/oauth/authorize?" + q)
    print("\n2) '사이트에 연결할 수 없음'이 떠도 정상이다. 주소창 전체를 복사해 아래에 붙여 넣는다.")
    got = input("\n주소: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(got).query).get("code", [got])[0]
    store_tokens(token_request({"grant_type": "authorization_code", "redirect_uri": REDIRECT, "code": code}), {})
    print("저장 완료:", os.path.join(STATE, "token.json"))


def main(args):
    if args[:1] == ["--login"]:
        return login()
    sent = load("sent.json", [])
    stems = args or [s for s in candidates(dt.datetime.now(KST)) if s not in sent]
    todo = []
    for s in stems:
        facts = fetch_json(RAW + s + ".facts.json")
        if facts:
            todo.append((s, build_text(s, facts, fetch_json(RAW + s + ".summary.json"))))
    if not todo:
        return
    token = access_token()
    for s, text in todo:
        send(token, s, text)
        print("보냄", s)
        sent = (sent + [s])[-60:]
        save("sent.json", sent)


if __name__ == "__main__":
    main(sys.argv[1:])
