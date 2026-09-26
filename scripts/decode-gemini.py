#!/usr/bin/env python3
"""decode-gemini.py — 공시 원문으로 기업 해독 서술 칸을 Gemini 가 쓰고, 코드가 검사한다(시범, 2026-09-26).

  python scripts/decode-gemini.py --ticker 005930 --name 삼성전자 --rcept 20260814003699 --out docs/cards/005930-gemini-pilot-2026-09.md
  python scripts/decode-gemini.py --selftest        (네트워크 없음)

흐름: DART document.xml(보고서 원문) → 'II. 사업의 내용'만 자름 → Gemini(JSON 스키마, 항목마다 원문 인용)
      → 검사: ① 인용이 원문에 그대로 있다(공백 무시) ② 주장 속 숫자가 전부 인용 안에 있다 → 통과만 본문, 탈락은 부록.
★ 숫자 재무(현금흐름·운전자본)는 LLM 에 맡기지 않는다 — DART 재무 API 로 코드가 채울 칸이다(이 시범 범위 밖).
★ 관찰용 맥락 자료다. 점수·매매 규칙에 쓰지 않는다(절대 규칙 1). 키: .env 의 DART_API_KEY · GEMINI_API_KEY.
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 2026-09-26 실측(삼성전자 반기보고서, 같은 지시문): 3.5-flash 첫 시도 응답·인용 통과 24/25 로 가장 안정.
# 3.6·3.7-flash 는 503 연속, 3.8-flash 통과 11/17, 2.5-flash 22/32. Pro 계열은 무료 한도 0(결제 필요), 2.5-pro 는 신규 사용자 차단.
MODEL = "gemini-3.5-flash"     # --model 로 바꾼다
MAX_CHARS = 180_000     # 사업의 내용만이면 대형주도 이 안이다(넘으면 자르고 표시)

SECTIONS = {
    "A_사업구조": "무엇으로 돈을 버는가 — 부문별 매출·이익 비중, 주력 제품, 가격 변화",
    "A_고객": "주요 매출처와 집중도",
    "A_시장지위": "시장 점유율·경쟁 구도(공시에 있는 것만)",
    "A_원재료": "주요 원재료·공급처·가격 변화",
    "A_주요계약": "주요 계약·수주 — 상대방·내용·기간·금액(표 행 그대로)",
    "B_성장동력": "성장 동력마다 단계 판정 ①개발·기술 ②고객·수주 ③생산·양산 ④매출 ⑤이익·현금",
    "C_전망": "회사가 스스로 밝힌 업황·수요 전망",
    "E_위험": "약세 시나리오 — 이 회사의 이익을 줄일 수 있는 요인",
}

PROMPT = """너는 한국 상장사 사업보고서를 읽고 투자 판단의 '맥락'을 정리하는 분석가다.
아래 원문(보고서의 '사업의 내용')만 근거로, 섹션별로 3~6개 항목을 쓴다.

규칙:
- claim: 한국어 한두 문장. 해석은 짧게. 원문에 없는 사실·숫자·외부 지식을 넣지 않는다.
- quote: claim 의 근거가 되는 원문 구절을 **글자 그대로** 복사한다(요약·수정 금지, 40~200자).
- claim 에 쓴 숫자는 반드시 quote 안에 그대로 있어야 한다. 계산한 숫자(비중·배수)를 새로 만들지 않는다.
- B_성장동력은 stage 에 ①~⑤ 중 하나를 넣는다. 다른 섹션은 stage 를 비운다.
- 원문에 근거가 없는 섹션은 항목을 넣지 않는다.
- 표는 한 행이 한 줄('칸 | 칸 | …')이다. 표에서 인용할 때는 그 행을 그대로 복사한다.
- summary: 이 회사의 지금 상태를 한 문장으로(숫자는 원문에 있는 것만).
- insights: 여러 항목을 엮은 해석 2~3문장(예: '이익이 한 부문에 몰려 있어 그 제품 가격에 민감하다').
  새 사실을 만들지 않는다. 숫자를 쓰면 원문에 있는 숫자만.

반드시 확인할 것(원문에 있으면 **빠짐없이** 항목으로 쓴다):
1. 부문별 매출과 영업이익 — 가장 큰 부문과 그 영업이익·매출 수치
2. 주요 제품·원재료의 가격 변화(몇 % 올랐나/내렸나)
3. 주요 매출처 이름과 상위 매출처 비중
4. 시장점유율 표 — 제품별 최신 연도 수치와 직전 연도 수치
5. 주요 계약·수주 표 — 상대방·내용·기간·금액
6. 신제품·신기술·신사업 각각의 단계(개발·샘플·수주·양산·매출)
7. 회사의 수요·공급 전망과, 수요를 둔화시킬 수 있다고 회사가 언급한 요인

섹션: {sections}

회사: {name}({ticker})
원문:
<<<
{text}
>>>"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "insights": {"type": "ARRAY", "items": {"type": "STRING"}},
        "items": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "section": {"type": "STRING", "enum": list(SECTIONS)},
                "claim": {"type": "STRING"},
                "stage": {"type": "STRING"},
                "quote": {"type": "STRING"},
            },
            "required": ["section", "claim", "quote"],
        }},
    },
    "required": ["summary", "items"],
}


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k in ("DART_API_KEY", "GEMINI_API_KEY")})
    return env


def dart_text(rcept, key):
    """보고서 원문 zip → 태그 뗀 텍스트. 표는 행=줄바꿈, 칸=' | '."""
    url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={key}&rcept_no={rcept}"
    raw = urllib.request.urlopen(url, timeout=60).read()
    if not raw.startswith(b"PK"):
        raise SystemExit("DART 원문 조회 실패: " + raw[:200].decode("utf-8", "replace"))
    z = zipfile.ZipFile(io.BytesIO(raw))
    main = max(z.namelist(), key=lambda n: z.getinfo(n).file_size)   # 본문이 가장 크다(첨부는 작다)
    x = z.read(main).decode("utf-8", "replace")
    # 표는 행 하나 = 한 줄('칸 | 칸 | 칸'). 칸마다 줄이 갈리면 모델이 행을 못 읽는다(2026-09-26: Tesla 계약·DRAM 점유율 놓침)
    cell = lambda c: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
    x = re.sub(r"<TR[^>]*>(.*?)</TR>", lambda m: " | ".join(
        cell(c) for _, c in re.findall(r"<(TD|TE|TU|TH)[^>]*>(.*?)</\1>", m.group(1), re.S)) + "\n", x, flags=re.S)
    x = re.sub(r"</(P|TITLE|SECTION-\d)>", "\n", x)
    x = re.sub(r"<[^>]+>", "", x)
    x = re.sub(r"&nbsp;|&#160;", " ", x).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", x))


def business_section(text):
    s = re.search(r"II\.\s*사업의\s*내용", text)
    e = re.search(r"III\.\s*재무에\s*관한\s*사항", text[s.end():]) if s else None
    if not s:
        return text[:MAX_CHARS], False
    body = text[s.start(): s.end() + e.start()] if e else text[s.start():]
    return body[:MAX_CHARS], len(body) > MAX_CHARS


def gemini(prompt, key, model=MODEL):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                 "responseSchema": SCHEMA}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(4):                     # 503(과부하)이 잦다 — 30·60·90초 쉬고 다시
        try:
            d = json.load(urllib.request.urlopen(req, timeout=300))
            break
        except urllib.error.HTTPError as e:
            if e.code != 503 or attempt == 3:
                raise
            time.sleep(30 * (attempt + 1))
    usage = d.get("usageMetadata", {})
    return json.loads(d["candidates"][0]["content"]["parts"][0]["text"]), usage


def squash(s):
    return re.sub(r"[\s|]+", "", s or "").replace(",", "")   # 표 칸 구분자도 무시


def numbers(s):
    return [n.rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", s or "")]


def check(item, source_sq):
    """통과면 None, 아니면 탈락 사유."""
    # 표는 머리행과 데이터행을 이어 인용한다(원문에선 떨어져 있다) — 줄·'…' 단위 조각마다 원문에 그대로 있으면 통과.
    # 모델이 줄바꿈을 글자 '\n' 으로 내는 경우도 있다(실측).
    parts = [squash(p) for p in re.split(r"\\n|\n|…|\.\.\.", item.get("quote") or "")]
    parts = [p for p in parts if p]
    q = "".join(parts)
    if len(q) < 10:
        return "인용이 너무 짧다"
    if len(parts) > 1 and min(map(len, parts)) < 6:
        return "인용 조각이 너무 짧다"                           # 짧은 조각을 이곳저곳에서 이어 붙이는 것을 막는다
    if any(p not in source_sq for p in parts):
        return "인용이 원문에 없다"
    # 연도는 맥락 표시라 원문 어딘가에만 있으면 된다
    missing = [n for n in numbers(item.get("claim"))
               if n.replace(",", "") not in q and not (re.fullmatch(r"(19|20)\d\d", n) and n in source_sq)]
    if missing:
        return "인용에 없는 숫자: " + ", ".join(missing)
    return None


def render(name, ticker, rcept, out, kept, dropped, usage, truncated, model=MODEL):
    lines = [f"# {name}({ticker}) 기업 해독 — Gemini 자동 시범 ({model})", "",
             f"> 자동 생성·**사람 검토 안 됨**. 근거 = DART 보고서 원문(rcept {rcept}) '사업의 내용'. "
             "모든 항목의 인용은 코드가 원문과 대조해 통과한 것만 실었다(공백 무시 완전 일치 + 주장 속 숫자가 인용 안에 있음). "
             "**매수·매도 추천이 아니며 점수에 쓰지 않는다.**", "",
             f"## 한 줄 요약", "", out.get("summary") or "-", ""]
    if out.get("insights"):
        lines += ["## 해석 (AI, 원문 사실을 엮은 것 — 새 숫자 없음을 코드가 확인)", ""] + [f"- {t}" for t in out["insights"]] + [""]
    for sec, desc in SECTIONS.items():
        its = [i for i in kept if i["section"] == sec]
        if not its:
            continue
        lines += [f"## {sec.replace('_', ' ')} — {desc}", ""]
        for i in its:
            st = f"**{i['stage']}** " if i.get("stage") else ""
            lines += [f"- {st}{i['claim']}", f"  > {i['quote'].strip()}"]
        lines.append("")
    lines += ["## 부록 — 검사 결과", "",
              f"- 통과 {len(kept)} · 탈락 {len(dropped)} · 입력 토큰 {usage.get('promptTokenCount')} · "
              f"출력 토큰 {usage.get('candidatesTokenCount')}" + (" · ★ 원문이 길어 잘랐다" if truncated else ""), ""]
    for i, why in dropped:
        lines += [f"- ❌ [{i.get('section')}] {why} — {i.get('claim')}", f"  > {i.get('quote', '').strip()[:200]}"]
    return "\n".join(lines) + "\n"


def selftest():
    src = squash("메모리 평균 판매가격은 전년 평균 대비 약 220% 상승하였습니다. 상위 5대 매출처 비중은 약 25%입니다.")
    ok = {"claim": "메모리 가격이 약 220% 올랐다", "quote": "메모리 평균 판매가격은 전년 평균 대비 약 220% 상승하였습니다."}
    assert check(ok, src) is None
    assert check({**ok, "claim": "메모리 가격이 약 250% 올랐다"}, src).startswith("인용에 없는 숫자")
    assert check({**ok, "quote": "메모리 가격이 크게 올랐다고 회사가 밝혔습니다"}, src) == "인용이 원문에 없다"
    assert check({"claim": "x", "quote": "짧다"}, src) == "인용이 너무 짧다"
    assert numbers("매출 1,234.5조 · 97%") == ["1,234.5", "97"]
    tsrc = squash("제 품 | 2026년 반기 | 2025년\nTV | 30.6% | 29.1%\nDRAM | 39.4% | 34.0%")
    row = {"claim": "DRAM 점유율 39.4%", "quote": "제 품 | 2026년 반기 | 2025년\\nDRAM | 39.4% | 34.0%"}
    assert check(row, tsrc) is None                               # 떨어진 머리행+데이터행, 글자 '\n'
    assert check({**row, "quote": "제 품 | 2026년 반기\\nDRAM | 41.0% | 34.0%"}, tsrc) == "인용이 원문에 없다"
    assert check({"claim": "2026년 반기 DRAM 39.4%", "quote": "DRAM | 39.4% | 34.0%"}, tsrc) is None   # 연도는 원문에만 있으면 됨
    assert check({"claim": "2031년 DRAM 39.4%", "quote": "DRAM | 39.4% | 34.0%"}, tsrc).startswith("인용에 없는 숫자")
    print("selftest ok (9)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker"), ap.add_argument("--name"), ap.add_argument("--rcept"), ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    env = load_env()
    if not env.get("DART_API_KEY") or not env.get("GEMINI_API_KEY"):
        raise SystemExit(".env 에 DART_API_KEY · GEMINI_API_KEY 가 필요하다")
    text, truncated = business_section(dart_text(a.rcept, env["DART_API_KEY"]))
    print(f"원문 사업의 내용 {len(text):,}자" + (" (잘림)" if truncated else ""))
    prompt = PROMPT.format(sections="\n".join(f"- {k}: {v}" for k, v in SECTIONS.items()),
                           name=a.name, ticker=a.ticker, text=text)
    out, usage = gemini(prompt, env["GEMINI_API_KEY"], a.model)
    src = squash(text)
    kept, dropped = [], []
    for it in out.get("items", []):
        why = check(it, src)
        (dropped.append((it, why)) if why else kept.append(it))
    # 요약·해석은 인용이 없다 — 숫자가 원문에 있는지만 본다. 없으면 그 문장을 버린다
    loose = lambda t: all(n.replace(",", "") in src for n in numbers(t))
    if out.get("summary") and not loose(out["summary"]):
        dropped.append(({"section": "summary", "claim": out["summary"], "quote": ""}, "원문에 없는 숫자"))
        out["summary"] = None
    bad = [t for t in out.get("insights") or [] if not loose(t)]
    dropped += [({"section": "insights", "claim": t, "quote": ""}, "원문에 없는 숫자") for t in bad]
    out["insights"] = [t for t in out.get("insights") or [] if loose(t)]
    print(f"항목 {len(kept) + len(dropped)} · 통과 {len(kept)} · 탈락 {len(dropped)} · 토큰 {usage}")
    Path(a.out).write_text(render(a.name, a.ticker, a.rcept, out, kept, dropped, usage, truncated, a.model), encoding="utf-8")
    print("saved:", a.out)


if __name__ == "__main__":
    sys.exit(main())
