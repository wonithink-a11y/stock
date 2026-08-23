# Macro Regime Layer 백필 — 실행 결과 보고 (2026-08-23)

`macro-regime-layer-design-2026-08.md`의 설계를 사용자 지시(2026-08-23, 10항목)
그대로 실행했다. 새 조인 로직 없음(§2, `macro_common.py::asof_join_kr()` 무변경
재사용), 기존 4축 regime 계산식·threshold 무변경(설계 §8). 이 문서는 실행
결과·audit만 기록한다 — 설계 근거는 design doc, 소스 근거는 source-check doc 참고.

---

## 1. 실행 요약

| 단계 | 스크립트 | 결과 |
|---|---|---|
| 백필(9 raw + 1 derived) | `build_macro_layer_backfill.py` | `data/market-regime/macro_layer_daily_kr.parquet`(3,097행, 2014-01-02~2026-08-14) |
| 병합 | `build_regime_features_backfill.py --merge`(기존 스크립트의 `MACRO_FILES` dict에 항목 추가만) | `market_regime_features.parquet` 25→**45컬럼**, 행수 2,604 그대로(2016-01-04~) |
| 감사 | `build_macro_layer_backfill.py --audit` | **15건 중 15 PASS**(아래 §2) |

---

## 2. Audit 결과 (전체 PASS)

- 중복 date 0건, date 오름차순 정렬 확인
- 10개 컬럼 전부 최소 1일 이상 유효값 존재(전부 결측인 컬럼 없음)
- `krCreditSpreadBp`: 한쪽 입력(국고채/회사채) NaN인 행은 예외 없이 결과도 NaN
  — 지어내지 않음(설계 §5) 확인
- **기존 25컬럼(4축 regime + 9 feature + USD/KRW + VIX) 전부 백업본과 완전
  일치, diff=0** — 이번 확장이 기존 데이터를 하나도 건드리지 않았다는 걸 직접
  대조로 확인(사용자 지시 §8)
- 병합본 행수(2,604) ≥ 백업본 행수(2,604) — 행 유실 없음

## 3. 컬럼별 커버리지(결측률)

| 컬럼 | validDays/전체 | missingRate |
|---|---|---|
| usFedFundsRate | 3097/3097 | 0.0000 |
| usTreasury10y | 3097/3097 | 0.0000 |
| usNasdaq | 3097/3097 | 0.0000 |
| krKospi | 2995/3097 | 0.0329 |
| krTreasury3y | 3096/3097 | 0.0003 |
| krCorpAA3y | 3096/3097 | 0.0003 |
| krCpi | 3074/3097 | 0.0074 |
| krLeadingCyclical | 3035/3097 | 0.0200 |
| krCoincidentCyclical | 3035/3097 | 0.0200 |
| krCreditSpreadBp | 3096/3097 | 0.0003 |

`krKospi`의 3.3% 결측은 KR 거래일 캘린더(2014-01-02~)가 네이버 KOSPI 이력
시작(2014-05-30)보다 앞서기 때문 — 2014-01~05 구간의 자연스러운 공백이지
수집 실패가 아니다. `krLeadingCyclical`·`krCoincidentCyclical`의 2.0%는 60일
lag 때문에 분석구간 맨 앞부분(2014년 초)이 아직 usableFromDate에 도달하지
않아 생기는 정상적인 워밍업 공백이다.

## 4. PIT 정합성 실측 확인 (합성 데이터 아닌 실데이터)

`--dry-run` 결과에서 직접 대조: 2026-08-12~14 구간의 `krLeadingCyclical`이
104.8(2026-05 관측치, usableFromDate=2026-07-30)을 계속 쓰고 있고 2026-06
관측치(105.7, usableFromDate=2026-08-29)는 아직 반영되지 않았다 — 설계
§3.3 계산식이 실데이터에서도 그대로 작동함을 확인했다.

## 5. 이번 실행이 하지 않은 것 (사용자 지시 §10 그대로)

- threshold 최적화 없음 — `lib/marketRegimeEngine.js`의 4축 정의·`-4~+4` 합산
  기준 무변경
- 새 macro feature 추가 없음 — 설계에서 확정한 10개(9 raw+1 derived)만 반영
- regime 재정의 없음 — 신규 10개 컬럼은 기존 regime 점수식에 아직 편입되지
  않은 "나란히 놓인" 컬럼일 뿐(설계 §8)
- CPI·경기종합지수 lag(5일·60일) 상수의 실제 통계청 공표일정 대조는 여전히
  안 함 — design doc §10에 이미 남긴 caveat 그대로 유효

## 검증 가능한 근거 목록

- `build_macro_layer_backfill.py` — 백필 스크립트, `--dry-run`·`--audit` 재실행하면 동일 결과
- `macro_common.py` — `ecos()`·`month_end()`·`usable_from_date_monthly()`·
  `ecos_daily_to_iso()`·`ecos_monthly_to_usable()` 신규 추가(기존 `fred()`·
  `asof_join_kr()`·`selftest_asof_join()`은 무변경)
- `test_macro_regime_layer_pit.py` — synthetic PIT selftest 12건 PASS(설계
  단계 검증, 실행 전 이미 통과), 이번 실행 전 macro_common 재사용 리팩터 후
  재실행해도 12건 전부 PASS 유지 확인
- `build_regime_features_backfill.py`의 `MACRO_FILES` dict — 이번에 추가한
  유일한 수정, 새 항목 하나만 추가(기존 9개 feature 그룹 로직 무변경)
- `data/market-regime/_manifest_macro_layer.json` — 이번 백필의 경량 manifest
- `data/market-regime/market_regime_features.parquet.bak_pre_macrolayer` —
  diff=0 확인에 쓴 백업본(로컬 전용, gitignore 대상)
