"""업종 그룹별 A5 점수 IC forward 기록 (2026-10-25, 사용자 GO · 기록 전용 — 판정·매매 불사용).

질문: A5 점수(같은 날·같은 업종 그룹 안 순위)가 20일 뒤 수익을 얼마나 맞히는가, 약한 업종이 계속 약한가.
기준선(이미 본 구간, 판정 근거 아님): 2024~2026-10-02 날짜 평균 IC — 통신·네트워크 .155 … 바이오·헬스케어 .035 · 조선·해운·운송 −.002 · 전자부품·디스플레이 .053.
업종 간 차이는 표준오차 ≈0.04 안이라 순위를 믿지 않는다. 몇 달 뒤에도 같은 업종이 계속 약할 때만 새 사전등록 후보.
forward = 점수 날짜 > FREEZE(2026-10-02, A5 마지막 날짜) 이고 20일 수익이 실현된 행. 월간 점검에서 A5 증분(A2a 이후) 뒤 실행.
대상: ACTIVE·NORMAL·신뢰도≥60·20일 평균 거래대금 중앙값 ≥10억(krx-daily-ext 로컬). 업종 = config/sectorGroups.json(현재 KRX 업종명 기준).
실행: python research/strategy-lab/run_sector_ic_forward.py   (--baseline: 기준선만 다시 계산해 출력)
기록: reports/2026-10-sector-ic-forward/observations.jsonl (추적됨, 커밋한다)
"""
import glob
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FREEZE = '2026-10-02'
OUT = ROOT / 'reports/2026-10-sector-ic-forward/observations.jsonl'
MIN_N = 12   # 날짜·업종당 최소 종목수


def liquidity():
    px = pd.concat(pd.read_parquet(f, columns=['BAS_DD', 'ISU_CD', 'ACC_TRDVAL'])
                   for f in sorted(glob.glob(str(ROOT / 'research/strategy-lab/data/krx-daily-ext/*.parquet'))))
    px['dt'] = pd.to_datetime(px.BAS_DD)
    px = px.sort_values(['ISU_CD', 'dt'])
    px['dv20'] = px.groupby('ISU_CD').ACC_TRDVAL.transform(lambda s: s.rolling(20, min_periods=15).median())
    return px[['ISU_CD', 'dt', 'dv20']].rename(columns={'ISU_CD': 't'}).dropna().sort_values('dt')


def groups():
    sg = json.load(open(ROOT / 'config/sectorGroups.json', encoding='utf-8'))
    k2g = {k: g for g, ks in sg['groups'].items() for k in ks}
    out = {}
    for l in open(ROOT / 'data/backfill/universe/a1a/current.jsonl', encoding='utf-8'):
        o = json.loads(l)
        out[o['ticker']] = sg['tickerOverrides'].get(o['ticker']) or k2g.get(o.get('sector')) or '기타(미분류)'
    return out


def load(since):
    rows = []
    for p in sorted(glob.glob(str(ROOT / 'data/backfill/scores/20*.jsonl.gz'))):
        if int(Path(p).name[:4]) < int(since[:4]):
            continue
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            for l in f:
                o = json.loads(l)
                if '_meta' in o or o.get('listingStatus') != 'ACTIVE' or o.get('tradingState') != 'NORMAL' \
                        or (o.get('conf') or 0) < 60 or o.get('fin') is None or o['d'] < since:
                    continue
                if (o.get('fwdStatus') or {}).get('d20') == 'OK':
                    rows.append((o['d'], o['t'], o['fin'], o['fwd']['d20'] * 100))
    return pd.DataFrame(rows, columns=['d', 't', 's', 'r'])


def ic_by_group(df):
    res = {}
    for g, sub in df.groupby('grp'):
        ics = sub.groupby('dt').apply(lambda x: x.s.rank().corr(x.r.rank()) if len(x) >= MIN_N else np.nan, include_groups=False).dropna()
        res[g] = {'ic': round(float(ics.mean()), 4) if len(ics) else None, 'dates': int(len(ics))}
    return res


def main():
    baseline = '--baseline' in sys.argv
    df = load('2024-01-01' if baseline else FREEZE)
    if baseline:
        df = df[df.d <= FREEZE]
    else:
        df = df[df.d > FREEZE]
    asof = df.d.max() if len(df) else None
    if df.empty:
        print(f'forward 관측 없음 — {FREEZE} 이후 점수 날짜 중 20일 수익이 실현된 행이 아직 없다(A5 증분과 20거래일 경과 필요).')
        return
    df['dt'] = pd.to_datetime(df.d)
    df = pd.merge_asof(df.sort_values('dt'), liquidity(), on='dt', by='t', direction='backward', tolerance=pd.Timedelta(days=7))
    df = df[df.dv20 >= 1e9].copy()
    df['grp'] = df.t.map(groups()).fillna('기타(미분류)')
    res = ic_by_group(df)
    rec = {'asOf': asof, 'kind': 'baseline' if baseline else 'forward', 'nRows': int(len(df)), 'groups': res}
    for g, v in sorted(res.items(), key=lambda kv: -(kv[1]['ic'] if kv[1]['ic'] is not None else -9)):
        print(f"{g:14s} IC {v['ic'] if v['ic'] is not None else '-':>7}  날짜 {v['dates']}")
    if baseline:
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    last = OUT.read_text(encoding='utf-8').strip().splitlines()[-1] if OUT.exists() and OUT.stat().st_size else ''
    if last and json.loads(last)['asOf'] == asof:
        print('같은 asOf 가 이미 기록돼 있다 — 추가 안 함')
        return
    with open(OUT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f'기록: {OUT.relative_to(ROOT)} (asOf {asof})')


if __name__ == '__main__':
    main()
