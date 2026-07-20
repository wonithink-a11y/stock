"""pykrx로 코스피/코스닥 투자자별 순매수(최근 기간 합계)를 받아 docs/data/market_flows.json 생성.
GitHub Actions에서 실행(pip install pykrx). 개인·외국인·금융투자·투신·연기금·보험·기타법인 등 세부 주체 포함.

  결과: docs/data/market_flows.json
    { updatedAt, period:{start,end}, markets:{ KOSPI:[{name,net}], KOSDAQ:[...] } }
    net = 순매수 금액(원), |net| 큰 순으로 정렬.
"""
import datetime
import json
from pathlib import Path

try:
    from pykrx import stock
except ImportError:
    raise SystemExit("pykrx 미설치: 워크플로에서 'pip install pykrx' 필요.")

ROOT = Path(__file__).resolve().parent.parent   # 저장소 루트(스크립트는 scripts/)
OUT = ROOT / "docs" / "data" / "market_flows.json"

# 합계 성격의 행은 개별 주체 차트에서 제외(표시는 하되 aggregate 플래그)
AGG = {"전체", "기관합계", "기관계", "기타"}


def last_biz(off=0):
    d = datetime.date.today() - datetime.timedelta(days=off)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y%m%d")


def _net_series(df):
    """단일컬럼('순매수') / 멀티컬럼(('거래대금','순매수')) 모두에서 순매수 열을 찾아 반환."""
    cols = list(df.columns)
    for c in cols:  # 멀티레벨: 금액×순매수 우선
        if isinstance(c, tuple) and c[-1] == "순매수" and ("거래대금" in c or "금액" in c):
            return df[c]
    for c in cols:  # 멀티레벨: 아무 순매수
        if isinstance(c, tuple) and c[-1] == "순매수":
            return df[c]
    if "순매수" in cols:
        return df["순매수"]
    return None


def fetch(market, start, end):
    df = stock.get_market_trading_value_by_investor(start, end, market)
    print("[%s] index=%s" % (market, list(df.index)))
    print("[%s] columns=%s" % (market, list(df.columns)))
    s = _net_series(df)
    if s is None:
        print("[%s] 순매수 컬럼을 찾지 못함 → 위 columns 확인 필요" % market)
        return []
    items = []
    for name, net in s.items():
        name = str(name).strip()
        try:
            net = int(net)
        except Exception:
            continue
        items.append({"name": name, "net": net, "agg": name in AGG})
    items.sort(key=lambda x: abs(x["net"]), reverse=True)
    return items


def main():
    end = last_biz(0)
    start = last_biz(30)   # 약 최근 20거래일
    out = {
        "updatedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "period": {"start": start, "end": end},
        "source": "pykrx get_market_trading_value_by_investor",
        "markets": {},
    }
    for market in ("KOSPI", "KOSDAQ"):
        try:
            out["markets"][market] = fetch(market, start, end)
            print("[%s] %d개 주체" % (market, len(out["markets"][market])))
        except Exception as e:
            print("[%s] 실패: %s" % (market, e))
            out["markets"][market] = []

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(len(v) for v in out["markets"].values())
    print("✅ 총 %d개 주체 → %s" % (total, OUT))
    if not total:
        print("⚠ 0개 — pykrx 함수/기간 확인 필요. 위 로그를 공유해 주세요.")


if __name__ == "__main__":
    main()
