"""VIX 인버스 규칙 점검 — 읽기 전용, 주문·계좌 연결 없음.

    python scripts/vix-inverse-check.py            # 오늘 상태 + SVIX 면제(QN) 만료일
    python scripts/vix-inverse-check.py --selftest # 네트워크 없이 규칙 검증

규칙(research/strategy-lab/findings/vix-level-product-era-results-2026-11.md):
  VIX 종가 ≥ 20 이면 다음 거래일 시가에 인버스 매수, 종가 ≤ 16 이면 다음 거래일 시가에 전량 매도.
  분할(수준 분할): 20·25·30·35 를 처음 넘을 때마다 1/4 씩, 한 번 산 단계는 줄이지 않는다.
이 규칙은 사전등록 OOS 기준을 통과하지 못했다(p 0.071). 투자 권유가 아니다.
"""
import argparse
import datetime as dt
import re
import sys

ENTRY, EXIT, LEVELS = 20.0, 16.0, (20.0, 25.0, 30.0, 35.0)
QN_URL = "https://www.volatilityshares.com/svix/PTP-Qualified-Notice-Quarterly"


def step(state, v):
    """종가 v 하나를 처리. state=(holding, tranches). 반환 (state, 신호)."""
    holding, n = state
    if holding and v <= EXIT:
        return (False, 0), "EXIT"
    if not holding and v >= ENTRY:
        return (True, sum(L <= v for L in LEVELS)), "ENTER"
    if holding:
        m = max(n, sum(L <= v for L in LEVELS))
        return (True, m), ("ADD" if m > n else "HOLD")
    return (False, 0), "WAIT"


def run(closes):
    """closes=[(date, close)] 오름차순. 처음 VIX ≤ 16 인 날부터 시작(그날은 확실히 대기 상태)."""
    i0 = next((i for i, (_, v) in enumerate(closes) if v <= EXIT), None)
    if i0 is None:
        raise SystemExit("기간 안에 VIX ≤ 16 인 날이 없어 상태를 확정할 수 없다")
    state, sig, info = (False, 0), "WAIT", {}
    for d, v in closes[i0:]:
        prev = state
        state, sig = step(state, v)
        if state[0] and not prev[0]:
            info = dict(entry_date=d, entry_vix=v, peak=v)
        elif state[0]:
            info["peak"] = max(info["peak"], v)
    return state, sig, info, closes[-1]


def qn_status(today=None):
    import requests
    today = today or dt.date.today()
    try:
        t = requests.get(QN_URL, timeout=30, headers={"User-Agent": "stock-research-monitor/1.0"}).text
        m = re.search(r"(\d{4})(\d{2})(\d{2})\.pdf", t)
        posted = dt.date(*map(int, m.groups()))
    except Exception as e:  # 네트워크·페이지 형식 변경
        return f"SVIX 면제(QN) 확인 실패: {e}"
    left = (posted + dt.timedelta(days=92) - today).days
    tag = "만료 임박 — 증권사 공지 확인" if left < 21 else "여유"
    return (f"SVIX·UVIX 면제(QN) 공시일 {posted}, 만료 {posted + dt.timedelta(days=92)} (D-{left}, {tag}). "
            f"SVXY 등 ProShares 는 이 출처로 확인 못 함 — 증권사 PTP 목록 확인")


def selftest():
    def final(seq):
        st = (False, 0)
        for v in seq:
            st, sig = step(st, v)
        return st, sig
    assert final([15, 18, 19]) == ((False, 0), "WAIT")
    assert final([15, 20.5]) == ((True, 1), "ENTER")
    assert final([15, 20.5, 26]) == ((True, 2), "ADD")
    assert final([15, 31]) == ((True, 3), "ENTER")                    # 갭 급등: 한 번에 3단계
    assert final([15, 26, 22]) == ((True, 2), "HOLD")                 # 단계는 줄이지 않는다
    assert final([15, 26, 18]) == ((True, 2), "HOLD")                 # 16 위에서는 청산하지 않는다
    assert final([15, 26, 16.0]) == ((False, 0), "EXIT")
    assert final([15, 26, 15.9, 19]) == ((False, 0), "WAIT")          # 청산 뒤 20 미만은 대기
    assert final([15, 26, 15.9, 21]) == ((True, 1), "ENTER")
    s, sig, info, last = run([(f"d{i}", v) for i, v in enumerate([22, 21, 17, 15, 18, 21, 27, 23])])
    assert s == (True, 2) and sig == "HOLD" and info["entry_vix"] == 21 and info["peak"] == 27, (s, sig, info)
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    import yfinance as yf
    sys.stdout.reconfigure(encoding="utf-8")
    x = yf.download("^VIX", period="3y", progress=False, auto_adjust=False)
    x.columns = x.columns.get_level_values(0)
    closes = [(d.date(), float(v)) for d, v in x["Close"].dropna().items()]
    (holding, n), sig, info, (ld, lv) = run(closes)
    print(f"VIX 최근 종가 {lv:.2f} ({ld})")
    msg = {"WAIT": "대기 — 매수 신호 없음 (20 이상 마감 시 다음 거래일 시가 매수)",
           "ENTER": "신호: 다음 거래일 시가에 매수 시작", "ADD": "신호: 다음 거래일 시가에 분할 추가 매수",
           "HOLD": "보유 구간 유지 (16 이하로 마감하면 청산)", "EXIT": "신호: 다음 거래일 시가에 전량 매도"}[sig]
    print(msg)
    if holding:
        print(f"진입 {info['entry_date']} (VIX {info['entry_vix']:.1f}), 이후 VIX 최고 {info['peak']:.1f}, "
              f"분할 단계 {n}/{len(LEVELS)} (누적 투입 {n * 100 // len(LEVELS)}%)")
    print(qn_status())


if __name__ == "__main__":
    main()
