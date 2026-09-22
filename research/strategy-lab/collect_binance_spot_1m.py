"""바이낸스 현물 1분봉 수집 — data.binance.vision 공개 자료실(키 불필요).

월 zip(과거) + 일 zip(이번 달)을 받아 .CHECKSUM(sha256)으로 검증하고 parquet 하나로 합친다.
출력: data/crypto/1m/{SYMBOL}_1m.parquet (gitignore). 시각은 UTC 봉 시작(open_time) —
KST 변환은 읽는 쪽에서 한다(절대 규칙 3: 저장은 원본 시각 그대로, 컬럼명에 utc 명시).

  python collect_binance_spot_1m.py                    # BTCUSDT, 2017-08 ~ 어제
  python collect_binance_spot_1m.py --symbol ETHUSDT --start 2017-08

zip 캐시는 data/crypto/1m/_zip/ 에 남겨 재실행 시 다시 받지 않는다.
"""
import argparse, datetime as dt, hashlib, io, sys, time, zipfile
from pathlib import Path
import pandas as pd, requests

BASE = 'https://data.binance.vision/data/spot'
COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume',
        'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore']
OUT = Path(__file__).parent / 'data' / 'crypto' / '1m'


def fetch(url, dest):
    if dest.exists():
        return dest.read_bytes()
    for i in range(4):
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            return None
        if r.ok:
            break
        time.sleep(2 ** i)
    r.raise_for_status()
    chk = requests.get(url + '.CHECKSUM', timeout=60)
    chk.raise_for_status()
    if hashlib.sha256(r.content).hexdigest() != chk.text.split()[0]:
        raise RuntimeError(f'checksum mismatch: {url}')
    dest.write_bytes(r.content)
    return r.content


def parse(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=COLS)
    if not str(df.open_time.iloc[0]).isdigit():  # 헤더 행이 있는 파일
        df = df.iloc[1:].astype({'open_time': 'int64'})
    ot = df.open_time.astype('int64')
    unit = 'us' if ot.iloc[0] > 10**14 else 'ms'  # 2025-01 부터 현물은 마이크로초
    out = pd.DataFrame({'open_time_utc': pd.to_datetime(ot, unit=unit)})
    for c in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'taker_buy_base', 'taker_buy_quote']:
        out[c] = df[c].astype('float64')
    out['trades'] = df.trades.astype('int64')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbol', default='BTCUSDT')
    ap.add_argument('--start', default='2017-08')
    a = ap.parse_args()
    zdir = OUT / '_zip' / a.symbol
    zdir.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date()
    first_this_month = today.replace(day=1)
    parts, missing = [], []
    for m in pd.period_range(a.start, first_this_month - dt.timedelta(days=1), freq='M'):
        name = f'{a.symbol}-1m-{m}.zip'
        blob = fetch(f'{BASE}/monthly/klines/{a.symbol}/1m/{name}', zdir / name)
        if blob is None:
            missing.append(str(m)); continue
        parts.append(parse(blob))
    d = first_this_month
    while d < today:  # 이번 달은 일 파일로(어제까지)
        name = f'{a.symbol}-1m-{d}.zip'
        blob = fetch(f'{BASE}/daily/klines/{a.symbol}/1m/{name}', zdir / name)
        if blob is None:
            missing.append(str(d))
        else:
            parts.append(parse(blob))
        d += dt.timedelta(days=1)
    df = pd.concat(parts)
    # 원본 자체가 2017-12-04~18(+20.8초)·2018-02-09~10(+14.8초) 에 분 경계에서 밀려 있다(실측, 거래 있는 봉).
    off = df.open_time_utc.dt.floor('min') != df.open_time_utc
    df['open_time_utc'] = df.open_time_utc.dt.floor('min')
    print(f'floored {off.sum():,} misaligned bars')
    df = df.drop_duplicates('open_time_utc').sort_values('open_time_utc').reset_index(drop=True)
    gaps = df.open_time_utc.diff().dt.total_seconds().div(60).gt(1)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f'{a.symbol}_1m.parquet', index=False)
    print(f'{a.symbol}: {len(df):,} bars  {df.open_time_utc.min()} ~ {df.open_time_utc.max()} UTC  '
          f'gaps>1m: {gaps.sum()} (max {df.open_time_utc.diff().max()})  missing files: {missing or "none"}')


if __name__ == '__main__':
    sys.exit(main())
