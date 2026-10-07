"""텔레그램 공개 채널 소식 — 웹 미리보기(`https://t.me/s/<채널>`)를 읽어 `state/channels.json` 에 쌓는다.

★ **개인 열람 전용**(2026-09-22 사용자 요청). 매경 글은 "무단 복제·배포 금지"이고 저장소는 공개라, 이 데이터는 VM 의
  상태 폴더에만 두고 로그인 뒤 웹 화면에서만 보인다. 저장소·공개 대시보드에 올리지 않는다.
★ 로그인·키가 필요 없다(공개 웹 페이지). 채널 주인이 미리보기를 끄면(비트캐쳐) 이 방식으로는 못 읽는다.
★ 텔레그램이 페이지 형식을 바꾸면 글이 0건으로 읽힌다 — 모든 채널이 0건/실패면 종료코드 1(유닛 실패 알림).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, List, Optional

CHANNELS: Dict[str, str] = {                            # 아이디 -> 화면 이름(2026-09-22 사용자 지정 매경 3개)
    "mk_giant": "매경 자이앤트",
    "wcforumxyz": "매경 크립토",
    "mkglobalinvest": "매경 월가월부",
}
KEEP = 400                                              # 전체 보관 글 수(오래된 것부터 버린다)
MAX_TEXT = 3000


class _Parser(HTMLParser):
    """글마다 {id, at, text}. 본문 div 안의 <br> 은 줄바꿈, 나머지 태그는 글자만 남긴다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts: List[dict] = []
        self._cur: Optional[dict] = None
        self._depth = -1                                # 본문 div 안이면 0 이상(안쪽 div 깊이)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "div" and a.get("data-post") and "tgme_widget_message " in cls + " ":
            self._cur = {"id": a["data-post"], "at": "", "text": ""}
            self.posts.append(self._cur)
            return
        if self._cur is None:
            return
        if self._depth >= 0:
            if tag == "br":
                self._cur["text"] += "\n"
            elif tag == "div":
                self._depth += 1
            return
        if tag == "div" and "tgme_widget_message_text" in cls:
            self._depth = 0
        elif tag == "time" and a.get("datetime") and not self._cur["at"]:
            self._cur["at"] = a["datetime"]

    def handle_endtag(self, tag):
        if self._depth >= 0 and tag == "div":
            self._depth -= 1

    def handle_data(self, data):
        if self._cur is not None and self._depth >= 0:
            self._cur["text"] += data


def parse(html: str) -> List[dict]:
    p = _Parser()
    p.feed(html)
    out = []
    for x in p.posts:
        if "/" not in x["id"] or not x["at"]:
            continue
        text = x["text"].strip()[:MAX_TEXT]
        out.append({"id": x["id"], "channel": x["id"].split("/")[0], "at": x["at"], "text": text})
    return out


# ── 증권사 목표가 변동 — 자이앤트 '당일 발간리포트' 요약·특징주 글에서 숫자 필드만 뽑아 tp-history.jsonl 에 영구 누적 ──
# ★ 개인 열람 전용(위와 같음). 글의 서술 문장은 저장하지 않는다 — 종목명·일자·증권사·의견·목표가·변동 구분만.
# ★ 그날 리포트가 나오고 채널이 올린 종목만 잡힌다(전 종목 컨센서스 아님). 점수·추천에 쓰지 않는다(절대 규칙 1).
_KST = timezone(timedelta(hours=9))
_ROW = re.compile(r"^\s*(\S+)\s*/\s*([A-Za-z가-힣]+)(?:\(([^)]*)\))?\s*/\s*([\d,]+)원\(([^)]*)\)", re.M)
_NUM = lambda x: int(x.replace(",", ""))


def _name(first: str) -> str:
    """'✅️ 제이앤티씨 : +15.2% 상승 중' -> '제이앤티씨'"""
    return re.sub(r"^[^\w가-힣]+", "", first.split(" : ")[0]).strip()


def extract_tp(posts: List[dict]) -> List[dict]:
    """매경 자이앤트 글 -> 목표가 기록. daily = 증권사별 한 줄, month = 특징주 글의 '최근 1개월 발간리포트' 요약."""
    out = []
    for p in posts:
        if p.get("channel") != "mk_giant":
            continue
        t, at = p["text"], p["at"]
        try:
            day = datetime.fromisoformat(at).astimezone(_KST).date().isoformat()
        except ValueError:
            continue
        name = _name(t.split("\n")[0])
        if "당일 발간리포트" in t:
            for m in _ROW.finditer(t):
                out.append({"k": f"{p['id']}|{m.group(1)}", "kind": "daily", "pid": p["id"], "day": day, "name": name, "broker": m.group(1),
                            "opinion": m.group(2), "opinionChg": m.group(3) or "", "tp": _NUM(m.group(4)), "tpChg": m.group(5)})
        elif "최근 1개월 발간리포트" in t:
            n = re.search(r"최근 1개월 발간리포트\s*-\s*(\d+)건", t)
            tp = re.search(r"목표가(?: 평균)?\s*:\s*([\d,]+)원", t)
            up = re.search(r"업사이드\s*:\s*([+-]?[\d.]+)%", t)
            px = re.search(r"현재주가\s*:\s*([\d,]+)원", t)
            if n and tp:
                out.append({"k": p["id"], "kind": "month", "pid": p["id"], "day": day, "name": name, "n": int(n.group(1)), "tp": _NUM(tp.group(1)),
                            "upside": float(up.group(1)) if up else None, "price": _NUM(px.group(1)) if px else None})
    return out


def append_tp(path: Path, posts: List[dict]) -> int:
    """새 기록만 덧붙인다(k 로 중복 제거). 채널 글은 400건이 넘으면 버려지지만 이 파일은 버리지 않는다."""
    seen = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            seen.add(json.loads(line)["k"])
    except (OSError, ValueError, KeyError):
        pass
    rows = [r for r in extract_tp(posts) if r["k"] not in seen]
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return len(rows)


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def merge(old: List[dict], new: List[dict], keep: int = KEEP) -> List[dict]:
    by = {p["id"]: p for p in old}
    by.update({p["id"]: p for p in new})                # 같은 글은 새로 읽은 것으로(수정된 글 반영)
    return sorted(by.values(), key=lambda p: p["at"], reverse=True)[:keep]


def fetch_all(path: Path, now: datetime, get: Callable[[str], str] = _get) -> int:
    """모든 채널을 읽어 합친다. 종료코드: 0 = 하나라도 읽음, 1 = 전부 실패(형식 변경·네트워크)."""
    try:
        cur = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = {"posts": []}
    new, errors = [], {}
    for ch in CHANNELS:
        try:
            got = parse(get(f"https://t.me/s/{ch}"))
            if not got:
                raise ValueError("글 0건 — 미리보기가 꺼졌거나 페이지 형식이 바뀌었다")
            new += got
        except Exception as e:                          # noqa: BLE001 — 한 채널 실패가 나머지를 막지 않는다
            errors[ch] = f"{type(e).__name__}: {e}"[:200]
    out = {"updatedAt": now.isoformat(), "errors": errors, "posts": merge(cur.get("posts") or [], new)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    added = append_tp(path.parent / "tp-history.jsonl", new)
    for ch, e in errors.items():
        print(f"[{ch}] {e}")
    print(f"채널 소식 {len(new)}건 읽음 · 보관 {len(out['posts'])}건 · 목표가 기록 +{added} · 실패 {len(errors)}/{len(CHANNELS)}")
    return 1 if len(errors) == len(CHANNELS) else 0
