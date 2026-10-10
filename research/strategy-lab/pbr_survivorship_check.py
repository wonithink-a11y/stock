"""PBR 생존편향 점검 — 사전등록 findings/pbr-survivorship-check-preregistration-2026-10.md (380f9d37) 그대로.

같은 저PBR 30종목 규칙을 ALL(그 시점 전 종목, 폐지 포함) 과 SURV(오늘 상장 명단만) 에 돌려 차이를 잰다.
네트워크 없음. 실행: python research/strategy-lab/pbr_survivorship_check.py [--selftest]
산출: findings/pbr-survivorship-check-results-2026-10.{md,json}
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / 'research/strategy-lab'
D = LAB / 'data'
OUT = LAB / 'findings/pbr-survivorship-check-results-2026-10'
N_PICK, COST, DV_MIN, DV_WIN = 30, 0.00335, 1e8, 20


def period_of(d):
    return 'TRAIN' if d <= '2022-06-30' else 'VALID' if d <= '2024-01-01' else 'TEST'


def regime_of(d):
    return '2016~23' if d[:4] <= '2023' else '2024' if d[:4] == '2024' else '2025~'


def stats(r):
    r = pd.Series(r, dtype=float)
    if len(r) == 0:
        return {}
    eq = (1 + r).cumprod()
    return {'cagr': eq.iloc[-1] ** (12 / len(r)) - 1, 'sharpe': r.mean() / r.std() * 12 ** 0.5 if r.std() > 0 else np.nan,
            'mdd': (eq / eq.cummax() - 1).min(), 'months': len(r)}


def load():
    d = pd.concat(pd.read_parquet(f, columns=['BAS_DD', 'ISU_CD', 'ISU_NM', 'FLUC_RT', 'ACC_TRDVAL'])
                  for f in sorted(glob.glob(str(D / 'krx-daily-ext/*.parquet'))))
    d['dt'] = pd.to_datetime(d.BAS_DD).dt.strftime('%Y-%m-%d')
    d = d.drop_duplicates(['dt', 'ISU_CD'])
    r = d.pivot(index='dt', columns='ISU_CD', values='FLUC_RT').apply(pd.to_numeric, errors='coerce') / 100
    tv = d.pivot(index='dt', columns='ISU_CD', values='ACC_TRDVAL').apply(pd.to_numeric, errors='coerce')
    names = d.groupby('ISU_CD').ISU_NM.last()
    pbr = pd.concat(pd.read_parquet(f, columns=['date', 'ticker', 'PBR'])
                    for f in sorted(glob.glob(str(D / 'krx-pbr-history/pbr/*.parquet'))) if Path(f).stem >= '2016-02')
    cur = {json.loads(l)['ticker'] for l in open(ROOT / 'data/backfill/universe/a1a/current.jsonl', encoding='utf-8')}
    dl = {json.loads(l)['ticker'] for l in open(ROOT / 'data/backfill/universe/a1b/delisted.jsonl', encoding='utf-8')}
    return r, tv, names, pbr, cur, dl


def run(r, tv, names, pbr, cur, dl):
    dates = list(r.index)
    pos = {x: i for i, x in enumerate(dates)}
    logcum = np.log1p(r.fillna(0)).cumsum()          # 정지일 0, 폐지 뒤 0(현금)
    traded = r.notna()
    dv20 = tv.fillna(0).rolling(DV_WIN, min_periods=DV_WIN).mean()
    bad_name = names.str.contains('스팩|기업인수목적', na=False)
    signals = sorted(d for d in pbr.date.unique() if d in pos)
    rows, prev = [], {'ALL': set(), 'SURV': set(), 'ALL10': set(), 'SURV10': set()}
    for s, s_next in zip(signals, signals[1:] + [None]):
        i = pos[s] + 1
        j = pos[s_next] + 1 if s_next else len(dates) - 1
        if i >= len(dates) or j >= len(dates) or j <= i:
            continue
        snap = pbr[(pbr.date == s) & (pbr.PBR > 0)].set_index('ticker').PBR
        tk = [t for t in snap.index if t in r.columns and t.endswith('0') and not bad_name.get(t, True)
              and traded.at[s, t] and dv20.at[s, t] >= DV_MIN]
        ret = np.exp(logcum.iloc[j][tk] - logcum.iloc[i][tk]) - 1
        for uni, members in (('ALL', tk), ('SURV', [t for t in tk if t in cur])):
            p = snap[members].sort_values(kind='stable')
            for name, k in ((uni, N_PICK), (uni + '10', max(len(p) // 10, 1))):
                pick = list(p.index[:k])
                if not pick:
                    continue
                new = len(set(pick) - prev[name]) / len(pick)
                prev[name] = set(pick)
                gross = ret[pick].mean()
                rows.append({'signal': s, 'universe': name, 'n_universe': len(members), 'gross': gross,
                             'net': gross - new * COST, 'ew': ret[members].mean(), 'turnover': new,
                             'delisted_picked': [t for t in pick if t in dl],
                             'delisted_ret': float(ret[[t for t in pick if t in dl]].mean()) if any(t in dl for t in pick) else None})
    return pd.DataFrame(rows), float(np.nanmax(r.values)), float(np.nanmin(r.values))


def summarize(df):
    out = {}
    for u, g in df.groupby('universe'):
        o = {'strategy': stats(g.net), 'ew': stats(g.ew)}
        for key, f in (('period', period_of), ('regime', regime_of), ('year', lambda d: d[:4])):
            o[key] = {k: {'net_cagr': stats(x.net)['cagr'], 'ew_cagr': stats(x.ew)['cagr']} for k, x in g.groupby(g.signal.map(f))}
        o['avg_universe'] = g.n_universe.mean()
        o['avg_turnover'] = g.turnover.mean()
        dp = [t for lst in g.delisted_picked for t in lst]
        o['delisted_slots'] = len(dp)
        o['delisted_tickers'] = len(set(dp))
        o['delisted_slot_ret_mean'] = float(np.nanmean([x for x in g.delisted_ret if x is not None])) if dp else None
        out[u] = o
    a, s = out['ALL']['strategy']['cagr'], out['SURV']['strategy']['cagr']
    delta = s - a
    beats = a > out['ALL']['ew']['cagr']
    verdict = '편향 작음' if delta < 0.01 and beats else '편향 큼' if delta >= 0.02 or not beats else '중간'
    return out, delta, beats, verdict


def pct(x):
    return '' if x is None or (isinstance(x, float) and np.isnan(x)) else f'{x * 100:+.2f}%'


def write(out, delta, beats, verdict, rmax, rmin, df):
    A, S = out['ALL'], out['SURV']
    reason = (f"편향 점검(신호·경제성 판정 아님). 비용 후 연복리 SURV {pct(S['strategy']['cagr'])} vs ALL {pct(A['strategy']['cagr'])} → "
              f"Δ {delta * 100:+.2f}%p · ALL 전략 {'>' if beats else '≤'} ALL 등가중({pct(A['ew']['cagr'])}) → {verdict}. (스크립트 판정)")
    L = ['---', 'track: kr', 'factor: pbr-survivorship-check', 'date: 2026-10-10', f'verdict: {verdict}',
         'criteria_version: research-only (pbr-survivorship-check-preregistration-2026-10)',
         'reason: >-', f'  {reason}', '---', '', '# PBR 생존편향 점검 — 결과', '',
         f'사전등록 380f9d37 그대로. 신호 {df.signal.nunique()}개월({df.signal.min()} ~ {df.signal.max()}). 일별 등락률 범위 {rmin * 100:.1f}% ~ {rmax * 100:+.1f}%(필터 없음).', '',
         '| 칸 | 전략 연복리(비용 후) | 샤프 | MDD | 등가중 연복리 | 초과 | 평균 대상 수 | 월 교체 | 고른 폐지 종목(슬롯) | 폐지 슬롯 평균 월수익 |',
         '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for u in ('SURV', 'ALL', 'SURV10', 'ALL10'):
        o = out[u]
        L.append(f"| {u} | {pct(o['strategy']['cagr'])} | {o['strategy']['sharpe']:.2f} | {pct(o['strategy']['mdd'])} | {pct(o['ew']['cagr'])} | "
                 f"{(o['strategy']['cagr'] - o['ew']['cagr']) * 100:+.2f}%p | {o['avg_universe']:.0f} | {o['avg_turnover'] * 100:.0f}% | "
                 f"{o['delisted_tickers']}({o['delisted_slots']}) | {pct(o['delisted_slot_ret_mean'])} |")
    L += ['', f'**판정 {verdict}** — Δ(SURV − ALL, 30종목) = {delta * 100:+.2f}%p (작음 < 1%p 그리고 ALL 이 등가중을 이김 · 큼 ≥ 2%p 또는 못 이김).', '',
          '## 기록 (판정 불사용)', '', '| 구간 | SURV 전략 | ALL 전략 | Δ | SURV 등가중 | ALL 등가중 |', '|---|---:|---:|---:|---:|---:|']
    for key in ('period', 'regime', 'year'):
        for k in sorted(A[key]):
            a, s = A[key][k], S[key].get(k, {})
            L.append(f"| {k} | {pct(s.get('net_cagr'))} | {pct(a['net_cagr'])} | {(s.get('net_cagr', np.nan) - a['net_cagr']) * 100:+.2f}%p | "
                     f"{pct(s.get('ew_cagr'))} | {pct(a['ew_cagr'])} |")
    L += ['', '한계: 운용 전략(DART 재무 PBR · 탈락 · MAX 제외)의 재현이 아니다 — 같은 단순 규칙에서 유니버스만 바꾼 차이다. 폐지 종목은 마지막 거래가로 현금화',
          '(정리매매 가격까지는 들어 있다). 이 결과로 운용 규칙을 바꾸는 것은 별도 🔴 결정.']
    OUT.with_suffix('.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
    OUT.with_suffix('.json').write_text(json.dumps({'verdict': verdict, 'delta': delta, 'all_beats_ew': beats, 'summary': out},
                                                   ensure_ascii=False, indent=1, default=float), encoding='utf-8')


def selftest():
    dates = [f'2020-01-0{i}' for i in range(1, 8)]
    r = pd.DataFrame({'A00000': [0, 0, 0.1, 0.1, 0, 0, 0], 'B00000': [0, 0, -0.5, np.nan, np.nan, np.nan, np.nan]}, index=dates)
    tv = pd.DataFrame(2e8, index=dates, columns=r.columns)
    pbr = pd.DataFrame({'date': ['2020-01-01', '2020-01-01', '2020-01-04'], 'ticker': ['A00000', 'B00000', 'A00000'], 'PBR': [0.5, 0.3, 0.5]})
    import pbr_survivorship_check as m
    m.N_PICK, m.DV_WIN = 1, 1
    df, _, _ = m.run(r, tv, pd.Series({'A00000': 'a', 'B00000': 'b'}), pbr, {'A00000'}, {'B00000'})
    g = df[(df.signal == '2020-01-01') & (df.universe == 'ALL')].iloc[0]
    assert abs(g.gross - (-0.5)) < 1e-9, g            # 폐지 종목 B: 진입 다음날 −50% 뒤 현금 — 손실이 남는다
    s = df[(df.signal == '2020-01-01') & (df.universe == 'SURV')].iloc[0]
    assert abs(s.gross - (1.1 * 1.1 - 1)) < 1e-9, s   # SURV 에는 B 가 없다
    print('selftest ok')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.path.insert(0, str(LAB))
        selftest()
        sys.exit()
    data = load()
    df, rmax, rmin = run(*data)
    out, delta, beats, verdict = summarize(df)
    write(out, delta, beats, verdict, rmax, rmin, df)
    print(verdict, f'delta {delta * 100:+.2f}%p', '->', OUT.with_suffix('.md'))
