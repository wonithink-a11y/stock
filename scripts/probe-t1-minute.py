"""probe-t1-minute.py — T1 수집 신뢰성 정찰 (MN-1.0 §6.1, 7일)

T0는 **API가 무엇을 주는가**를 한 번에 쟀다. T1은 **같은 것을 반복해도 같은가**를
잰다. 이건 한 번의 호출로 알 수 없고 며칠이 걸린다.

이 스크립트가 아닌 것
    수집이 아니다. Raw 네임스페이스에 쓰지 않는다.
    manifest를 만들지 않는다 - manifest는 '인수 조건을 통과했다'는 뜻이고(교훈43),
    정찰 산출물에 그것을 찍으면 그 뜻이 무너진다. 대신 (종목,날짜) 단위 rows
    sha256을 남긴다. 어느 종목이 갈렸는지 조각 파일보다 정확히 지목한다.

잴 수 없는 것을 재는 척하지 않는다
    dayVerdict는 전 종목을 봐야 나온다(교훈73). 표본 10종목으로는 '전부 비었다'가
    휴장인지 그 열이 모두 정지인지 못 가린다. 그러므로 계산하지 않고 그날 Broad
    수집의 manifest에서 읽어 참조로 기록한다. 없으면 미측정이다.

임계를 미리 정하지 않는다
    비교 '방법'은 여기서 고정한다 - 7개 필드 완전일치 · rows sha256 · 다른 필드 지목.
    '며칠 안에 몇 %까지 갈려도 정상인가'라는 '임계'는 7일 뒤에 정한다.
    뒤집힐 수 없게 설계된 정찰은 돌릴 이유가 없다(교훈51).

두 축을 잰다
    즉시 재실행   같은 실행 안에서 두 번 부른다 - 전송 흔들림과 데이터 변화를 가른다
    일자 간 재실행 어제 받은 (종목,날짜)를 오늘 다시 받는다 - §4가 말한 '버전'이
                  실제로 얼마나 자주 갈리는지

사용:
    python3 scripts/probe-t1-minute.py
    python3 scripts/probe-t1-minute.py --dry-run     표본과 대상만 보여준다
    python3 scripts/probe-t1-minute.py --report      쌓인 관측을 요약한다
    python3 scripts/probe-t1-minute.py --selftest
"""

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import sys
import time
import statistics as st
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "T1-1.0"

# 표본이 밟아야 하는 축. 리터럴 목록으로 고정한다 - '몇 개'로 적으면 하나가
# 빠져도 참으로 읽힌다(교훈59). 못 채운 축은 미측정으로 남긴다(교훈50·57).
REQUIRED_AXES = ["대형주", "소형주", "거래정지이력", "신규상장", "액면분할이력"]


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "collect_minute_kis", REPO / "scripts" / "collect-minute-kis.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def now_kst():
    return datetime.now(KST)


def stamp():
    return now_kst().strftime("%Y-%m-%dT%H:%M:%S+09:00")


def t1_dir():
    return Path(os.environ.get("MINUTE_T1_DIR")
                or (REPO / "data" / "minute" / "_t1")).expanduser()


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ---------------------------------------------------------------- 관측 해시

def rows_sha(rows):
    """관측 단위 해시. 정렬을 고정해 조회 순서가 해시를 흔들지 않게 한다.

    parquet 파일 해시가 아니라 값의 해시다. 파일은 압축·조각 구성에 따라
    달라지지만 값은 그렇지 않다 - 재현성은 값의 성질이지 파일의 성질이 아니다.
    """
    body = "\n".join(
        "%s %s %d %d %d %d %d" % (r["ticker"], r["ts"], r["open"], r["high"],
                                  r["low"], r["close"], r["volume"])
        for r in sorted(rows, key=lambda x: (x["ticker"], x["ts"])))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def compare_rows(a, b):
    """두 관측을 대조한다. '같다/다르다'로 끝내지 않고 어디가 갈렸는지 남긴다.

    필드별로 세는 이유는 축이 다르기 때문이다 - volume만 갈리면 정정 체결이고,
    가격이 통째로 비율만큼 갈리면 수정주가다. 한 칸에 넣으면 둘이 섞인다(교훈67).
    """
    PRICES = ("open", "high", "low", "close")
    ka = {(r["ticker"], r["ts"]): r for r in a}
    kb = {(r["ticker"], r["ts"]): r for r in b}
    only_a = sorted(set(ka) - set(kb))
    only_b = sorted(set(kb) - set(ka))
    fields = {}
    changed = []
    # 수정주가 판정은 '비율이 정확히 같은가'로 하면 절대 안 걸린다 - 가격은
    # 호가단위로 반올림되므로 105 -> 52는 0.5가 아니라 0.4952다. 그렇다고
    # 임의의 허용오차를 두면 그것이 곧 임계다(교훈51).
    # 반올림 자체가 주는 상한을 쓴다: 정수 v로 관측된 값의 참값은 [v-0.5, v+0.5]
    # 안에 있으므로 비율은 [(v-0.5)/p, (v+0.5)/p] 안에 있다. 이 구간들이 모두
    # 겹치면 '단일 비율 하나로 설명된다'가 성립한다. 유도된 경계이지 취향이 아니다.
    lo, hi = 0.0, float("inf")
    all4 = 0
    for k in sorted(set(ka) & set(kb)):
        ra, rb = ka[k], kb[k]
        diff = [f for f in PRICES + ("volume",) if ra[f] != rb[f]]
        if not diff:
            continue
        changed.append({"key": list(k), "fields": diff,
                        "before": {f: ra[f] for f in diff},
                        "after": {f: rb[f] for f in diff}})
        for f in diff:
            fields[f] = fields.get(f, 0) + 1
        # 분할은 네 가격을 모두 옮긴다. 하나만 바뀐 것은 정정이지 재조정이 아니다.
        if all(f in diff for f in PRICES):
            all4 += 1
            for f in PRICES:
                if ra[f]:
                    lo = max(lo, (rb[f] - 0.5) / float(ra[f]))
                    hi = min(hi, (rb[f] + 0.5) / float(ra[f]))

    consistent = all4 > 0 and lo <= hi
    rng = [round(lo, 6), round(hi, 6)] if consistent else None
    return {
        "identical": not (only_a or only_b or changed),
        "rowsBefore": len(a), "rowsAfter": len(b),
        "missingInSecond": [list(k) for k in only_a[:10]],
        "addedInSecond": [list(k) for k in only_b[:10]],
        "missingCount": len(only_a), "addedCount": len(only_b),
        "changedCount": len(changed),
        "changedFields": fields,
        "samples": changed[:5],
        # 측정값을 남긴다. 구간이지 점이 아닌 것이 사실에 가깝다.
        "rowsWithAllPricesChanged": all4,
        "priceRatioRange": rng,
        "looksLikeAdjustment": bool(consistent and not (lo <= 1.0 <= hi)),
    }


# ---------------------------------------------------------------- 계획
#
# ★ 표본과 anchor는 7일 동안 바뀌지 않는다.
#
# 매 실행마다 다시 고르면 일자간 대조가 성립하지 않는다. 어제의 '대형주'와
# 오늘의 '대형주'가 다른 종목이면 비교할 쌍이 없기 때문이다. 특히 폴백은
# 수집된 날짜에서 순위를 내므로 하루가 지날 때마다 값이 달라진다.
#
# 그래서 첫 실행이 계획을 만들어 얼려 두고, 이후 실행은 그것을 읽기만 한다.
# 계획을 바꾸려면 --replan 이라는 명시적 행위가 필요하고, 그때 이전 계획을
# 무엇으로 대체했는지 기록에 남는다.

PLAN_VERSION = "T1PLAN-1.0"
TURNOVER_WINDOW = 5          # 폴백 집계 범위(수집일). 계획 시점에 한 번만 쓴다


def plan_path(outdir):
    return Path(outdir) / "plan.json"


def plan_hash(plan):
    """계획의 신원. 창 도중에 계획이 바뀌면 대조 결과가 그것을 드러내야 한다."""
    core = {"anchorDate": plan.get("anchorDate"),
            "sample": sorted((s["ticker"], s["axis"])
                             for s in (plan.get("sample") or []))}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:16]


def load_plan(outdir):
    return safe(lambda: json.loads(
        plan_path(outdir).read_text(encoding="utf-8")))


def save_plan(outdir, plan):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    with open(plan_path(outdir), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- 표본

def collected_dates(raw_root):
    return sorted(p.name.split("=")[1]
                  for p in Path(raw_root).glob("date=*") if "=" in p.name)


def turnover_from_snapshot(universe_dir=None):
    """유니버스 스냅샷의 거래대금. 있으면 이것을 쓴다 - 일봉 60거래일 중앙값이라
    폴백보다 정확하고, 다른 단계와 같은 정의를 쓴다."""
    d = Path(universe_dir or (REPO / "data" / "backfill" / "minute" / "universe"))
    snaps = sorted(d.glob("*.jsonl")) if d.exists() else []
    if not snaps:
        return None, None
    out = {}
    for line in safe(lambda: snaps[-1].read_text(encoding="utf-8"), "").splitlines():
        if line.strip():
            r = safe(lambda l=line: json.loads(l))
            if r and r.get("ticker"):
                out[r["ticker"]] = r.get("turnoverEok") or 0.0
    return (out, "universe-snapshot:" + snaps[-1].name) if out else (None, None)


def turnover_from_parquet(raw_root, dates):
    """수집한 분봉에서 종목별 일 거래대금 중앙값(억). 스냅샷이 없을 때의 폴백.

    스냅샷(일봉 60거래일)보다 거칠다. 그래도 되는 이유는 이 값이 정하는 것이
    '대형주와 소형주가 표본에 있다'뿐이고 PIT 정확성이 필요 없기 때문이다.
    선정 근거는 계획에 문자열로 남으므로 나중에 되짚을 수 있다.

    **이 값은 계획을 만들 때 한 번만 쓴다.** 매일 다시 계산하면 순위가 흔들려
    표본이 바뀌고, 그러면 일자간 대조가 성립하지 않는다.

    1GB VM이라 열 단위로 읽고 파일마다 버린다. to_pylist()를 행 단위로 쓰면
    45,000개 dict가 파일마다 생긴다.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return None, None
    per = {}
    used = []
    for d in dates:
        files = sorted(Path(raw_root).glob("date=" + d + "/part-*.parquet"))
        if not files:
            continue
        day = {}
        for f in files:
            t = safe(lambda f=f: pq.read_table(
                f, columns=["ticker", "close", "volume"]))
            if t is None:
                continue
            tk = t.column("ticker").to_pylist()
            cl = t.column("close").to_pylist()
            vo = t.column("volume").to_pylist()
            del t
            for i in range(len(tk)):
                day[tk[i]] = day.get(tk[i], 0) + cl[i] * vo[i]
            del tk, cl, vo
        if not day:
            continue
        used.append(d)
        for k, v in day.items():
            per.setdefault(k, []).append(v)
    if not per:
        return None, None
    med = {k: st.median(v) / 1e8 for k, v in per.items()}
    return med, ("parquet-turnover:" + ",".join(used))


def pick_anchor(manifest_dir, dates):
    """anchor = 인수 조건을 통과한 **가장 오래된** 수집일.

    최근이 아니라 오래된 것을 고른다. 롤링 창(최근 N일)이 이미 '갓 받은
    데이터가 안정되는가'를 재기 때문이다. anchor가 재야 하는 것은 다른
    질문 - '이미 안정됐어야 할 과거가 흔들리는가'이고, 그 신호는 오래된
    날일수록 세다. anchor는 고정이므로 7일 동안 계속 늙는다.

    인수 조건 통과를 요구하는 이유는 혼동 제거다. 미완료 날짜를 anchor로
    잡으면 날짜 간 차이가 소스의 사후 변경인지 우리 수집이 덜 된 것인지
    가릴 수 없다. 휴장일도 고르지 않는다 - 잴 것이 없다.
    """
    for d in dates:                      # 오름차순 = 오래된 것부터
        m = safe(lambda d=d: json.loads(
            (Path(manifest_dir) / (d + ".json")).read_text(encoding="utf-8")))
        if not m or not m.get("acceptancePassed"):
            continue
        if str(m.get("dayVerdict") or "").startswith("CLOSED"):
            continue
        if not (m.get("rows") or 0) > 0:
            continue
        return d, ("인수 조건을 통과한 가장 오래된 수집일 · %s · rows %s"
                   % (m.get("dayVerdict"), m.get("rows")))
    return None, "미측정 — 인수 조건을 통과한 수집일이 없다"


def pick_sample(M, raw_root, turnover=None, turnover_source=None,
                state_dir=None):
    """표본은 의도적으로 고른다(§6.1). 무작위 5종목은 갈리는 축을 못 밟는다.

    고른 이유를 함께 남긴다. 나중에 '왜 이 종목인가'를 되짚을 수 없으면
    결과의 일반화 범위를 말할 수 없다.
    """
    chosen, axes = [], {}
    unmeasured = []

    def take(ticker, axis, why):
        if not ticker or any(c["ticker"] == ticker for c in chosen):
            return False
        chosen.append({"ticker": ticker, "axis": axis, "why": why,
                       "source": turnover_source if axis in ("대형주", "소형주")
                       else "observed"})
        axes[axis] = ticker
        return True

    # 대형주 · 소형주 — 거래대금 순위. 출처는 스냅샷이거나 수집한 parquet다.
    if turnover:
        rank = sorted(((v, k) for k, v in turnover.items() if v and v > 0),
                      reverse=True)
        for v, k in rank[:2]:
            take(k, "대형주", "거래대금 상위 %.0f억 (%s)" % (v, turnover_source))
        for v, k in rank[-2:]:
            take(k, "소형주", "거래대금 하위 %.2f억 (%s)" % (v, turnover_source))
    else:
        unmeasured.append("대형주·소형주 — 거래대금 출처가 없다 "
                          "(유니버스 스냅샷도 수집된 parquet도 읽지 못했다)")

    # 거래정지 이력 — Broad 수집 상태에서 HALT가 실제로 난 종목을 쓴다.
    # 추측이 아니라 우리가 관측한 사실에서 고른다.
    halted = []
    sd = Path(state_dir or (Path(raw_root) / "_state"))
    for p in sorted(sd.glob("state-*.json"))[-5:] if sd.exists() else []:
        stt = safe(lambda p=p: json.loads(p.read_text(encoding="utf-8"))) or {}
        for tk, v in (stt.get("symbols") or {}).items():
            if v.get("gapReason") == "HALT":
                halted.append((tk, p.name))
    if halted:
        take(halted[0][0], "거래정지이력",
             "Broad 수집에서 HALT 관측 (%s)" % halted[0][1])
    else:
        unmeasured.append("거래정지이력 — 수집 상태에 HALT가 없다")

    # 신규상장 — A1a의 listedAt 최신
    a1a = [r for r in M.read_a1a() if r.get("listedAt")]
    a1a.sort(key=lambda r: r["listedAt"], reverse=True)
    if a1a:
        take(a1a[0]["ticker"], "신규상장", "상장일 " + a1a[0]["listedAt"])
    else:
        unmeasured.append("신규상장 — A1a에 listedAt이 없다")

    # 액면분할 이력 — 확보 수단이 없다.
    # A2a는 adjusted=true라 분할이 이미 반영돼 불연속이 남지 않고, 분할 원장도 없다.
    # 잴 수 없는 것을 통과로 적지 않는다(교훈50).
    unmeasured.append(
        "액면분할이력 — 표본 확보 수단이 없다. A2a는 수정주가라 불연속이 남지 "
        "않고 분할 원장도 없다. 7일 안에 분할이 없으면 '수정주가 변경 없음'은 "
        "확인이 아니라 미관측이다(§6.1)")

    missing = [a for a in REQUIRED_AXES if a not in axes]
    return chosen, unmeasured, missing


def derive_plan(M, raw_root, state_dir, manifest_dir, universe_dir=None,
                window_days=7):
    """7일 창의 계획을 만든다. 첫 실행에서 한 번만 부른다."""
    dates = collected_dates(raw_root)
    turn, src = turnover_from_snapshot(universe_dir)
    if not turn:
        # 스냅샷이 없다. 이미 받아 둔 분봉에서 같은 축을 만든다 -
        # SSH 없이도 표본이 서게 하는 안전망이다. 스냅샷이 생기면
        # 다음 창부터 그것을 쓴다(이 창은 계획이 얼어 있다).
        turn, src = turnover_from_parquet(raw_root, dates[-TURNOVER_WINDOW:])
    sample, unmeasured, missing = pick_sample(
        M, raw_root, turnover=turn, turnover_source=src, state_dir=state_dir)
    anchor, anchor_why = pick_anchor(manifest_dir, dates)
    if not anchor:
        unmeasured.append("고정 관측일(anchor) — " + anchor_why)

    plan = {
        "schemaVersion": PLAN_VERSION,
        "createdAt": stamp(),
        "windowDays": window_days,
        "frozen": True,
        "frozenNote": "표본과 anchor는 이 창 동안 바뀌지 않는다. 매 실행마다 "
                      "다시 고르면 어제의 '대형주'와 오늘의 것이 달라져 "
                      "일자간 대조에 쓸 쌍이 없다. 바꾸려면 --replan.",
        "turnoverSource": src,
        "turnoverWindowDates": dates[-TURNOVER_WINDOW:],
        "collectedDatesAtPlanning": dates,
        "sample": sample,
        "sampleAxesMissing": missing,
        "anchorDate": anchor,
        "anchorWhy": anchor_why,
        "anchorRule": "인수 조건을 통과하고 휴장이 아닌 가장 오래된 수집일. "
                      "최근이 아니라 오래된 것을 고르는 이유는 롤링 창이 이미 "
                      "'갓 받은 데이터가 안정되는가'를 재기 때문이다 - anchor는 "
                      "'이미 안정됐어야 할 과거가 흔들리는가'를 잰다.",
        "unmeasured": unmeasured,
    }
    plan["planHash"] = plan_hash(plan)
    return plan


def target_dates(plan, raw_root, back=2):
    """anchor(고정) + 최근 수집일(롤링). 두 축을 함께 본다.

    롤링   갓 받은 데이터가 다음 날 같은가        재현성
    anchor 오래된 날이 7일 동안 흔들리는가        사후 변경·수정주가
    """
    got = collected_dates(raw_root)
    roll = got[-back:] if got else []
    a = plan.get("anchorDate")
    out = list(roll)
    if a and a not in out:
        out.insert(0, a)
    return out


# ---------------------------------------------------------------- 실행

def read_day_verdict(manifest_dir, date):
    """그날의 dayVerdict를 Broad manifest에서 읽어온다. 계산하지 않는다.

    표본 열 종목으로 날짜 단위 판정을 흉내 내면 그건 측정이 아니라 추측이다.
    """
    p = Path(manifest_dir) / (date + ".json")
    m = safe(lambda: json.loads(p.read_text(encoding="utf-8")))
    if not m:
        return None, "미측정 — 그날 Broad manifest가 없다"
    return m.get("dayVerdict"), "broad-manifest"


def observe(M, transport, ticker, date, pol, ctx):
    """한 관측. 호출 수와 결과를 함께 남긴다."""
    calls = {"n": 0}
    inner = transport

    class Counting:
        def fetch(self, tk, sent, hour, p):
            calls["n"] += 1
            return inner.fetch(tk, sent, hour, p)

    t0 = time.time()
    o = M.collect_symbol_day(Counting(), ticker, date, pol, ctx)
    rows = list(o.rows)
    return {
        "ticker": ticker, "date": date,
        "requestedAt": stamp(),
        "elapsedSec": round(time.time() - t0, 2),
        "calls": calls["n"], "attempts": o.attempts,
        "status": o.status,
        "rows": len(rows),
        "gapReason": o.gap_reason,
        "failureClass": o.failure_class,
        "sha256": rows_sha(rows) if rows else None,
        "firstTs": rows[0]["ts"] if rows else None,
        "lastTs": rows[-1]["ts"] if rows else None,
        "_rows": rows,
    }


def prior_runs(d):
    out = []
    for p in sorted(Path(d).glob("t1-*.json")):
        r = safe(lambda p=p: json.loads(p.read_text(encoding="utf-8")))
        if r:
            out.append((p.name, r))
    return out


def run(M, args, out=print):
    pol = M.load_policy()
    ctx = M.load_context()
    raw, state, mandir = M.env_paths(pol)
    outdir = t1_dir()

    # 계획을 먼저 읽는다. 있으면 그대로 쓴다 - 표본과 anchor는 창 동안
    # 바뀌지 않아야 하고, 그것이 일자간 대조가 성립하는 유일한 조건이다.
    plan = load_plan(outdir)
    replaced = None
    if plan is None or args.replan:
        replaced = plan
        plan = derive_plan(M, raw, state, mandir, window_days=args.window)
        if replaced:
            plan["replacedPlan"] = {"createdAt": replaced.get("createdAt"),
                                    "planHash": replaced.get("planHash"),
                                    "replacedAt": stamp()}
        if not args.dry_run:
            save_plan(outdir, plan)
        plan_state = "새로 세움" + (" (--replan으로 교체)" if replaced else "")
    else:
        plan_state = "기존 계획 재사용 (" + str(plan.get("createdAt")) + ")"

    sample = plan.get("sample") or []
    unmeasured = list(plan.get("unmeasured") or [])
    missing_axes = plan.get("sampleAxesMissing") or []
    dates = target_dates(plan, raw, back=args.dates)

    out("")
    out("  T1 수집 신뢰성 정찰   " + stamp())
    out("  계획 " + plan_state + "  hash " + str(plan.get("planHash")))
    out("  표본 " + str(len(sample)) + "종목 · 대상 " + str(len(dates)) + "일 · 출력 "
        + str(outdir))
    for s in sample:
        out("    " + s["ticker"] + "  " + s["axis"].ljust(12) + s["why"])
    out("  고정 관측일 " + str(plan.get("anchorDate")) + "  "
        + str(plan.get("anchorWhy")))
    for u in unmeasured:
        out("    [미측정] " + u)
    if not dates:
        out("  [중단] 대상 날짜가 없다 - Broad 수집물이 " + str(raw) + "에 없다")
        return 2, None
    out("  대상 날짜 " + ", ".join(dates) + "   (anchor 고정 + 최근 롤링)")
    out("")

    if args.dry_run:
        out("  --dry-run: 부르지 않았고 계획도 쓰지 않았다")
        return 0, None

    if not sample:
        out("  [중단] 표본이 비었다")
        return 2, None

    key, sec = M.credentials()
    token, how = M.get_token(key, sec)
    tr = M.KisTransport(key, sec, token)

    run_id = now_kst().strftime("%Y%m%dT%H%M%S")
    obs, repeats = [], []
    for s in sample:
        for d in dates:
            a = observe(M, tr, s["ticker"], d, pol, ctx)
            # 즉시 재실행 — 전송 흔들림과 데이터 변화를 가른다.
            # 첫 날짜에만 한다. 전부 하면 호출이 두 배가 되는데 얻는 것은 같다.
            if d == dates[-1] and d != plan.get("anchorDate"):
                b = observe(M, tr, s["ticker"], d, pol, ctx)
                cmp_ = compare_rows(a["_rows"], b["_rows"])
                cmp_.update({"ticker": s["ticker"], "date": d,
                             "shaA": a["sha256"], "shaB": b["sha256"]})
                repeats.append(cmp_)
                obs.append({k: v for k, v in b.items() if k != "_rows"})
            obs.append({k: v for k, v in a.items() if k != "_rows"})
            a["axis"] = s["axis"]

    # --- 일자 간 대조 --------------------------------------------------------
    # 어제 이 스크립트가 남긴 관측과 오늘 것을 (종목,날짜)로 맞춰 본다.
    cross = []
    for name, prev in prior_runs(outdir):
        idx = {}
        for o in prev.get("observations") or []:
            if o.get("sha256"):
                idx[(o["ticker"], o["date"])] = o
        for o in obs:
            k = (o["ticker"], o["date"])
            if k in idx and o.get("sha256"):
                p = idx[k]
                cross.append({
                    "ticker": o["ticker"], "date": o["date"],
                    "prevRun": name, "prevRequestedAt": p.get("requestedAt"),
                    "prevSha": p["sha256"], "sha": o["sha256"],
                    "identical": p["sha256"] == o["sha256"],
                    "prevRows": p.get("rows"), "rows": o.get("rows"),
                })

    verdicts = {}
    for d in dates:
        v, src = read_day_verdict(mandir, d)
        verdicts[d] = {"dayVerdict": v, "source": src}

    gaps = {}
    for o in obs:
        if o.get("gapReason"):
            gaps[o["gapReason"]] = gaps.get(o["gapReason"], 0) + 1

    report = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "startedAt": stamp(),
        "host": os.environ.get("HOSTNAME") or "unknown",
        "policyVersion": pol["version"],
        "collectionContractHash": M.sha256_bytes(
            json.dumps(pol["collectionContract"], sort_keys=True,
                       ensure_ascii=False).encode("utf-8")),
        "tokenSource": how,
        "planHash": plan.get("planHash"),
        "planCreatedAt": plan.get("createdAt"),
        "anchorDate": plan.get("anchorDate"),
        "turnoverSource": plan.get("turnoverSource"),
        "sample": sample,
        "sampleAxesMissing": missing_axes,
        "unmeasured": unmeasured,
        "targetDates": dates,
        "symbolCount": len(sample),
        "requestCount": sum(o.get("calls") or 0 for o in obs),
        "observationCount": len(obs),
        "okCount": sum(1 for o in obs if o["status"] == "OK"),
        "gapCount": sum(1 for o in obs if o["status"] == "GAP"),
        "unresolvedCount": sum(1 for o in obs if o["status"] == "UNRESOLVED"),
        "gapReasons": gaps,
        "dayVerdicts": verdicts,
        "observations": obs,
        "immediateRepeat": repeats,
        "crossRun": cross,
        "reproducibilityMethod": {
            "note": "비교 '방법'만 확정한다. '며칠 안에 몇 %까지 갈려도 정상인가'는 "
                    "7일 측정 뒤에 정한다 - 지금 임계를 박으면 그 임계에 맞는 답만 "
                    "나온다(교훈51).",
            "unit": "(ticker, date)",
            "fields": ["ticker", "ts", "open", "high", "low", "close", "volume"],
            "equality": "전 필드 완전일치. 허용 오차 없음",
            "hash": "rows sha256 — (ticker, ts) 정렬 후 값 직렬화",
            "adjustmentSignal": "가격 넷이 한 비율로 갈리면 수정주가 재조정",
            "thresholdDecided": False,
        },
        "notAMeasurement": [
            "dayVerdict는 T1이 계산하지 않는다. 전 종목 범위의 값이라 표본으로 "
            "흉내 내면 추측이 된다(교훈73). Broad manifest에서 읽어 참조로만 둔다.",
            "이 산출물은 manifest가 아니다. 인수 조건을 통과했다는 뜻을 담지 않는다.",
        ],
    }

    outdir.mkdir(parents=True, exist_ok=True)
    p = outdir / ("t1-" + run_id + ".json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    out("  관측 %d · 호출 %d · OK %d · GAP %d · 미해결 %d"
        % (report["observationCount"], report["requestCount"],
           report["okCount"], report["gapCount"], report["unresolvedCount"]))
    for r in repeats:
        out("  즉시재실행  " + r["ticker"] + " " + r["date"] + "  " +
            ("동일" if r["identical"] else
             "다름 rows %d->%d 변경 %d %s" % (r["rowsBefore"], r["rowsAfter"],
                                            r["changedCount"],
                                            json.dumps(r["changedFields"],
                                                       ensure_ascii=False))))
    if cross:
        same = sum(1 for c in cross if c["identical"])
        out("  일자간대조  %d건 중 동일 %d · 다름 %d"
            % (len(cross), same, len(cross) - same))
        for c in cross:
            if not c["identical"]:
                out("    다름  " + c["ticker"] + " " + c["date"] +
                    "  rows %s->%s  (%s)" % (c["prevRows"], c["rows"],
                                             c["prevRun"]))
    else:
        out("  일자간대조  없음 (첫 실행이다. 내일부터 쌓인다)")
    out("  " + str(p))
    out("")
    return 0, report


def report_only(out=print):
    d = t1_dir()
    runs = prior_runs(d)
    if not runs:
        out("  T1 관측이 없다: " + str(d))
        return 1
    out("")
    pl = load_plan(d) or {}
    out("  T1 누적 요약   실행 " + str(len(runs)) + "회")
    out("  계획 " + str(pl.get("createdAt")) + "  hash " + str(pl.get("planHash"))
        + "  anchor " + str(pl.get("anchorDate")))
    hashes = {r.get("planHash") for _, r in runs if r.get("planHash")}
    if len(hashes) > 1:
        out("  ★ 창 도중에 계획이 바뀌었다 " + str(sorted(hashes))
            + " — 그 경계를 넘는 대조는 같은 표본이 아니다")
    tot = same = 0
    for name, r in runs:
        c = r.get("crossRun") or []
        s = sum(1 for x in c if x["identical"])
        tot += len(c)
        same += s
        out("  %s  관측 %3d · 호출 %4d · 일자간 %d/%d 동일"
            % (r.get("runId"), len(r.get("observations") or []),
               r.get("requestCount") or 0, s, len(c)))
    out("")
    out("  누적 일자간 대조  %d건 중 동일 %d" % (tot, same))
    if tot == 0:
        out("  재현성: 미측정 (대조 쌍이 아직 없다)")
    else:
        out("  재현성: %d/%d = %.4f  ← 임계는 아직 정하지 않았다" %
            (same, tot, same / float(tot)))
    um = sorted({u for _, r in runs for u in (r.get("unmeasured") or [])})
    for u in um:
        out("  [미측정] " + u)
    out("")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", type=int, default=2,
                    help="롤링 대상 - 최근 수집일 중 몇 개 (anchor는 별도로 고정)")
    ap.add_argument("--window", type=int, default=7, help="정찰 창 (일)")
    ap.add_argument("--replan", action="store_true",
                    help="얼어 있는 표본·anchor를 다시 고른다. 창 도중에 쓰면 "
                         "일자간 대조가 끊긴다")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        p = REPO / "scripts" / "test-probe-t1-minute.py"
        if not p.exists():
            print("테스트 파일이 없다")
            return 1
        spec = importlib.util.spec_from_file_location("t", p)
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        return t.run_all(sys.modules[__name__])

    if args.report:
        return report_only()

    M = load_collector()
    try:
        code, _ = run(M, args)
    except SystemExit as e:
        print("  [중단] " + str(e))
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
