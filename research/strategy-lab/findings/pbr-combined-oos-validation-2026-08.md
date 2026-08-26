# PBR combined 파라미터 스윕 — OOS(TRAIN/VALID/TEST) 검증, 반전 없음 (2026-08-26)

`findings/pbr-combined-paramsweep-2026-08.md`이 "nDrop=2+pct=0.8이 격자
전체 최선"이라 찾은 것은 **전체 기간(2016~2026)을 다 보고 사후에 고른
값**이라는 한계를 그 findings 자신이 적어 뒀다. `run_strategy_validation.py`
가 CAND1·Opening Fade에 쓴 원칙("TRAIN에서만 스윕, VALID·TEST는 고정된
선택을 보고만 한다")을 `run_pbr_combined_oos_validation.py`(커밋)로 같은
12격자(3 dropout-alone + 9 combined)에 적용했다.

시간분할(월별 시가평가 스냅샷 128개월 기준 60/15/25%):
```
TRAIN 2016-01 ~ 2022-06 (77개월)
VALID 2022-06 ~ 2024-01 (19개월)
TEST  2024-01 ~ 2026-08 (33개월)
```

## 결과 (Sharpe, 12격자 전체)

| | TRAIN | VALID | TEST |
|---|---|---|---|
| nDrop=2, maxexcl=none | 0.5029 | 0.2536 | 0.9000 |
| nDrop=2, maxexcl=0.7 | 0.5894 | 0.3249 | 1.1214 |
| **nDrop=2, maxexcl=0.8** | **0.6943** | 0.3337 | **1.1361** |
| nDrop=2, maxexcl=0.9 | 0.6454 | **0.4736** | 1.0328 |
| nDrop=3, maxexcl=none(원 baseline) | 0.5020 | 0.1640 | 0.6701 |
| nDrop=3, maxexcl=0.7 | 0.5592 | 0.2225 | 1.0146 |
| nDrop=3, maxexcl=0.8(첫 결합실험 값) | 0.6780 | 0.2172 | 1.0413 |
| nDrop=3, maxexcl=0.9 | 0.6216 | 0.3076 | 0.8904 |
| nDrop=5, maxexcl=none | 0.4939 | 0.1473 | 0.5248 |
| nDrop=5, maxexcl=0.7 | 0.5306 | 0.1951 | 0.9027 |
| nDrop=5, maxexcl=0.8 | 0.6369 | 0.1926 | 0.7934 |
| nDrop=5, maxexcl=0.9 | 0.6103 | 0.2268 | 0.6852 |

## 판정 — 반전 없음, TRAIN 선택이 전체기간 선택과 일치

**① TRAIN에서 고른 최선(nDrop=2, maxexcl=0.8)이 전체기간 스윕이 골랐던
것과 정확히 같다** - 그 선택이 순전히 사후적 look-ahead 산물만은 아니라는
뜻. TRAIN 구간 자체만 봐도 이 조합이 가장 낫다.

**② 12격자·3구간(TRAIN/VALID/TEST) 전부에서 Sharpe가 양(+)이다** - 부호
반전 0건. 이 프로젝트가 REV20·Opening Fade에서 반복 겪은 "TEST에서
부호가 뒤집힌다"는 패턴이 여기서는 나타나지 않는다 - dropout+maxexcl
결합 실험은 지금까지 이 프로젝트의 PBR 계열 실험 중 OOS 반전 위험이
가장 낮은 축에 든다.

**③ VALID 구간(2022-06~2024-01)이 모든 격자점에서 공통으로 가장
약하다** - 파라미터 문제가 아니라 그 구간 자체가 어려운 국면(고금리·
변동성 국면과 겹침)이라는 뜻. TEST(2024-01~2026-08)는 반대로 전부
가장 강하다 - 최근 구간에 유리하게 편중됐을 위험은 있으나, 그 편중이
"어떤 파라미터를 고르느냐"와 무관하게 전 격자에 걸쳐 있어 선택 자체를
무효화하지는 않는다.

**④ 다만 TRAIN이 고른 게 VALID 최적은 아니다** - VALID만 보면 오히려
nDrop=2/maxexcl=0.9(Sharpe 0.4736)가 더 낫다. 이건 정상적인 파라미터
선택 노이즈이지 치명적 결함은 아니다 - TRAIN픽(0.8)도 VALID에서 여전히
0.3337로 양호한 축에 속한다(전체 12격자 중 2위).

## 종합

dropout+maxexcl 결합·nDrop=2/pct=0.8 선택은 이 OOS 검증을 통과했다 -
"연구 후보"에서 "production 결정을 실제로 고려해볼 후보"로 한 단계
올라간다. 단 여전히:
- 단일 팩터(PBR) 계열 실험이라 이 프로젝트가 반복 겪은 "2022년 한 해가
  대부분을 설명한다"는 concentration 문제 자체를 이 검증이 직접 배제하지
  않는다(연도별 기여 분해는 별도 확인 필요).
- production 채택은 여전히 별도 🔴 결정 - 이 findings는 "OOS에서 반전은
  없었다"는 근거 하나를 추가할 뿐이다.
