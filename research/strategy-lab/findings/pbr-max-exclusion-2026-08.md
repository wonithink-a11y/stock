# PBR — MAX(복권효과) 제외 카운터팩추얼 결과 (2026-08-26)

`findings/github-literature-return-enhancement-candidates-2026-08.md`의
① 후보(Nartea, Wu & Liu 2014, *Applied Financial Economics* 24(6) 425-435 -
한국시장 실측 MAX효과, 검증 완료)를 실제로 구현·검증했다.

## 방법 — 왜 "노출 오버레이"가 아니라 "구성 제외"인가

`pbr_exposure_overlay_vs_baseline_mtm.py`류가 쓰는 `exposure_frac` 스칼라
방식은 시장 전체 타이밍 신호(미국 10년물 등)용이다 - baseline과 구성을
100% 동일하게 두고 곡선 전체에 가중치만 곱한다. MAX는 종목별 특성이라
"이 종목을 살지 말지"를 바꾸는 게 맞는 방법이지, 포트폴리오 전체 노출을
줄이는 게 아니다. 그래서 이번 실험은 **구성 자체를 바꾸는 카운터팩추얼**
로 설계했다:

`pbr_value_v1`이 이미 뽑은 매달 top-30 중, 그 달 적격 유니버스(turnover20
≥1억) 안에서 MAX5(최근 21거래일 일간수익 상위5 평균, Nartea/Wu/Liu의
정의)가 상위 20%(80th percentile 이상)에 해당하는 종목을 **대체 없이
제외**했다 - "이 종목들을 안 샀으면 어땠을까"에 정확히 대응한다.

## 결과: 개선 확인, PBR dropout 실험보다 큰 폭

| | baseline(pbr_value_v1) | MAX 제외(top20%) | 차이 |
|---|---|---|---|
| CAGR | 4.72% | **5.67%** | **+0.95%p** |
| MDD | -21.70% | **-20.80%** | 개선 |
| Sharpe | 0.4556 | **0.5814** | **+0.1258** |
| 청산 거래 | 756건 | 882건 | +16.7%(제외된 종목이 이후 재선정되며 추가 진입/청산 발생) |
| 제외된 (ticker,월) 슬롯 | - | 337/3,774 (8.9%) | |
| 월평균 보유종목수 | 29.7 | 27.1 | |

**3개 헤드라인 지표(CAGR·MDD·Sharpe) 전부 같은 방향으로 개선** - 같은 날
먼저 검증한 dropout 실험(CAGR +0.64%p, Sharpe +0.0345)보다 개선폭이 더
크다. 연도별로도 11개 연도 중 8개(2016·2017·2018·2022·2023·2024·2025·
2026)가 우위, 3개(2019·2020·2021)만 열위 - 특정 연도 하나에 몰린 착시가
아니다.

거래건수는 오히려 늘었다(756→882) - 제외가 영구적이지 않고 매달 재평가돼
경계선 근처(MAX5가 80th percentile을 오르내리는) 종목은 청산-재진입을
반복하기 때문이다. 이 추가 회전비용까지 반영된 채로도 net 성과가
개선됐다는 점이 결과를 더 신뢰할 만하게 만든다 - "회전율을 줄여서
좋아진" 게 아니라 "MAX 상위 종목 자체가 나쁜 편입이었다"는 방향이다.

## 방법론 재확인

baseline 재현치(CAGR 4.72%·MDD -21.70%·Sharpe 0.4556)가 CLAUDE.md 최종
정정본과 정확히 일치함을 먼저 확인한 뒤 비교를 신뢰했다(realized-pnl
방식이 아니라 `pbr_vs_ew_monthly_mtm.py`의 월별 MTM 방법론 재사용 -
`run_pbr_dropout_vs_baseline_mtm.py`와 동일 관례).

## 한계 — 아직 채택 근거로 쓰지 않는다

- **1회 실행, 20% 컷 하나만 테스트**. 10%·30% 등 다른 exclusion percentile
  스윕 안 함.
- **T1/T3(대형주) 분해 안 함** - 조사 문서 자체가 경고했듯 한국 MAX효과는
  등가중(소형주) 표본에서만 유의했다는 보고가 있다. 이 프로젝트가 3~4번
  재현한 "T3 대형주에서 반전" 패턴과 겹치는지 아직 확인 안 됨. PBR
  유니버스 자체가 절대유동성 필터(turnover≥1억)를 이미 통과한 종목들이라
  극단적 소형주는 아니지만, 그 안에서도 규모 편중이 있는지는 미확인.
- Out-of-sample 분할(TRAIN/VALID/TEST) 검증 안 함 - Opening Fade·REV20이
  겪은 "OOS 반전" 위험이 여기서도 있는지 아직 모른다.
- dropout(n_drop) 실험과의 **결합은 아직 안 함** - 둘 다 개선을 보였으니
  같이 적용하면 어떻게 되는지가 자연스러운 다음 질문이나, 두 효과가
  겹치는(회전율 감소 vs 종목 제외) 부분이 있어 단순 합산을 가정하면 안
  된다.

## 파일

- `strategies/pbr_value_v1_maxexcl/`(policy.json·rule.py·
  build_selection_maxexcl.py·selection.json) - rule.py는 pbr_value_v1과
  완전 동일(무변경 복사), 차이는 selection.json 생성 로직뿐(baseline
  selection.json을 읽어 MAX 상위 20% 슬롯만 제거)
- `build_selection_maxexcl.py --selftest`: MAX5 계산 함수 자체를 4건
  검증(균일 리턴·내림차순 상위 반영·표본 부족·빈 리스트) - 전부 통과
- `run_pbr_maxexcl_vs_baseline_mtm.py` - 이 문서의 실행 스크립트
- `reports/2026-08-26-pbr-maxexcl-vs-baseline-mtm/
  pbr-maxexcl-vs-baseline-mtm.json` - 원자료(연도별 수익률 포함)
