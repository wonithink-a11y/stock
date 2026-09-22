"""텔레그램 공개 채널 소식 — 웹 미리보기(`https://t.me/s/<채널>`)를 읽어 `state/channels.json` 에 쌓는다.

★ **개인 열람 전용**(2026-09-22 사용자 요청). 매경 글은 "무단 복제·배포 금지"이고 저장소는 공개라, 이 데이터는 VM 의
  상태 폴더에만 두고 로그인 뒤 웹 화면에서만 보인다. 저장소·공개 대시보드에 올리지 않는다.
★ 로그인·키가 필요 없다(공개 웹 페이지). 채널 주인이 미리보기를 끄면(비트캐쳐) 이 방식으로는 못 읽는다.
★ 텔레그램이 페이지 형식을 바꾸면 글이 0건으로 읽힌다 — 모든 채널이 0건/실패면 종료코드 1(유닛 실패 알림).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
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
    for ch, e in errors.items():
        print(f"[{ch}] {e}")
    print(f"채널 소식 {len(new)}건 읽음 · 보관 {len(out['posts'])}건 · 실패 {len(errors)}/{len(CHANNELS)}")
    return 1 if len(errors) == len(CHANNELS) else 0
