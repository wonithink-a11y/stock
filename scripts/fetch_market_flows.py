"""pykrx로 코스피/코스닥 '일별' 투자자별 순매수를 받아 docs/data/market_flows.json 생성.
GitHub Actions에서 실행(pip install pykrx). 세부 주체(연기금·금융투자·투신 등) 포함.

  결과: docs/data/market_flows.json
    { updatedAt, markets:{ KOSPI:{days:[{date, items:[{name,net,agg}]}, ...]}, KOSDAQ:{...} } }
    net = 그날 순매수 금액(원). items는 |net| 큰 순 정렬.

  세부(연기금 등)는 KRX 로그인 필요 → 워크플로 env로 KRX_ID/KRX_PW 주입.
"""
import datetime
import json
from pathlib import Path

try:
    from pykrx import stock
except ImportError:
    raise SystemExit("pykrx 미설치: 워크플로에서 'pip install pykrx' 필요.")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "market_flows.json"
AGG = {"전체", "기관합계", "기관계", "기타"}
LOOKBACK = 25  # 최근 약 25일(달력) → 거래일 ~17일


def last_biz(off=0):
    d = datetime.date.today() - datetime.timedelta(days=off)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y%m%d")


def trading_days(start, end):
    """거래일 목록(YYYYMMDD). 코스피 지수 OHLCV 인덱스 사용, 실패 시 평일 폴백."""
    try:
        df = stock.get_index_ohlcv(start, end, "1001")
        days = [d.strftime("%Y%m%d") for d in df.index]
        if days:
            return days
    except Exception as e:
        print("거래일 조회 실패, 평일 폴백:", e)
    out, d = [], datetime.datetime.strptime(start, "%Y%m%d")
    endd = datetime.datetime.strptime(end, "%Y%m%d")
    while d <= endd:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    return out


def _net_series(df):
    cols = list(df.columns)
    for c in cols:
        if isinstance(c, tuple) and c[-1] == "순매수" and ("거래대금" in c or "금액" in c):
            return df[c]
    for c in cols:
        if isinstance(c, tuple) and c[-1] == "순매수":
            return df[c]
    if "순매수" in cols:
        return df["순매수"]
    return None


def fetch_day(market, day):
    df = stock.get_market_trading_value_by_investor(day, day, market)
    s = _net_series(df)
    if s is None:
        return None
    items = []
    for name, net in s.items():
        name = str(name).strip()
        try:
            net = int(net)
        except Exception:
            continue
        items.append({"name": name, "net": net, "agg": name in AGG})
    if not any(it["net"] for it in items):
        return None  # 휴장/무거래
    items.sort(key=lambda x: abs(x["net"]), reverse=True)
    return items


def main():
    start, end = last_biz(LOOKBACK), last_biz(0)
    tdays = trading_days(start, end)
    print("거래일 %d일: %s ~ %s" % (len(tdays), start, end))
    out = {
        "updatedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "source": "pykrx get_market_trading_value_by_investor (일별)",
        "markets": {},
    }
    for market in ("KOSPI", "KOSDAQ"):
        days = []
        for day in tdays:
            try:
                items = fetch_day(market, day)
                if items:
                    days.append({"date": day, "items": items})
            except Exception as e:
                print("[%s %s] 실패: %s" % (market, day, e))
        out["markets"][market] = {"days": days}
        print("[%s] %d일 수집" % (market, len(days)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(len(v["days"]) for v in out["markets"].values())
    print("✅ 총 %d일 → %s" % (total, OUT))
    if not total:
        print("⚠ 0일 — pykrx/로그인/기간 확인 필요. 위 로그 공유해 주세요.")


if __name__ == "__main__":
    main()
