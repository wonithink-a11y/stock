#!/usr/bin/env python3
"""자주 보는 유튜브 채널의 새 영상을 Gemini 로 자세히 요약 → VM 상태 파일 + 텔레그램 1:1 방 (2026-10-24 사용자 요청).

  python3 scripts/yt-digest.py              # 새 영상 찾아 요약·발송 (타이머가 20분마다)
  python3 scripts/yt-digest.py --test ID    # 영상 하나만 요약해 출력 (저장·발송 없음, 토큰 실측용)
  python3 scripts/yt-digest.py --selftest

채널 RSS(키 없음)로 새 영상을 찾고, 영상 URL 을 Gemini 에 그대로 넣는다(공개 영상만). 라이브 중인 영상은 끝난 뒤에 받는다.
결과는 $YT_DIR/digest.json(기본 ~/collector-venv/yt) — VM /yt 가 키(X-Pin-Key)를 확인하고 내준다.
★ 남의 콘텐츠 요약이라 **저장소·공개 대시보드에 올리지 않는다**(channels-feed 와 같은 규칙). 관찰용 맥락 — 점수·매매 불사용(절대 규칙 1).
env: GEMINI_API_KEY · TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID(선택 — 없으면 발송 생략).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
STATE = Path(os.environ.get("YT_DIR") or Path.home() / "collector-venv" / "yt")
MODEL = os.environ.get("YT_MODEL", "gemini-3.5-flash")   # 10-24 시험: 90분 방송에서 Flash 가 Flash-Lite 보다 상세·정확(대선/중간선거 혼동 없음), 68초 vs 113초
FALLBACK = "gemini-3.5-flash-lite"                         # Flash 무료 하루 20건 한도(429) 때만. 하루 8건 안팎이라 평소엔 안 쓴다
MAX_AGE_H = 48       # 첫 실행에 옛 영상을 쏟아붓지 않는다
MAX_PER_RUN = 4      # 한 번에 요약하는 상한(토큰·한도 보호) — 나머지는 다음 실행
MAX_TRIES = 6        # 라이브 중·한도·일시 오류 재시도 상한
KEEP = 300           # digest.json 에 남기는 건수

# only: 제목이 이 패턴일 때만(오선은 라이브 본편이 아니라 '오늘의 요약' 영상만)
CHANNELS = [
    {"id": "UC_JJ_NhRqPKcIOj5Ko3W_3w", "name": "오선의 미국 증시", "only": r"^【미국 증시 오늘의 요약】"},
    {"id": "UCPTy0BNqiv-0SdAvFgrXvXg", "name": "매경 라이브"},
    {"id": "UCC3yfxS5qC6PCwDzetUuEWg", "name": "소수몽키"},
    {"id": "UCIipmgxpUxDmPP-ma3Ahvbw", "name": "매경 월가월부"},
]

PROMPT = """이 영상은 한국어 투자·시장 방송이다. 시청하지 못한 사람이 영상을 보지 않아도 내용을 알 수 있게 **자세히** 정리하라.

규칙:
- 영상에서 실제로 말한 내용만 쓴다. 없는 내용을 보태거나 네 의견·예측·추천을 섞지 않는다.
- 숫자(지수·가격·금리·실적·날짜)는 말한 그대로 적는다. 들리지 않았거나 확실하지 않으면 적지 말고 caveats 에 '불분명'으로 남긴다.
- 화자의 주장(전망·의견)과 확인된 사실(발표·실적·시세)을 구분해서 쓴다.
- 광고·인사·구독 안내·잡담은 뺀다.
- brief 는 바쁜 사람이 이것만 읽어도 되는 핵심 10줄 이내. 한 줄에 한 문장, 가장 중요한 것부터, 숫자는 말한 그대로. sections 와 겹쳐도 된다.
- mentioned 는 종목·섹터·자산(원자재·환율·채권 등)만 쓴다. 사람·기관 이름은 넣지 말고 sections 안에 '누가 무엇을 말했다'로 쓴다. 해당이 없으면 빈 배열.
- numbers 는 '무엇의 수치인지'를 붙여 쓴다(예: 'S&P500 −0.52%'). 날짜·단순 개수는 빼고, 없으면 빈 배열.
- caveats 는 화자가 밝힌 위험·전제·불확실성, 또는 잘 안 들린 부분만. 없으면 빈 배열.
- sections 는 영상 흐름 순서로 주제별로 나눈다. 10분 이하는 3~6개, 길면 영상 길이에 비례해 늘려 최대 15개. 각 points 는 구체적인 문장으로 충분히 길게 쓰고, 출연자별로 누가 무엇을 말했는지 구분한다(한 줄 요약 금지).
- 한국어로 쓴다."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "brief": {"type": "ARRAY", "items": {"type": "STRING"}},
        "summary": {"type": "STRING"},
        "sections": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"title": {"type": "STRING"}, "points": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "required": ["title", "points"],
        }},
        "mentioned": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}, "view": {"type": "STRING"}},
            "required": ["name", "view"],
        }},
        "numbers": {"type": "ARRAY", "items": {"type": "STRING"}},
        "caveats": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["headline", "brief", "summary", "sections"],
}

NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def load_env():
    env = dict(os.environ)
    for p in (Path.home() / "collector-venv" / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


def http(req, timeout=60, tries=3):
    for attempt in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code not in (500, 502, 503, 504) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == tries - 1:
                raise
        time.sleep(10 * (attempt + 1))


def parse_feed(xml_bytes):
    """RSS → [{id, title, published(datetime), url}] 최신순. 쇼츠는 뺀다."""
    out = []
    for e in ET.fromstring(xml_bytes).findall("a:entry", NS):
        link = (e.find("a:link", NS).get("href") or "")
        if "/shorts/" in link:
            continue
        out.append({"id": e.find("yt:videoId", NS).text, "title": e.find("a:title", NS).text or "",
                    "published": datetime.fromisoformat(e.find("a:published", NS).text), "url": link})
    return sorted(out, key=lambda v: v["published"], reverse=True)


def wanted(ch, v, now):
    if ch.get("only") and not re.search(ch["only"], v["title"]):
        return False
    return now - v["published"] <= timedelta(hours=MAX_AGE_H)


def is_live_now(vid):
    """진행 중인 라이브면 True. 페이지를 못 읽으면 False(요약 시도 → 실패하면 재시도 횟수만 쓴다)."""
    try:
        h = http(urllib.request.Request(f"https://www.youtube.com/watch?v={vid}", headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko"}), 30, 2).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return False
    return '"isLiveNow":true' in h


def summarize(vid, key, model=MODEL):
    body = {"contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={vid}"}}, {"text": PROMPT}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json", "responseSchema": SCHEMA,
                                 "mediaResolution": "MEDIA_RESOLUTION_LOW"}}   # 말이 중심이라 화면 해상도는 낮춰 토큰을 아낀다
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    d = json.loads(http(req, 600, 2))
    return json.loads(d["candidates"][0]["content"]["parts"][0]["text"]), d.get("usageMetadata", {})


def render(item):
    """텔레그램·로그용 글. 대시보드는 JSON 을 직접 그린다."""
    s = item["digest"]
    L = [f"🎬 {item['channel']} | {item['published'][:16].replace('T', ' ')}", item["title"], item["url"], "", s["headline"], "", s["summary"]]
    for sec in s.get("sections", []):
        L += ["", f"■ {sec['title']}"] + [f"· {p}" for p in sec["points"]]
    if s.get("mentioned"):
        L += ["", "언급 종목·자산"] + [f"· {m['name']}: {m['view']}" for m in s["mentioned"]]
    if s.get("numbers"):
        L += ["", "나온 숫자"] + [f"· {n}" for n in s["numbers"]]
    if s.get("caveats"):
        L += ["", "유의"] + [f"· {c}" for c in s["caveats"]]
    return "\n".join(L)


DASH = "https://wonithink-a11y.github.io/stock/"


def pin_key():
    """대시보드 키(VM /pins·/yt 가 검사). 링크에 실어 보내면 어느 브라우저로 열어도 그 기기에 저장된다(텔레그램 앱 내 브라우저는 저장소가 따로라서)."""
    try:
        return (Path.home() / "collector-venv" / "pins" / "key").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def render_short(item, key=""):
    """텔레그램용: 핵심 10줄 + 전문 링크(대시보드 '영상 요약'). 전문은 길어서 텔레그램에 보내지 않는다."""
    s = item["digest"]
    lines = (s.get("brief") or [])[:10] or [s["headline"]]   # brief 없는 옛 항목은 헤드라인만
    return "\n".join([f"🎬 {item['channel']} | {item['published'][:16].replace('T', ' ')}", item["title"], "",
                      s["headline"], ""] + [f"· {x}" for x in lines] +
                     ["", f"전체 요약 → {DASH}#yt={item['id']}" + (f"&pinkey={key}" if key else ""), f"영상 → {item['url']}"])


def split(text, limit=3900):
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        chunks.append(cur)
    return [c.rstrip("\n") for c in chunks if c.strip()]


def telegram(env, text):
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_VIDEO_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    parts = split(text)
    for i, part in enumerate(parts, 1):
        body = json.dumps({"chat_id": chat, "text": (f"({i}/{len(parts)})\n" if len(parts) > 1 else "") + part,
                           "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, headers={"Content-Type": "application/json"})
        try:
            http(req, 20, 3)
        except Exception as e:  # noqa: BLE001 — 발송 실패가 요약 저장을 막지 않는다
            print(f"  텔레그램 실패: {type(e).__name__}: {e}")
            return False
    return True


def read_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(p, data):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def run(env):
    if not env.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY 가 없다")
    STATE.mkdir(parents=True, exist_ok=True)
    seen = read_json(STATE / "seen.json", {})            # id → {"tries": n} | {"done": true}
    digest = read_json(STATE / "digest.json", {"items": []})
    now = datetime.now(timezone.utc)
    todo = []
    for ch in CHANNELS:
        try:
            feed = parse_feed(http(urllib.request.Request(f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}"), 30))
        except Exception as e:  # noqa: BLE001 — 한 채널 실패가 나머지를 막지 않는다
            print(f"{ch['name']} RSS 실패: {type(e).__name__}: {e}")
            continue
        for v in feed:
            st = seen.get(v["id"], {})
            if st.get("done") or st.get("tries", 0) >= MAX_TRIES or not wanted(ch, v, now):
                continue
            todo.append((ch, v))
    todo.sort(key=lambda t: t[1]["published"])           # 오래된 것부터 — 상한에 걸려도 순서가 안 뒤집힌다
    done_n = 0
    for ch, v in todo[:MAX_PER_RUN]:
        if is_live_now(v["id"]):
            print(f"라이브 중, 건너뜀: {v['title'][:40]}")
            continue
        st = seen.setdefault(v["id"], {"tries": 0})
        model = MODEL
        try:
            try:
                s, usage = summarize(v["id"], env["GEMINI_API_KEY"], model)
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                model = FALLBACK
                s, usage = summarize(v["id"], env["GEMINI_API_KEY"], model)
        except Exception as e:  # noqa: BLE001
            st["tries"] += 1
            body = e.read().decode("utf-8", "replace")[:200] if isinstance(e, urllib.error.HTTPError) else ""
            print(f"요약 실패({st['tries']}/{MAX_TRIES}) {v['id']}: {type(e).__name__} {e} {body}")
            write_json(STATE / "seen.json", seen)
            continue
        item = {"id": v["id"], "channel": ch["name"], "title": v["title"], "url": v["url"],
                "published": v["published"].astimezone(KST).isoformat(timespec="seconds"),
                "digest": s, "model": model, "tokens": usage.get("totalTokenCount"),
                "createdAt": datetime.now(KST).isoformat(timespec="seconds")}
        digest["items"] = ([item] + digest["items"])[:KEEP]
        st["done"] = True
        write_json(STATE / "digest.json", digest)
        write_json(STATE / "seen.json", seen)
        sent = telegram(env, render_short(item, pin_key()))
        print(f"요약 완료 {ch['name']} · {v['title'][:40]} · 토큰 {item['tokens']} · 텔레그램 {'OK' if sent else '생략/실패'}")
        done_n += 1
    print(f"새 영상 후보 {len(todo)}건, 요약 {done_n}건")


def selftest():
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>AAAAAAAAAAA</yt:videoId><title>t1</title><link rel="alternate" href="https://www.youtube.com/watch?v=AAAAAAAAAAA"/><published>2026-10-24T01:00:00+00:00</published></entry>
<entry><yt:videoId>BBBBBBBBBBB</yt:videoId><title>s</title><link rel="alternate" href="https://www.youtube.com/shorts/BBBBBBBBBBB"/><published>2026-10-24T02:00:00+00:00</published></entry></feed>"""
    vs = parse_feed(feed)
    assert [v["id"] for v in vs] == ["AAAAAAAAAAA"]                       # 쇼츠 제외
    now = datetime(2026, 10, 24, 5, tzinfo=timezone.utc)
    os_ch = CHANNELS[0]
    assert wanted(os_ch, {"title": "【미국 증시 오늘의 요약】  유가", "published": now}, now)
    assert not wanted(os_ch, {"title": "[26년 10월 23일 금] 라이브", "published": now}, now)   # 오선 라이브 본편 제외
    assert not wanted(CHANNELS[1], {"title": "x", "published": now - timedelta(hours=49)}, now)  # 48시간 지난 영상
    assert split("a\n" * 3000, 100) and all(len(c) <= 100 for c in split("a\n" * 3000, 100))
    item = {"channel": "c", "published": "2026-10-24T07:00:00+09:00", "title": "t", "url": "u",
            "digest": {"headline": "h", "summary": "s", "sections": [{"title": "T", "points": ["p"]}], "numbers": ["n"]}}
    assert "■ T" in render(item) and "· p" in render(item)
    item.update(id="AAAAAAAAAAA", digest={"headline": "h", "brief": [f"b{i}" for i in range(12)], "summary": "s", "sections": []})
    sh = render_short(item)
    assert "· b9" in sh and "· b10" not in sh and "#yt=AAAAAAAAAAA" in sh and len(sh) < 1000   # 10줄 상한
    assert "· h" in render_short({**item, "digest": {"headline": "h", "summary": "s", "sections": []}})   # brief 없는 옛 항목
    assert "#yt=AAAAAAAAAAA&pinkey=abc" in render_short(item, "abc") and "pinkey" not in render_short(item)
    print("selftest ok (11 assertions)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--test" in sys.argv:
        e = load_env()
        t0 = time.time()
        a = sys.argv[sys.argv.index("--test") + 1:]
        s, u = summarize(a[0], e["GEMINI_API_KEY"], a[1] if len(a) > 1 else MODEL)   # --test ID [모델]
        print(render({"channel": "시험", "published": "", "title": "", "url": "", "digest": s}))
        print(f"\n토큰 {u.get('totalTokenCount')} (입력 {u.get('promptTokenCount')}) · {time.time() - t0:.0f}초")
    else:
        run(load_env())
