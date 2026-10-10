"""시기 분리·반도체 쏠림 진단 (2026-10-10, 진단 전용 — 판정·매매 불사용).

1) 연도별 시장: 시총가중/등가중, 반도체 포함·제외, 반도체 시총 비중 (krx-daily-ext 일별)
2) 팩터 상위 10% − 유동 종목 등가중, 월평균 초과(%p): 2016~23 / 2024 / 2025 / 2026, 반도체 포함·제외 (factor-panel)
3) 규모 장세: 월별 시총 상위 10% − 전체 등가중(반도체 포함·제외)

반도체 = 테마 트리 'AI·반도체' ∪ 업종 '반도체 제조업'. 지금 알고 만든 목록이라 진단에만 쓴다(사후 필터).
네트워크 없음. 실행: python research/strategy-lab/diag_regime_semis.py [--monthly]
--monthly 는 3) 규모 장세(월별 큰 종목 − 전체)만 — 월간 점검용. 먼저 collect_krx_daily_ext.py 로 이번 달을 받는다.
"""
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'research/strategy-lab/data'
FACTORS = {'저PBR': ('pbr', True), '이익수익률': ('earnings_yield', False), '영업이익률': ('op_margin', False),
           'ROE': ('roe', False), '12개월 모멘텀': ('mom12m_skip1m', False), '6개월 모멘텀': ('mom6m', False),
           '저변동': ('rv60_pct', True), '거래대금 큰': ('dv20', False), '외국인 순매수': ('foreign_nb20_ratio', False)}


def semi_set(panel):
    themes = json.load(open(ROOT / 'config/themeTree.json', encoding='utf-8'))['themes']
    ai = {x['t'] for g in themes['AI·반도체'].values() for x in g}
    return ai | set(panel.loc[panel.sector == '반도체 제조업', 'ticker'])


def daily(semi):
    d = pd.concat(pd.read_parquet(f, columns=['BAS_DD', 'ISU_CD', 'FLUC_RT', 'MKTCAP'])
                  for f in sorted(glob.glob(str(D / 'krx-daily-ext/*.parquet'))))
    d['dt'] = pd.to_datetime(d.BAS_DD)
    d = d.sort_values(['ISU_CD', 'dt'])
    d['r'] = pd.to_numeric(d.FLUC_RT, errors='coerce') / 100
    d['w'] = d.groupby('ISU_CD').MKTCAP.shift(1)  # 전일 시총 가중
    d = d.dropna(subset=['r', 'w'])
    d = d[(d.w > 0) & (d.r.abs() < 0.35)]
    d['s'] = d.ISU_CD.isin(semi)
    return d


def size_regime(d, months=24):
    """월별 '큰 종목 − 전체' 등가중 차(%p). 큰 종목 = 전일 시총 상위 10%.
    PBR 결합은 거래대금 하위 21%(중앙) 소형주 전략이라, 이 값이 크게 양(+)인 달의 PBR 부진은 장세 역풍으로 읽는다."""
    d = d.assign(big=d.groupby('dt').w.rank(pct=True) >= 0.9)
    x = d[~d.s]
    g = pd.DataFrame({'큰−전체': d[d.big].groupby('dt').r.mean() - d.groupby('dt').r.mean(),
                      '반도체 제외 큰−전체': x[x.big].groupby('dt').r.mean() - x.groupby('dt').r.mean()})
    m = g.groupby(g.index.to_period('M')).sum() * 100  # ponytail: 일별 차의 합 ≈ 월 차, 복리 오차는 수 bp
    return m.tail(months).round(2)


def market(d):
    d['rw'] = d.r * d.w
    x = d.assign(rw_ex=d.rw.where(~d.s, 0), w_ex=d.w.where(~d.s, 0), r_ex=d.r.where(~d.s), w_s=d.w.where(d.s, 0))
    g = x.groupby('dt').agg(rw=('rw', 'sum'), w=('w', 'sum'), rw_ex=('rw_ex', 'sum'), w_ex=('w_ex', 'sum'),
                            ew=('r', 'mean'), ew_ex=('r_ex', 'mean'), w_s=('w_s', 'sum'))
    df = pd.DataFrame({'시총가중': g.rw / g.w, '반도체제외 시총가중': g.rw_ex / g.w_ex,
                       '등가중': g.ew, '반도체제외 등가중': g.ew_ex})
    comp = lambda s: (1 + s).prod() - 1
    out = df.groupby(df.index.year).agg(comp)
    out['반도체 시총비중(연말)'] = (g.w_s / g.w).groupby(g.index.year).last()
    yr = d.groupby([d.dt.dt.year, 'ISU_CD']).r.apply(comp).reset_index()
    yr = yr[~yr.ISU_CD.isin(set(d.ISU_CD[d.s]))]
    out['반도체제외 종목 중앙값'] = yr.groupby('dt').r.median()
    out['반도체제외 상승비율'] = yr.groupby('dt').r.apply(lambda s: (s > 0).mean())
    return (out * 100).round(1)


def factor_excess(p):
    rows = {}
    for nm, (c, asc) in FACTORS.items():
        def top_minus_ew(x):
            x = x.dropna(subset=[c])
            if c == 'pbr':
                x = x[x.pbr > 0]
            if len(x) < 50:
                return float('nan')
            k = max(int(len(x) * 0.1), 5)
            top = x.nsmallest(k, c) if asc else x.nlargest(k, c)
            return top.fwd1m.mean() - x.fwd1m.mean()
        rows[nm] = p.groupby('date').apply(top_minus_ew, include_groups=False)
    df = pd.DataFrame(rows)
    y = pd.to_datetime(df.index).year
    buckets = {'2016~23': y <= 2023, '2024': y == 2024, '2025': y == 2025, '2026': y == 2026}
    return pd.DataFrame({k: df[m].mean() for k, m in buckets.items()}) * 100


def main():
    p = pd.read_parquet(D / 'factor-panel/kr-monthly-v1.parquet')
    semi = semi_set(p)
    d = daily(semi)
    print(f'반도체 {len(semi)}종목 · 일별 자료 ~{d.dt.max():%Y-%m-%d}\n\n[규모 장세: 큰 종목 − 전체, 월 %p]')
    print(size_regime(d).to_string())
    if sys.argv[1:] == ['--monthly']:
        return
    print('\n[시장, %]')
    print(market(d).to_string())
    p = p[p.liquid == True].dropna(subset=['fwd1m'])  # noqa: E712
    full, ex = factor_excess(p), factor_excess(p[~p.ticker.isin(semi)])
    print(f'\n[팩터 상위 10% 월평균 초과, %p] 패널 {p.date.min()} ~ {p.date.max()}')
    print(pd.concat({'포함': full, '반도체제외': ex}, axis=1).round(2).to_string())


if __name__ == '__main__':
    main()
