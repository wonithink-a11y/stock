#!/usr/bin/env python
"""sentiment_contrarian_v1.py 후속 - 사용자 지시(2026-08-28)에 따른 마지막
진단 실험. bearish_z>=+2가 절대수치는 유의(NWt 최대 3.16)하지만 baseline
대비 초과수익이 전부 마이너스이고 TRAIN(1987~2007)/TEST(2007~2026) 부호가
어긋난 게, "2sigma가 너무 희소해 표본이 몇 개 안 되는 위기(2008·2020 등)에
쏠려서 생긴 노이즈인지" 확인하기 위해 1.5sigma로 한 번만 완화한다.

★ 1.5sigma는 사전에 고정한다. 1.0/1.2/1.3sigma 등으로 스윕하며 최적값을
찾지 않는다(사용자 명시 지시 - 이건 전략을 살리기 위한 최적화가 아니라
진단 실험). 종료 기준(사용자가 미리 정함, 결과를 본 뒤 바꾸지 않는다):
  1. TRAIN/TEST 방향 불일치 -> 종료
  2. 초과수익이 일관되게 0 근처 -> 종료
  3. 특정 자산/기간에서만 유의 -> 종료
  4. 1.5sigma에서도 의미있는 OOS(TEST) 초과수익 확인 -> 그때만 다음 단계

production 변경 없음, 새 API 호출 없음.
"""
import pandas as pd

from sentiment_contrarian_v1 import load_aaii, episodes, align_price, report_signal
from stress_score_rebound_check import DATA_DIR

THRESH = 1.5  # 고정 - 스윕 금지


def main():
    aaii = load_aaii()
    horizons = (60, 120, 252)

    print("=" * 90)
    print(f"bearish_z >= +{THRESH} (고정, 사전등록) - S&P500 / Nasdaq100")
    print("=" * 90)

    sp = aaii.dropna(subset=["sp500_close"]).sort_values("date").reset_index(drop=True)
    sp_close = sp["sp500_close"].to_numpy()
    ep = episodes(aaii, "bearish_z", ">=", THRESH)
    ep_sp = ep[ep["date"].isin(sp["date"])]
    pos_map = {d: i for i, d in enumerate(sp["date"])}
    positions = [pos_map.get(d, -1) for d in ep_sp["date"]]

    report_signal(f"bearish_z>=+{THRESH}", "S&P500(weekly) 전체", ep_sp, sp_close, positions, sp_close, horizons)
    mid = sp["date"].min() + (sp["date"].max() - sp["date"].min()) / 2
    report_signal(f"bearish_z>=+{THRESH}", "S&P500-TRAIN", ep_sp, sp_close, positions, sp_close,
                  horizons, lo=sp["date"].min(), hi=mid)
    report_signal(f"bearish_z>=+{THRESH}", "S&P500-TEST", ep_sp, sp_close, positions, sp_close,
                  horizons, lo=mid, hi=sp["date"].max() + pd.Timedelta(days=1))

    raw = pd.read_parquet(f"{DATA_DIR}/usnasdaq100_raw.parquet").rename(columns={"usableFromDate": "date"})
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.sort_values("date").reset_index(drop=True)
    nq_close = raw["value"].to_numpy()
    ep_nq = ep[(ep["date"] >= raw["date"].min()) & (ep["date"] <= raw["date"].max())]
    _, positions_nq = align_price(raw, ep_nq["date"].tolist())

    report_signal(f"bearish_z>=+{THRESH}", "Nasdaq100 전체", ep_nq, nq_close, positions_nq, nq_close, horizons)
    mid_nq = raw["date"].min() + (raw["date"].max() - raw["date"].min()) / 2
    report_signal(f"bearish_z>=+{THRESH}", "Nasdaq100-TRAIN", ep_nq, nq_close, positions_nq, nq_close,
                  horizons, lo=raw["date"].min(), hi=mid_nq)
    report_signal(f"bearish_z>=+{THRESH}", "Nasdaq100-TEST", ep_nq, nq_close, positions_nq, nq_close,
                  horizons, lo=mid_nq, hi=raw["date"].max() + pd.Timedelta(days=1))


if __name__ == "__main__":
    main()
