# forward 그림자 목록

CLAUDE.md 상태 블록(2026-10-25 기준) 에서 옮긴 표. 명령은 저장소 루트에서, 경로는 `research/strategy-lab/` 기준.
판정 시점은 사전등록 값이며 코드가 그 전 `--judge` 를 거부한다. 표가 낡았을 수 있으니 의심되면 각 스크립트 docstring 과 대조한다.

| # | 이름 | 명령 | 기록 위치 (커밋) | 판정 시점 |
|---|---|---|---|---|
| 1 | 부분 익절 | `run_partial_exit_shadow.py` | `reports/2026-09-partial-exit-shadow/observations.jsonl` | 12코호트·300건 1회, INCONCLUSIVE 면 24코호트 1회 |
| 2 | O2b | `futures/run_close_open_shadow.py` | 해당 observations.jsonl | 셀별 250 신호일 (≈2027-09~2028-01) |
| 3 | ETF 종가→시가 | `run_etf_close_open_shadow.py` (KRX 증분 포함) | `reports/2026-09-etf-shadow/observations.jsonl` | 위와 같음 (사전등록 c42e17dc) |
| 4 | M2 미국 야간 | `run_us_overnight_shadow.py` | `reports/2026-09-us-overnight-shadow/observations.jsonl` | 250 거래일 (≈2027-10) |
| 5 | 뉴스 | `run_news_shadow.py` | `reports/2026-10-news-shadow/observations.jsonl` | 양쪽 각 150건 (≈6개월) |
| 6 | 업종 부상 | `run_sector_rise_study.py --forward` (월별 `--forward-report`) | `reports/2026-10-sector-rise-forward/events.jsonl` | 기록 전용 |
| 7 | 업종 촉매 · 거래대금 | `collect_dart_event_titles.py --update` 후 `run_sector_catalyst_study.py --forward-report` · `run_sector_volume_confirm.py --forward-report` | 각 reports | 12개월 뒤 월별 1회 |
| 8 | 업종 ETF 연계 | ETF 증분 후 `run_sector_etf_study.py --forward-report` | 각 reports | 사전등록 53e2f7ef |
| 9 | 분기 실적 급변 B | `run_quarterly_growth_shadow.py --mature` · `--report` (시즌 직후 `--collect 2026Q3`) | `reports/2026-10-quarterly-growth-shadow/` | 만기 ≥300건 ∧ 분기 코호트 ≥4 (≈2027-11~12) |
| 10 | 연속 상승 7일 | `run_streak7_shadow.py` | `reports/2026-10-streak7-forward/observations.jsonl` | 성숙 500건·24개월 `--judge` |
| 11 | 52주 저점 × 실적 | `low52_fundamental_paths.py --forward` | `reports/2026-10-low52-forward/` | 12·18개월(≈2028-01·07) 중간, 24개월 최종 |
| 12 | 야간 후보 3칸 | `run_night_forward.py --fa1` · ETF 증분 후 `--fb` | `reports/2026-10-night-forward/` | FA1 300건·12개월, FB 250일·12개월, FF ≈2029-01 |
| 13 | 쿨라마기 돌파 | `qullamaggie_breakout.py --forward` | `reports/2026-10-qb-forward/` | 닫힌 거래 60건·24개월 |
| 14 | 업종 모멘텀 국면 | `run_sector_momentum_forward.py` | `reports/2026-10-sector-momentum-forward/` | 12개월(조기는 p<0.001만) · 24개월 최종 ≈2028-11 |
| 15 | 결합 순위 h5 | `run_combined_rank_shadow.py` (패널 재구성 수 분) | `reports/2026-10-combined-rank-shadow/` | 마지막 성숙 신호일 ≥ 2027-10-13 |
| 16 | 수익성 팩터 | `run_quality_forward.py` | `reports/2026-10-quality-forward/` | 12개월(≈2027-12) · 24개월 ≈2028-12 |
| 17 | 횡보 국면 M | `run_sideways_regime_forward.py` (`--collect` 선행) | `reports/2026-10-sideways-regime-forward/` | 국면 달 outcome 24개 (≈2032) |
| 18 | 장중 뉴스 1분 | `run_news_minute_forward.py --sync` 후 인자 없이 | `reports/2026-10-news-minute-forward/` | 갈래별 150건·6개월 |
| 19 | 마감 30분 약세 | `run_close_weakness_forward.py --sync` 후 인자 없이 | `reports/2026-10-close-weakness-forward/` | 250 성숙일 (≈2027-10). 분봉은 VM 에만 쌓이니 월 1회 이상 |
| 20 | 무한매수 하락일 2배 | `run_infbuy_dip_shadow.py` | `reports/2026-09-infbuy-dip-shadow/observations.jsonl` | 2028-09-29 |
| 21 | 업비트 신규 상장 숏 | `run_upbit_listing_forward.py` (자주 돌릴수록 누락 감소) | `reports/2026-10-upbit-listing-forward/` | 상장일 60 또는 2027-10-19 ∧ 30 |
| 22 | 미국 목표가 큰 변경 | `collect_us_price_targets.py` (≈3분) 후 `run_us_target_change_forward.py` | `reports/2026-10-us-target-change-forward/` | UP_L·DN_L 각 150 (≈2027-05~06) |

## 메모

- 실행 위치: 대부분 로컬 PC. #18·#19 는 VM `~/collector-venv/news`·`~/minute-raw` 에서 `--sync` 로 복사해 온다(`ssh stock-new`, hostname 은 `stock`).
- #15: `model_h5.txt` sha256 이 freeze.json 과 다르면 기록을 거부한다. 재학습 금지.
- 점수 후보 3종(`run_score_candidates_shadow.py --snapshot`)은 11월 초 한 번.
- 일부 그림자는 Actions 가 자동으로 쌓는다(급등 군집 `clusters.jsonl` 은 market-movers 워크플로). 손으로 돌리지 않는다.
- 이 표가 CLAUDE.md 와 어긋나면 CLAUDE.md 가 정본이다. 새 forward 를 사전등록하면 여기에 한 행 추가한다.
