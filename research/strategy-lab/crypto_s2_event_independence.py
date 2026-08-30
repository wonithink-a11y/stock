"""Step 7B — S2 Squeeze+Vol 이벤트 독립성 검증.

전략 코드/파라미터/비용 모델/rule 변경 없이 TEST 성과의
이벤트·종목 집중도를 분석한다. run_backtest 시그널 필터 래퍼만 사용하고
엔진·모듈은 그대로 재사용한다.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, '.')
import run_community_strategy_validation as R
from engine.execution.executor import CostModel

SYM = 'bb_squeeze_vol_v1'
UNIVERSE = R.UNIVERSE
OUT_MD = Path('findings/crypto-s2-event-independence-2026-08.md')

RES = json.load(open('findings/crypto-community-strategies/results.json', encoding='utf-8'))
SPLITS = {k: tuple(pd.Timestamp(x) for x in v) for k, v in RES['splits_daily'].items()}
COST = CostModel(R.BASE_ENTRY, R.BASE_EXIT, R.BASE_SLIP)

mod = R.load_strategy_module(SYM)
bars = R.load_bars('D')
feats = {s: mod.compute_features_main(bars[s]) for s in UNIVERSE}
close_lk = R.build_close_lookup(bars)


def make_mod_excluding(cal, excluded_dates):
    """generate_signals를 감싸 order_date(=진입일)가 excluded인 시그널만 제외."""
    class W:
        pass
    w = W()
    w.compute_features_main = mod.compute_features_main
    w.risk_spec_for_main = mod.risk_spec_for_main
    w.PARAMS = mod.PARAMS

    def gen(symbol, feats_):
        out = []
        for sig in mod.generate_signals_main(symbol, feats_):
            order_date = cal.next_session(pd.Timestamp(sig.signal_date))
            if order_date in excluded_dates:
                continue
            out.append(sig)
        return out

    w.generate_signals_main = gen
    return w


def run(fn_set=None, symbols=None, wrap_cal=None, excluded=None):
    if wrap_cal is not None:
        m = make_mod_excluding(wrap_cal, excluded)
    else:
        m = mod
    syms = symbols if symbols is not None else UNIVERSE
    res = R.run_backtest(m, bars, feats, fn_set, close_lk, COST, syms)
    if res is None:
        return None, []
    metrics, trades = R.compute_metrics(res, 365, label_ts=False)
    return metrics, trades


L = []
def P(s=''):
    L.append(s)


P('# S2 Squeeze+Vol — 이벤트 독립성 검증 (Step 7B)')
P('')
P(f'- 대상: `{SYM}` · Daily · 기본 비용 · 유니버스 {len(UNIVERSE)}종목')
P(f'- 구간: TRAIN {SPLITS["TRAIN"][0].date()}~{SPLITS["TRAIN"][1].date()} / '
  f'VALID {SPLITS["VALID"][0].date()}~{SPLITS["VALID"][1].date()} / '
  f'TEST {SPLITS["TEST"][0].date()}~{SPLITS["TEST"][1].date()}')
P('- 방법: run_backtest의 시그널 생성만 래핑해 특정 진입일 시그널을 제거(leave-one-event-out), '
  '유니버스 축소로 특정 코인 제외(leave-one-asset-out). 전략 코드·파라미터·비용·rule 무변경.')

resp = {}
for split in ['TRAIN', 'VALID', 'TEST']:
    m, tr = run(fn_set=SPLITS[split])
    cal = R.AllDaysCalendar(sorted({
        ts for df in bars.values()
        for ts in df.index
        if SPLITS[split][0] <= ts <= SPLITS[split][1]}))
    resp[split] = {'metrics': m, 'trades': tr, 'cal': cal}
meta = resp

# 0) consistency: TEST baseline == stored
sm = RES['strategies'][f'{SYM}:D']['periods']['TEST']['metrics']
mt = meta['TEST']['metrics']
assert mt['tradeCount'] == sm['tradeCount'] == 8, (mt['tradeCount'], sm['tradeCount'])
assert abs(mt['cagr'] - sm['cagr']) < 1e-9 and abs(mt['sharpe_ann'] - sm['sharpe_ann']) < 1e-9

P('')
P('## 1. TEST event-date decomposition')
P('')
by_date = defaultdict(list)
for t in meta['TEST']['trades']:
    by_date[str(t['entry_date'])[:10]].append(t)
tot_pnl = sum(t['pnl'] for t in meta['TEST']['trades'])
P('| 진입일 | 종목 | 거래수 | 합산 NetPnL(M) | 전체 대비 기여 |')
P('|--------|------|-------|---------------|----------------|')
for dt in sorted(by_date):
    ts = by_date[dt]
    net = sum(t['pnl'] for t in ts)
    coins = ', '.join(sorted({t['symbol'][4:] for t in ts}))
    P(f"| {dt} | {coins} | {len(ts)} | {net/1e6:>9,.0f} | {net/tot_pnl*100:+.0f}% |")
P(f'| **합계** | | {len(meta["TEST"]["trades"])} | {tot_pnl/1e6:,.0f} | 100% |')
P('')

# 2) leave-one-event-out per entry date (TEST)
P('## 2. Leave-one-event-out (TEST) — 진입일 하나씩 제거')
P('')
P('| 제외 진입일 | Total Return | CAGR | Sharpe | MDD | Net PnL(M) |')
P('|-------------|-------------|------|--------|-----|------------|')
P(f"| (없음, baseline) | {mt['totalReturn']*100:+.2f}% | {mt['cagr']*100:+.2f}% | {mt['sharpe_ann']:+.2f} | {mt['maxDrawdown']*100:.2f}% | {tot_pnl/1e6:,.0f} |")
loo_event = {}
for dt in sorted(by_date):
    cal = meta['TEST']['cal']
    m, tr_rem = run(fn_set=SPLITS['TEST'], wrap_cal=cal, excluded={pd.Timestamp(dt)})
    net_rem = sum(t['pnl'] for t in tr_rem)
    loo_event[dt] = {'m': m, 'net': net_rem,
                     'cagr': m['cagr'], 'sharpe': m['sharpe_ann'], 'mdd': m['maxDrawdown']}
    P(f"| **{dt}** | {m['totalReturn']*100:+.2f}% | {m['cagr']*100:+.2f}% | {m['sharpe_ann']:+.2f} | {m['maxDrawdown']*100:.2f}% | {net_rem/1e6:,.0f} |")
P('')

# 3) leave-one-asset-out (TEST)
P('## 3. Leave-one-asset-out (TEST) — 코인 하나씩 제외')
P('')
m_all = meta['TEST']['metrics']
P('| 제외 코인 | Total Return | CAGR | Sharpe | MDD | Net PnL(M) | 거래수 |')
P('|-----------|-------------|------|--------|-----|------------|--------|')
P(f"| (없음, baseline) | {m_all['totalReturn']*100:+.2f}% | {m_all['cagr']*100:+.2f}% | {m_all['sharpe_ann']:+.2f} | {m_all['maxDrawdown']*100:.2f}% | {tot_pnl/1e6:,.0f} | {m_all['tradeCount']} |")
loo_asset = {}
for s in UNIVERSE:
    syms = [x for x in UNIVERSE if x != s]
    m, tr = run(fn_set=SPLITS['TEST'], symbols=syms)
    net = sum(t['pnl'] for t in tr)
    loo_asset[s] = {'m': m, 'net': net, 'trades': len(tr)}
    P(f"| {s[4:]} | {m['totalReturn']*100:+.2f}% | {m['cagr']*100:+.2f}% | {m['sharpe_ann']:+.2f} | {m['maxDrawdown']*100:.2f}% | {net/1e6:,.0f} | {m['tradeCount']} |")
P('')

# 4) cluster decomposition (TEST)
P('## 4. Cluster decomposition (TEST)')
P('')
P('- cluster = 같은 진입일에 2개 이상 코인이 동시 진입')
clusters = [(dt, ts) for dt, ts in by_date.items() if len(ts) >= 2]
singles = [(dt, ts) for dt, ts in by_date.items() if len(ts) == 1]
cl_net = sum(sum(t['pnl'] for t in ts) for _, ts in clusters)
si_net = sum(sum(t['pnl'] for t in ts) for _, ts in singles)
P(f'- 클러스터 수: {len(clusters)} ({", ".join(dt for dt, _ in clusters)})')
P(f'- 클러스터 합산 NetPnL: {cl_net/1e6:+,.0f}M (전체 {cl_net/tot_pnl*100:+.0f}%)')
P(f'- 단독 진입 거래일 수: {len(singles)} ({", ".join(dt for dt, _ in singles)})')
P(f'- 단독 진입 합산 NetPnL: {si_net/1e6:+,.0f}M (전체 {si_net/tot_pnl*100:+.0f}%)')
P('')
P('| cluster | 종목 | 거래수 | NetPnL(M) | 기여 |')
P('|---------|------|-------|-----------|------|')
for dt, ts in clusters:
    net = sum(t['pnl'] for t in ts)
    coins = ', '.join(sorted({t['symbol'][4:] for t in ts}))
    P(f"| {dt} | {coins} | {len(ts)} | {net/1e6:,.0f} | {net/tot_pnl*100:+.0f}% |")
P('')
win_detail = []
for t in meta['TEST']['trades']:
    win_detail.append((str(t['entry_date'])[:10], t['symbol'][4:], t['pnl']/1e6, len(by_date[str(t['entry_date'])[:10]])))
P('- 단독 진입 거래: ' + ', '.join(f"{d} {c} {n:+,.0f}M(단독)" for d, c, n, k in win_detail if k == 1))
P('')

# 5) market-wide move on entry dates (TEST)
P('## 5. S2 진입일의 시장 전체 움직임 (TEST)')
P('')
cal = meta['TEST']['cal']
def coin_ret(d0, d1):
    vals = []
    for s in UNIVERSE:
        df = bars[s]
        if d0 in df.index and d1 in df.index:
            vals.append(float(df.loc[d1, 'close']) / float(df.loc[d0, 'close']) - 1)
    return vals

P('| 진입일 | 7코인 당일 평균수익 (신호종가→진입일종가) | 7코인 양성 종목수/7 | 다음날 평균수익 | S2 해당일 진입 종목 |')
P('|--------|------------------------------------------|--------------------|----------------|--------------------|')
for dt in sorted(by_date):
    d_ts = pd.Timestamp(dt)
    prev = cal.days[cal.days.index(d_ts) - 1]
    nxt = cal.days[cal.days.index(d_ts) + 1] if cal.days.index(d_ts) + 1 < len(cal.days) else None
    ret_t = coin_ret(prev, d_ts)
    ret_n = coin_ret(d_ts, nxt) if nxt else []
    up = sum(1 for r in ret_t if r > 0)
    coins = ', '.join(sorted({t['symbol'][4:] for t in by_date[dt]}))
    avg_t = sum(ret_t) / len(ret_t) if ret_t else float('nan')
    avg_n = sum(ret_n) / len(ret_n) if ret_n else float('nan')
    P(f"| {dt} | {avg_t*100:+.2f}% | {up}/{len(ret_t)} | {avg_n*100:+.2f}% | {coins} |")
P('')

# 6) TRAIN/VALID/TEST event decomposition
P('## 6. TRAIN / VALID / TEST 동일 event decomposition')
P('')
P('| 구간 | 거래수 | 진입일수 | 클러스터수 | 최대 단일 진입일 기여(전체 대비) | 클러스터 NetPnL 기여 | 단독 진입 기여 |')
P('|------|--------|----------|-----------|----------------------------------|---------------------|----------------|')
split_extra = {}
for split in ['TRAIN', 'VALID', 'TEST']:
    m, tr = meta[split]['metrics'], meta[split]['trades']
    net = sum(t['pnl'] for t in tr)
    bd = defaultdict(list)
    for t in tr:
        bd[str(t['entry_date'])[:10]].append(t)
    if not bd:
        P(f"| {split} | 0 | - | - | - | - | - |")
        split_extra[split] = {'bd': bd, 'net': net}
        continue
    cl_dates = [dt for dt, ts in bd.items() if len(ts) >= 2]
    cl_net = sum(sum(t['pnl'] for t in bd[dt]) for dt in cl_dates)
    si_net = sum(sum(t['pnl'] for t in bd[dt]) for dt in bd if len(bd[dt]) == 1)
    top_dt = max(bd, key=lambda dt: abs(sum(t['pnl'] for t in bd[dt])))
    top_share = abs(sum(t['pnl'] for t in bd[top_dt])) / abs(net) if net else 0
    P(f"| {split} | {len(tr)} | {len(bd)} | {len(cl_dates)} | {top_dt} {top_share*100:+.0f}% | {cl_net/net*100:+.0f}% | {si_net/net*100:+.0f}% |")
    split_extra[split] = {'bd': bd, 'net': net, 'top_dt': top_dt}

# leave-one-event-out for TRAIN/VALID too (top contributor each)
P('')
P('### TRAIN / VALID leave-one-event-out (최대 기여 진입일 제거)')
P('')
P('| 구간 | 제외 | Total Return | CAGR | Sharpe | MDD | Net PnL(M) |')
P('|------|------|-------------|------|--------|-----|------------|')
for split in ['TRAIN', 'VALID']:
    if split not in split_extra or split not in meta:
        continue
    bd = split_extra[split]['bd']
    if not bd:
        continue
    cal = meta[split]['cal']
    base_m = meta[split]['metrics']
    for top in [split_extra[split]['top_dt']]:
        m, tr = run(fn_set=SPLITS[split], wrap_cal=cal, excluded={pd.Timestamp(top)})
        net = sum(t['pnl'] for t in tr)
        P(f"| {split} | {top} | {m['totalReturn']*100:+.2f}% | {m['cagr']*100:+.2f}% | {m['sharpe_ann']:+.2f} | {m['maxDrawdown']*100:.2f}% | {net/1e6:,.0f} |")
P('')

# 7) verdict
P('## 7. 최종 판정')
P('')
m08 = loo_event.get('2026-08-20')
m01 = loo_event.get('2026-01-06')
doje_net = sum(t['pnl'] for t in meta['TEST']['trades'] if t['symbol'] == 'KRW-DOGE')
idx = meta['TEST']['cal'].days
P(f'**(1) 2026-08-20 제거 시:** TotalReturn {m08["m"]["totalReturn"]*100:+.2f}% / CAGR {m08["cagr"]*100:+.2f}% / Sharpe {m08["sharpe"]:+.2f} / MDD {m08["mdd"]*100:.2f}% / NetPnL {m08["net"]/1e6:,.0f}M')
P(f'**(2) 2026-01-06 제거 시:** TotalReturn {m01["m"]["totalReturn"]*100:+.2f}% / CAGR {m01["cagr"]*100:+.2f}% / Sharpe {m01["sharpe"]:+.2f} / NetPnL {m01["net"]/1e6:,.0f}M')
P(f'**(3) DOGE(3월+8월 2건) 단독 종목 효과:** DOGE 2건 합산 {doje_net/1e6:+,.0f}M = 전체 순익의 {doje_net/tot_pnl*100:+.0f}%')
adu = loo_asset.get('KRW-DOGE')
if adu:
    P(f'**(4) DOGE 제거 시:** TotalReturn {adu["m"]["totalReturn"]*100:+.2f}% / CAGR {adu["m"]["cagr"]*100:+.2f}% / Sharpe {adu["m"]["sharpe_ann"]:+.2f} / NetPnL {adu["net"]/1e6:,.0f}M')
P('')
P('### 판정: **B. EVENT-CONCENTRATED** (C·D 한계 동반)')
P('')
P('- 2026-08-20 단일 이벤트(3건, +877M, 순익의 +190%) 제거 시 TEST 성과는 음(-)으로 반전 '
  '(위 (1) 결과) → **"2026-08-20을 제거해도 의미 있는 TEST 성과를 유지하는가?"에 대한 답은 NO**.')
P('- 수익은 전적으로 2개 클러스터(2026-01-06 손실클러스터 -378M, 2026-08-20 수익클러스터 +877M)와 '
  'DOGE 단독 1건(2026-03 TIME_EXIT, B&H와 동일 수익)이 결정. 독립 이벤트 수 4개 중 성과 원천은 사실상 1개.')
P('- 종목 측면에서도 DOGE 2건이 순익의 122%를 차지(ASSET-CONCENTRATED 측면 일부).')
P('- 표본 규모(8건)상 D(INCONCLUSIVE) 요소도 존재하나, 방향성이 일관되게 "단일 이벤트/단일 종목"으로 '
  '수렴하므로 B를 우선 판정.')
P('- 구조적 알파로 확정하려면 2026-08-20과 같은 다중 코인 동시 스퀴즈 이벤트가 미래/과거(TRAIN)에 '
  '독립적으로 반복되는지 TRAIN·VALID 및 추가 데이터로 확인 필요.')

Path(OUT_MD).write_text('\n'.join(L), encoding='utf-8')

# console summary
print('=== TEST 진행 ===')
print(f'baseline: CAGR={mt["cagr"]*100:.2f}% Sharpe={mt["sharpe_ann"]:.2f} NetPnL={tot_pnl/1e6:,.0f}M N={mt["tradeCount"]}')
for dt, v in loo_event.items():
    print(f'  -LOO {dt}: CAGR={v["cagr"]*100:+.2f}% Sharpe={v["sharpe"]:+.2f} NetPnL={v["net"]/1e6:+,.0f}M')
a = loo_asset['KRW-DOGE']
print(f'  -LOO DOGE: CAGR={a["m"]["cagr"]*100:.2f}% Sharpe={a["m"]["sharpe_ann"]:.2f} NetPnL={a["net"]/1e6:+,.0f}M')
print(f'DOGE 2건 = {doje_net/1e6:+,.0f}M ({doje_net/tot_pnl*100:+.0f}% of net)')
print(f'clusters: {len(clusters)} net={cl_net/1e6:+,.0f}M ({cl_net/tot_pnl*100:+.0f}%)')
print(f'singles: {len(singles)} net={si_net/1e6:+,.0f}M ({si_net/tot_pnl*100:+.0f}%)')
print('WROTE', OUT_MD)