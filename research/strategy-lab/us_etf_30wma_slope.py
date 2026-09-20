"""미국 ETF 30주선 기울기 — 사전등록(f87b550) 결과 산출.

사전등록: findings/us-etf-30wma-slope-preregistration-2026-09.md (결과 전 커밋, 불변).
가설 H1 하나: 30주 SMA 10주 기울기 > 0(ON) 이면 다음 주 수익이 더 높다.
조건·기간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

  python research/strategy-lab/us_etf_30wma_slope.py --selftest    # 네트워크 없음
  python research/strategy-lab/us_etf_30wma_slope.py               # 데이터 받아 결과 산출(.cache 에 동결)
  python research/strategy-lab/us_etf_30wma_slope.py --refresh     # 캐시를 지우고 다시 받음

산출: findings/us-etf-30wma-slope-results-2026-09.{md,json}
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache" / "us_etf_30wma"
OUT = HERE / "findings" / "us-etf-30wma-slope-results-2026-09"

ETFS = ["SPY", "QQQ", "IWM", "EFA", "EEM"]
REF = "^KS11"
LAST_DAY = "2026-09-18"          # 사전등록: 종료 2026-09-18
WARM = 40                        # 사전등록: 첫 40주 워밍업 버림
SMA_W, SLOPE_W = 30, 10
MIN_WEEKS = 20                   # 사전등록 §4: ON 또는 OFF 가 20주 미만이면 그 창에서 제외
N_PERM, SEED = 1000, 20260921
SHIFT_MIN = 52                   # 사전등록 §3: 오프셋 52주 ~ n-52주
COST1, COST2 = 5e-4, 10e-4       # 편도 5bp / 스트레스 10bp
TRAIN_END, VALID_END = "2010-12-31", "2017-12-31"
WINDOWS = ["TRAIN", "VALID", "TEST"]


# ---------------------------------------------------------------- 데이터
def load_daily(sym, refresh=False):
    """yfinance 일봉 종가(auto_adjust=True, 사전등록). 첫 실행 때 .cache 에 동결한다."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (sym.replace("^", "_") + ".parquet")
    if f.exists() and not refresh:
        return pd.read_parquet(f)["close"]
    import yfinance as yf
    d = yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=True)
    s = d["Close"].copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    s = s[s.index <= pd.Timestamp(LAST_DAY)].dropna()
    s.to_frame("close").to_parquet(f)
    return s


def to_weekly(close):
    """금요일 기준 주 마지막 거래일 종가(사전등록 §1)."""
    return close.resample("W-FRI").last().dropna()


def build(wk):
    """주봉 종가 -> 신호·수익 프레임. 인덱스 = 신호 주 t, 첫 40주는 버린다, 마지막 주는 다음 주 수익이 없어 버린다."""
    d = pd.DataFrame({"close": wk})
    d["sma"] = d.close.rolling(SMA_W).mean()
    d["slope"] = d.sma / d.sma.shift(SLOPE_W) - 1
    d["r1"] = d.close.shift(-1) / d.close - 1
    d["r13"] = d.close.shift(-13) / d.close - 1
    d["on"] = d.slope > 0
    d["above"] = d.close > d.sma
    d = d.iloc[WARM:]
    d = d[d.r1.notna()].copy()
    d["pos"] = d.on.astype(float)
    return d


def win_mask(idx, name):
    t = pd.DatetimeIndex(idx)
    if name == "TRAIN":
        return t <= pd.Timestamp(TRAIN_END)
    if name == "VALID":
        return (t > pd.Timestamp(TRAIN_END)) & (t <= pd.Timestamp(VALID_END))
    if name == "TEST":
        return t > pd.Timestamp(VALID_END)
    if name == "VT":
        return t > pd.Timestamp(TRAIN_END)
    raise ValueError(name)


# ---------------------------------------------------------------- 통계량
def spread_one(r, state, m, min_weeks=MIN_WEEKS):
    """평균 r | state - 평균 r | ~state (창 m 안). 한쪽이 min_weeks 미만이면 nan(제외)."""
    ok = m & ~np.isnan(r)
    a, b = r[ok & state], r[ok & ~state]
    if len(a) < min_weeks or len(b) < min_weeks:
        return np.nan
    return a.mean() - b.mean()


def pooled(vals):
    v = [x for x in vals if not np.isnan(x)]
    return (float(np.mean(v)) if v else np.nan), len(v)


def null_baseline(frames, window, rng, n_perm=N_PERM):
    """ON/OFF 상태열을 ETF 별로 순환 이동(오프셋 52..n-52) 한 뒤 창 S 의 95번째 백분위."""
    prep = []
    for d in frames.values():
        prep.append((d.r1.to_numpy(), d.on.to_numpy(), win_mask(d.index, window)))
    draws = np.empty(n_perm)
    for i in range(n_perm):
        vals = []
        for r, on, m in prep:
            n = len(on)
            k = int(rng.integers(SHIFT_MIN, n - SHIFT_MIN + 1))
            vals.append(spread_one(r, np.roll(on, k), m))
        draws[i] = pooled(vals)[0]
    return float(np.nanpercentile(draws, 95)), draws


# ---------------------------------------------------------------- 전략
def strategy_returns(d, cost):
    """주 t 종가에 ON 이면 주 t+1 보유. 상태가 바뀔 때마다 편도 cost. OFF 는 현금 0."""
    pos = d.pos
    sw = pos.diff().abs()
    sw.iloc[0] = pos.iloc[0]         # 현금에서 시작
    return pos * d.r1 - cost * sw


def sharpe(r):
    r = np.asarray(r, dtype=float)
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(52)) if sd > 0 else np.nan


def cagr(r):
    r = np.asarray(r, dtype=float)
    return float(np.prod(1 + r) ** (52 / len(r)) - 1)


def mdd(r):
    eq = np.cumprod(1 + np.asarray(r, dtype=float))
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float((eq / peak - 1).min())


# ---------------------------------------------------------------- 실행
def run(frames, ref_frame):
    rng = np.random.default_rng(SEED)
    res = {"seed": SEED, "n_perm": N_PERM}

    # 창별 ETF 별 S, ON/OFF 주 수
    per = {}
    for w in WINDOWS + ["VT"]:
        per[w] = {}
        for s, d in frames.items():
            m = win_mask(d.index, w)
            r, on = d.r1.to_numpy(), d.on.to_numpy()
            ok = m & ~np.isnan(r)
            per[w][s] = {"S": spread_one(r, on, m), "n_on": int((ok & on).sum()), "n_off": int((ok & ~on).sum())}
    res["per_etf"] = per
    S = {}
    for w in WINDOWS + ["VT"]:
        S[w], used = pooled([per[w][s]["S"] for s in frames])
        res.setdefault("etfs_used", {})[w] = used
    res["S"] = S

    base, draws = null_baseline(frames, "TRAIN", rng)
    res["baseline95_train"] = base
    res["null_train_mean"] = float(np.nanmean(draws))

    # 전략 vs 매수보유 (VALID+TEST)
    econ = {}
    for label, cost in (("cost1", COST1), ("cost2", COST2)):
        diffs = []
        for s, d in frames.items():
            m = win_mask(d.index, "VT")
            st = strategy_returns(d, cost)[m]
            diffs.append(sharpe(st) - sharpe(d.r1[m]))
        econ[label] = float(np.mean(diffs))
        econ[label + "_per_etf"] = dict(zip(frames, diffs))
    res["econ"] = econ

    n_pos = sum(1 for s in frames if per["VT"][s]["S"] > 0)
    n_valid = sum(1 for s in frames if not np.isnan(per["VT"][s]["S"]))
    res["vt_positive_etfs"] = {"positive": n_pos, "of": n_valid}

    info = bool(S["TRAIN"] >= base and S["VALID"] > 0 and S["TEST"] > 0)
    econo = bool(info and econ["cost1"] > 0 and econ["cost2"] > 0)
    robust = bool(econo and n_pos >= 4)
    res["verdict"] = "ROBUST" if robust else "ECONOMIC" if econo else "INFORMATION" if info else "REJECT"
    res["verdict_parts"] = {"information": info, "economic": econo, "robust": robust}

    # ---- 기록 전용 ----
    rec = {}
    # R1 수준 셀
    r1c = {}
    for w in WINDOWS:
        vals = []
        for s, d in frames.items():
            vals.append(spread_one(d.r1.to_numpy(), d.above.to_numpy(), win_mask(d.index, w)))
        r1c[w] = dict(zip(["S", "etfs_used"], pooled(vals)))
    rec["R1_level"] = r1c
    # R2 2x2 (ETF-주 풀링, 주 수 가중)
    r2 = {}
    for w in WINDOWS + ["ALL"]:
        cells = {}
        for son, sn in ((True, "slope+"), (False, "slope-")):
            for ab, an in ((True, "above"), (False, "below")):
                rs = []
                for d in frames.values():
                    m = np.ones(len(d), bool) if w == "ALL" else win_mask(d.index, w)
                    sel = m & (d.on.to_numpy() == son) & (d.above.to_numpy() == ab)
                    rs.append(d.r1.to_numpy()[sel])
                x = np.concatenate(rs)
                cells[f"{sn}/{an}"] = {"mean_next_week": float(x.mean()) if len(x) else None, "weeks": int(len(x))}
        r2[w] = cells
    rec["R2_2x2"] = r2
    # R3 한국 대조
    r3 = {}
    for w in WINDOWS + ["VT"]:
        m = win_mask(ref_frame.index, w)
        r, on = ref_frame.r1.to_numpy(), ref_frame.on.to_numpy()
        ok = m & ~np.isnan(r)
        r3[w] = {"S": spread_one(r, on, m), "n_on": int((ok & on).sum()), "n_off": int((ok & ~on).sum())}
    rec["R3_KS11"] = r3
    # R4 13주 forward (겹침, 참고)
    r4 = {}
    for w in WINDOWS:
        vals = [spread_one(d.r13.to_numpy(), d.on.to_numpy(), win_mask(d.index, w)) for d in frames.values()]
        r4[w] = dict(zip(["S13", "etfs_used"], pooled(vals)))
    rec["R4_fwd13_overlap"] = r4
    # R5 연도별 S 부호 (ETF 균등평균, 한쪽 상태가 1주 미만인 ETF 는 제외)
    years = sorted({t.year for d in frames.values() for t in d.index})
    r5 = {}
    for y in years:
        vals = []
        for d in frames.values():
            m = np.asarray(d.index.year == y)
            vals.append(spread_one(d.r1.to_numpy(), d.on.to_numpy(), m, min_weeks=1))
        v, used = pooled(vals)
        r5[str(y)] = {"S": v, "etfs_used": used}
    rec["R5_yearly_S"] = r5
    # R6 전략 MDD·CAGR·시장 노출 (VALID+TEST, 비용 1배) vs 매수보유
    r6 = {}
    for s, d in frames.items():
        m = win_mask(d.index, "VT")
        st = strategy_returns(d, COST1)[m]
        bh = d.r1[m]
        r6[s] = {
            "strategy_net": {"CAGR": cagr(st), "MDD": mdd(st), "Sharpe": sharpe(st)},
            "buy_hold": {"CAGR": cagr(bh), "MDD": mdd(bh), "Sharpe": sharpe(bh)},
            "exposure": float(d.pos[m].mean()),
            "weeks": int(m.sum()),
        }
    rec["R6_strategy_vs_bh_VT"] = r6
    res["record_only"] = rec
    return res


# ---------------------------------------------------------------- 보고서
def f(x, nd=4, pct=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x*100:.2f}%" if pct else f"{x:.{nd}f}"


def render(res, meta):
    P, R = res["per_etf"], res["record_only"]
    v = res["verdict"]
    L = []
    L.append("---")
    L.append("track: us")
    L.append("factor: us-etf-30wma-slope")
    L.append("date: 2026-09-21")
    L.append(f"verdict: {v}")
    L.append("criteria_version: research-only")
    L.append('conditions: ["사전등록 f87b550 그대로", "SPY·QQQ·IWM·EFA·EEM 주봉 30주 SMA 10주 기울기>0", "TRAIN ~2010-12 / VALID 2011~2017 / TEST 2018~", "난수 바닥선 = 상태열 순환이동 1,000회"]')
    L.append(f"reason: >-\n  스크립트가 계산한 판정({v}). INFORMATION = TRAIN S >= 난수 바닥선(95p) 그리고 VALID·TEST S > 0.")
    L.append("---\n")
    L.append("# 미국 ETF 30주선 기울기 — 결과 (사전등록 f87b550)\n")
    L.append("이 문서의 수치는 `us_etf_30wma_slope.py` 가 계산해 그대로 옮긴 값이다(수기 입력 없음). 조건·기간·판정은 사전등록을 따랐고 결과를 보고 바꾸지 않았다.\n")
    L.append("## 1. 판정\n")
    L.append(f"**{v}** — INFORMATION={res['verdict_parts']['information']} · ECONOMIC={res['verdict_parts']['economic']} · ROBUST={res['verdict_parts']['robust']}\n")
    L.append("| 항목 | 값 |\n|---|---|")
    L.append(f"| TRAIN S (5종 균등평균, 다음 주 수익 ON−OFF) | {f(res['S']['TRAIN'], pct=True)} |")
    L.append(f"| 난수 바닥선 95p (TRAIN, 순환이동 {res['n_perm']}회, seed {res['seed']}) | {f(res['baseline95_train'], pct=True)} (난수 평균 {f(res['null_train_mean'], pct=True)}) |")
    L.append(f"| VALID S | {f(res['S']['VALID'], pct=True)} |")
    L.append(f"| TEST S | {f(res['S']['TEST'], pct=True)} |")
    L.append(f"| VALID+TEST S | {f(res['S']['VT'], pct=True)} |")
    L.append(f"| VALID+TEST 전략 net Sharpe − 매수보유 Sharpe, 균등평균 (편도 5bp) | {f(res['econ']['cost1'])} |")
    L.append(f"| 같은 값 (편도 10bp) | {f(res['econ']['cost2'])} |")
    L.append(f"| VALID+TEST 에서 S>0 인 ETF | {res['vt_positive_etfs']['positive']} / {res['vt_positive_etfs']['of']} |\n")
    L.append("## 2. ETF 별 S 와 ON/OFF 주 수\n")
    L.append("| ETF | 창 | S | ON 주 | OFF 주 |\n|---|---|---|---|---|")
    for s in ETFS:
        for w in WINDOWS + ["VT"]:
            x = P[w][s]
            note = "" if not np.isnan(x["S"]) else " (제외: <20주)"
            L.append(f"| {s} | {w} | {f(x['S'], pct=True)}{note} | {x['n_on']} | {x['n_off']} |")
    L.append("")
    L.append("각 창에서 S 를 만든 ETF 수: " + ", ".join(f"{w} {res['etfs_used'][w]}" for w in WINDOWS + ["VT"]) + "\n")
    L.append("### ETF 별 Sharpe 차이 (VALID+TEST, 전략 net − 매수보유)\n")
    L.append("| ETF | 편도 5bp | 편도 10bp |\n|---|---|---|")
    for s in ETFS:
        L.append(f"| {s} | {f(res['econ']['cost1_per_etf'][s])} | {f(res['econ']['cost2_per_etf'][s])} |")
    L.append("\nSharpe = 주간 수익 평균 / 표준편차(ddof=1) × √52, 무위험수익 0 (사전등록에 정의가 없어 구현 시 정한 값 — §5 참고).\n")
    L.append("## 3. 기록 전용 (판정에 안 씀)\n")
    L.append("### R1 수준 셀 — 종가 > 30주선 vs 아님, 다음 주 수익 차\n")
    L.append("| 창 | S(수준) | ETF 수 |\n|---|---|---|")
    for w in WINDOWS:
        x = R["R1_level"][w]
        L.append(f"| {w} | {f(x['S'], pct=True)} | {x['etfs_used']} |")
    L.append("\n### R2 2×2 — 기울기 × 수준 (ETF-주 풀링, 다음 주 평균 수익 / 주 수)\n")
    L.append("| 창 | slope+/above | slope+/below | slope−/above | slope−/below |\n|---|---|---|---|---|")
    for w in WINDOWS + ["ALL"]:
        c = R["R2_2x2"][w]
        cells = " | ".join(f"{f(c[k]['mean_next_week'], pct=True)} / {c[k]['weeks']}" for k in ("slope+/above", "slope+/below", "slope-/above", "slope-/below"))
        L.append(f"| {w} | {cells} |")
    L.append("\n### R3 한국 대조 — ^KS11 같은 규칙\n")
    L.append("| 창 | S | ON 주 | OFF 주 |\n|---|---|---|---|")
    for w in WINDOWS + ["VT"]:
        x = R["R3_KS11"][w]
        L.append(f"| {w} | {f(x['S'], pct=True)} | {x['n_on']} | {x['n_off']} |")
    L.append("\n### R4 13주 forward (구간 겹침 — 참고용)\n")
    L.append("| 창 | S13 | ETF 수 |\n|---|---|---|")
    for w in WINDOWS:
        x = R["R4_fwd13_overlap"][w]
        L.append(f"| {w} | {f(x['S13'], pct=True)} | {x['etfs_used']} |")
    L.append("\n### R5 연도별 S (ETF 균등평균)\n")
    L.append("| 연도 | S | ETF 수 |\n|---|---|---|")
    for y, x in R["R5_yearly_S"].items():
        L.append(f"| {y} | {f(x['S'], pct=True)} | {x['etfs_used']} |")
    pos = sum(1 for x in R["R5_yearly_S"].values() if not np.isnan(x["S"]) and x["S"] > 0)
    tot = sum(1 for x in R["R5_yearly_S"].values() if not np.isnan(x["S"]))
    L.append(f"\nS>0 인 해: {pos} / {tot}\n")
    L.append("### R6 전략 vs 매수보유 (VALID+TEST, 비용 편도 5bp)\n")
    L.append("| ETF | 전략 CAGR | 전략 MDD | 시장 노출 | 매수보유 CAGR | 매수보유 MDD | 주 수 |\n|---|---|---|---|---|---|---|")
    for s in ETFS:
        x = R["R6_strategy_vs_bh_VT"][s]
        L.append(f"| {s} | {f(x['strategy_net']['CAGR'], pct=True)} | {f(x['strategy_net']['MDD'], pct=True)} | {f(x['exposure'], pct=True)} | {f(x['buy_hold']['CAGR'], pct=True)} | {f(x['buy_hold']['MDD'], pct=True)} | {x['weeks']} |")
    L.append("\n## 4. 데이터\n")
    L.append("| 심볼 | 일봉 첫날 | 일봉 끝 | 주봉 수 | 신호 주 첫날 | 신호 주 끝 |\n|---|---|---|---|---|---|")
    for s, m in meta.items():
        L.append(f"| {s} | {m['first']} | {m['last']} | {m['weeks']} | {m['sig_first']} | {m['sig_last']} |")
    L.append("")
    L.append("## 5. 사전등록 대조 (구현 중 확인한 것)\n")
    L.append(f"- **수정주가**: yfinance `auto_adjust=True`(배당 포함), 종료 {LAST_DAY} — 사전등록과 일치. 다만 yfinance 는 받을 때마다 과거 수정값이 미세하게 바뀔 수 있어 첫 실행 결과를 `.cache/us_etf_30wma/` 에 동결했다(재현은 캐시 기준).")
    L.append("- **저장소 보유 데이터와 불일치**: `data/leveraged-etf/QQQ.parquet` 는 **비수정가**(배당·분할 열이 분리)이고 2026-09-11 에서 끝난다. SPY·IWM·EFA·EEM 은 저장소에 없다. 사전등록이 yfinance 수정주가를 지정했으므로 5종 모두 새로 받아 썼고 저장소 QQQ 는 쓰지 않았다.")
    L.append("- **주 수익 기준**: 주 t 종가 → 주 t+1 종가(종가-종가), 신호는 주 t 종가로 결정 — 사전등록 §1 과 일치. 금요일 휴장 주는 그 주의 마지막 거래일 종가를 쓴다.")
    L.append(f"- **워밍업**: 사전등록대로 첫 {WARM}주를 버렸다. 기울기가 계산되는 가장 이른 주는 40번째(인덱스 39)라 실제로는 1주를 더 버린 셈이다(사전등록 문구를 그대로 따른 결과).")
    L.append("- **Sharpe 정의**: 사전등록에 연율화·무위험수익 정의가 없다. 주간 수익 평균/표준편차×√52, 무위험 0 으로 구현했다(현금 수익 0 가정과 일관). 다른 정의로 바꾸면 ECONOMIC 판정이 달라질 수 있다.")
    L.append("- **비용**: 상태가 바뀌는 주마다 편도 5bp(스트레스 10bp)를 그 신호 주의 수익에서 뺐다. 시작은 현금에서. 매수보유는 비용 없음.")
    L.append("- **난수 바닥선**: ETF 별 독립 오프셋(52..n−52, n = 워밍업 제거 후 신호 주 수), 1,000회, 창 TRAIN 의 S 의 95번째 백분위. 이동은 전체 신호열에 적용하고 창은 날짜 기준으로 자른다.")
    L.append("- 사전등록에 없는 지표는 추가하지 않았다. CAGR·MDD·시장 노출은 사전등록 R6 에 명시된 기록 전용 항목이다.\n")
    L.append("## 6. 한계 (사전등록 §6 재확인)\n")
    L.append("- ETF 5종은 같은 시장에서 움직여 독립 표본 5개가 아니다. 통과 여부와 무관하게 '5개 독립 검증'으로 읽지 않는다.")
    L.append("- 이 문서의 어떤 판정도 채택이 아니다. 최대 결론은 forward 관측(그림자) 후보이며 실주문은 범위 밖이다.")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 셀프테스트
def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    # 1 주봉: 금요일 기준 주 마지막 거래일 (금요일 휴장 주는 목요일 종가)
    idx = pd.to_datetime(["2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10",
                          "2020-01-13", "2020-01-14", "2020-01-15", "2020-01-16"])
    s = pd.Series(range(len(idx)), index=idx, dtype=float)
    w = to_weekly(s)
    check("주봉 마지막 거래일 종가", list(w.values) == [4.0, 8.0])

    # 2 기울기 방향: 상승 램프 = 전부 ON, 하락 램프 = 전부 OFF
    up = pd.Series(np.linspace(100, 300, 200), index=pd.date_range("2000-01-07", periods=200, freq="W-FRI"))
    dn = pd.Series(np.linspace(300, 100, 200), index=up.index)
    check("상승 램프 ON", build(up).on.all())
    check("하락 램프 OFF", (~build(dn).on).all())
    check("워밍업 40주 제거", len(build(up)) == 200 - WARM - 1)

    # 3 룩어헤드 없음: t 이후 가격을 바꿔도 ON(t) 불변
    rng = np.random.default_rng(1)
    p = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))), index=pd.date_range("2000-01-07", periods=300, freq="W-FRI"))
    full = build(p)
    p2 = p.copy()
    p2.iloc[200:] *= 3
    alt = build(p2)
    common = full.index[full.index < p.index[200]]
    check("ON(t) 는 미래 가격에 무관", (full.loc[common, "on"] == alt.loc[common, "on"]).all())

    # 4 spread 값·제외 규칙
    r = np.array([0.02] * 30 + [0.00] * 30)
    st = np.array([True] * 30 + [False] * 30)
    m = np.ones(60, bool)
    check("spread 평균 차", abs(spread_one(r, st, m) - 0.02) < 1e-12)
    check("20주 미만이면 제외(nan)", np.isnan(spread_one(r, np.array([True] * 10 + [False] * 50), m)))

    # 5 순환이동: ON 개수 보존, 신호 없는 데이터에서 바닥선이 관측을 자주 넘지 않는다
    on = rng.random(400) > 0.4
    check("순환이동은 ON 개수 보존", np.roll(on, 77).sum() == on.sum())
    fp = 0
    for k in range(20):
        r_ = np.random.default_rng(100 + k)
        frames = {}
        for j in range(3):
            idx_ = pd.date_range("1999-01-01", periods=600, freq="W-FRI")
            ret = r_.normal(0.002, 0.02, 600)
            state = np.repeat(r_.random(60) > 0.4, 10)  # 지속적인 상태(자기상관)
            frames[str(j)] = pd.DataFrame({"r1": ret, "on": state}, index=idx_)
        base, _ = null_baseline(frames, "TRAIN", np.random.default_rng(k), n_perm=200)
        obs = pooled([spread_one(d.r1.to_numpy(), d.on.to_numpy(), win_mask(d.index, "TRAIN")) for d in frames.values()])[0]
        fp += obs >= base
    check(f"신호 없는 데이터 오탐률 ≤ 25% ({fp}/20)", fp <= 5)

    # 6 비용: 매주 뒤집히는 상태는 전환마다 비용, 항상 ON 은 진입 1회만
    d = pd.DataFrame({"r1": [0.0] * 6, "pos": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]})
    check("전환 비용 6회", abs(strategy_returns(d, 0.001).sum() + 6 * 0.001) < 1e-12)
    d2 = pd.DataFrame({"r1": [0.01] * 5, "pos": [1.0] * 5})
    check("항상 ON = 진입비용 1회만", abs(strategy_returns(d2, 0.001).sum() - (0.05 - 0.001)) < 1e-12)

    # 7 성과 함수
    check("CAGR", abs(cagr([0.01] * 52) - (1.01 ** 52 - 1)) < 1e-12)
    check("MDD", abs(mdd([0.1, -0.5, 0.2]) - (-0.5)) < 1e-12)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    frames, meta = {}, {}
    for s in ETFS + [REF]:
        c = load_daily(s, a.refresh)
        wk = to_weekly(c)
        d = build(wk)
        meta[s] = {"first": str(c.index[0].date()), "last": str(c.index[-1].date()), "weeks": len(wk),
                   "sig_first": str(d.index[0].date()), "sig_last": str(d.index[-1].date())}
        if s == REF:
            ref_frame = d
        else:
            frames[s] = d
    res = run(frames, ref_frame)
    res["data"] = meta
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res, res["data"]), encoding="utf-8")
    print("verdict:", res["verdict"], res["verdict_parts"])
    print("S:", {k: round(v, 5) for k, v in res["S"].items()}, "baseline95:", round(res["baseline95_train"], 5))
    print("wrote", OUT.with_suffix(".md"))


if __name__ == "__main__":
    main()
