#!/usr/bin/env python3
"""관세청 수출입무역통계(HS 10단위) → DRAM/NAND/HBM대용 수출단가 → 005930·000660 주가.

사용자 GO(2026-09-13) — GitHub 개인(+AI공동저자, 별 0~1개) 저장소 3건을
데이터 소스로 쓰는 건 신뢰도 문제로 반려했고(finding 없음, 대화 기록 참고),
대신 그 저장소들이 인용한 원천(관세청 수출입무역통계)을 직접 조회하기로
했다. HS 코드는 관세법령정보포털(CLIP) 세계HS 8542.32(메모리) 하위
10자리에서 직접 확인:

    8542.32-1010  디램 DRAM            ← 진짜 D램 전용 코드(이전 세션 오판 정정 —
                                          ECOS 생산자물가지수엔 D램 품목이 없었지만
                                          관세청 HS 분류엔 있다)
    8542.32-1030  플래시메모리 (NAND)
    8542.32-3000  복합구조집적회로      ← HBM(적층형) 후보. 단 HBM 전용 코드가
                                          아니라 다른 적층 패키지도 섞일 수 있음(한계)

API: data.go.kr "관세청_품목별 수출입실적(GW)" (무료, 활용신청 필요 —
사용자가 이미 발급·승인받음). Base URL apis.data.go.kr/1220000/Itemtrade,
GET /getItemtradeList. ★ serviceKey는 data.go.kr이 이미 URL-인코딩해서
주는 값이라 urlencode()에 같이 넣으면 이중인코딩으로 깨진다(실측:
SERVICE_KEY_IS_NOT_REGISTERED_ERROR로 오진되기 쉽다) — serviceKey만
분리해서 그대로 붙인다.

실측 확인(2026-09-13): DRAM·NAND·복합구조 세 코드 전부 2007-01부터 월별
데이터 존재(그 이전은 0건 — 이 10자리 코드 체계 시행 시점으로 추정),
2026-08까지 최신. 순중량(kg) + 신고미화금액(수출 FOB)·과세가격(수입 CIF)
모두 제공 — export unit value(USD/kg) = 가격 근사치를 낼 수 있다(rishsriv
repo와 같은 방법론이지만 그 repo의 가공값을 믿지 않고 원천을 직접 받는다).

한계(그대로 남긴다): unit value는 계약가격이 아니라 "금액÷중량"이라
제품 구성비(다이 개수·패키지 크기) 변화가 섞인다 — 절대수준보다 변화율/
전환점 위주로 해석한다(이 저장소가 지금까지 써온 원칙과 동일).

PIT: API 설명에 "매월 15일경 전월까지 자료 갱신"이라고 명시돼 있다(추정이
아니라 문서화된 값) — 월말+20일로 가정(문서상 15일보다 며칠 더 늦춰
보수적으로).

    python research/strategy-lab/semiconductor_cycle_kcs_export_price.py
"""
import os
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from soxl_leadlag_common import load_fwd_returns, run_battery

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "data" / "semiconductor-cycle"
BASE = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
PIT_LAG_DAYS = 20
HS_CODES = {"dram": "8542321010", "nand": "8542321030", "multichip_hbm_proxy": "8542323000"}
TICKERS = {"005930": "s005930", "000660": "s000660"}
START_YM, END_YM = "200701", "202612"


def _load_key():
    key = os.environ.get("DATA_GO_KR_API_KEY", "")
    if key:
        return key
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATA_GO_KR_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("DATA_GO_KR_API_KEY 없음 (.env 확인)")


def _fetch_one_year(hs_code: str, start_ym: str, end_ym: str) -> list[tuple[str, float, float]]:
    key = _load_key()
    other = {"strtYymm": start_ym, "endYymm": end_ym, "hsSgn": hs_code,
              "imexTp": "1", "type": "json", "numOfRows": "50", "pageNo": "1"}
    url = f"{BASE}?serviceKey={key}&" + urllib.parse.urlencode(other)
    with urllib.request.urlopen(url, timeout=30) as r:
        raw = r.read().decode("utf-8")
    import re
    rows = []
    for m in re.finditer(r"<item>(.*?)</item>", raw, re.S):
        block = m.group(1)

        def field(name):
            mm = re.search(f"<{name}>(.*?)</{name}>", block)
            return mm.group(1) if mm else None

        year = field("year")
        if year is None or year == "총계" or "." not in year:
            continue
        exp_dlr, exp_wgt = field("expDlr"), field("expWgt")
        if exp_dlr in (None, "-") or exp_wgt in (None, "-", "0"):
            continue
        rows.append((year, float(exp_dlr), float(exp_wgt)))
    return rows


def fetch_hs_monthly(hs_code: str) -> pd.DataFrame:
    """(year, expDlr, expWgt) — 수출금액(USD)·수출중량(kg) 월별. serviceKey는
    이미 URL-인코딩돼 있으므로 urlencode에 넣지 않는다(위 docstring 참고).
    ★ 이 API는 조회기간을 1년 이내로 제한한다(실측: resultCode 99, "시작과
    종료의 조회기간은 1년이내 기간만 가능합니다") — 연도별로 나눠 호출한다."""
    start_year, end_year = int(START_YM[:4]), int(END_YM[:4])
    rows = []
    for y in range(start_year, end_year + 1):
        rows.extend(_fetch_one_year(hs_code, f"{y}01", f"{y}12"))
    df = pd.DataFrame(rows, columns=["yearMonth", "expDlr", "expWgt"])
    df["periodEnd"] = pd.to_datetime(df["yearMonth"], format="%Y.%m") + pd.offsets.MonthEnd(0)
    df = df.drop_duplicates("periodEnd").sort_values("periodEnd").reset_index(drop=True)
    return df


def build_factor_df(hs_code: str) -> pd.DataFrame:
    df = fetch_hs_monthly(hs_code)
    df["unitValue"] = df["expDlr"] / df["expWgt"]  # USD/kg — 가격 근사치(계약가 아님)
    df["availableFrom"] = df["periodEnd"] + pd.Timedelta(days=PIT_LAG_DAYS)
    df["ppi_yoy"] = df["unitValue"].pct_change(12) * 100
    df["ppi_chg3m"] = df["unitValue"].pct_change(3) * 100
    df["ppi_chg6m"] = df["unitValue"].pct_change(6) * 100
    df["ppi_yoy_accel"] = df["ppi_yoy"].diff(1)
    return df


def load_stock_close(ticker: str) -> pd.Series:
    import gzip
    import json
    rows = []
    for path in sorted((ROOT / "data" / "backfill" / "price" / "a2a").glob("*.jsonl.gz")):
        if path.stem.startswith("price-quality"):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("ticker") == ticker:
                    rows.append((rec["date"], rec["close"]))
    s = pd.DataFrame(rows, columns=["date", "close"]).drop_duplicates("date")
    s["date"] = pd.to_datetime(s["date"])
    return s.sort_values("date").set_index("date")["close"]


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    df = fetch_hs_monthly(HS_CODES["dram"])
    ck("DRAM 200개월 이상(2007~) 확보", len(df) > 200)
    ck("expDlr·expWgt 전부 양수", (df["expDlr"] > 0).all() and (df["expWgt"] > 0).all())
    ck("periodEnd 단조증가", df["periodEnd"].is_monotonic_increasing)

    fdf = build_factor_df(HS_CODES["dram"])
    ck("unitValue = expDlr/expWgt 계산됨", "unitValue" in fdf.columns and fdf["unitValue"].notna().any())
    ck("availableFrom = periodEnd+20일",
       (fdf["availableFrom"] - fdf["periodEnd"]).dt.days.eq(20).all())

    total = 5
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for code_name, hs in HS_CODES.items():
        df = build_factor_df(hs)
        for ticker, prefix in TICKERS.items():
            close = load_stock_close(ticker)
            merged = load_fwd_returns(df, close, prefix)
            out = OUT_DIR / f"kcs_export_{code_name}_{ticker}.parquet"
            merged.to_parquet(out, index=False)
            print(f"\n{'='*70}\n{code_name}({hs}) -> {ticker} ({out.name})\n{'='*70}")
            run_battery(merged, ["ppi_yoy", "ppi_chg3m", "ppi_chg6m", "ppi_yoy_accel"],
                        target_prefix=prefix)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
