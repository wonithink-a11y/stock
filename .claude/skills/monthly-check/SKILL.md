---
name: monthly-check
description: 월간 점검 — A2a 월간 증분(매월 1~5일) 뒤 forward 그림자·기록 전용 관측을 한꺼번에 돌리고 observations 를 커밋하는 절차. "월간 점검", "그림자 돌려줘", "forward 기록", "이번 달 점검", "A2a 끝났어", "월초 점검" 같은 말이 나오면 반드시 이 스킬을 쓴다. 각 forward 의 --judge 가능 시점 확인이 필요할 때도 쓴다.
---

# 월간 점검

forward 관측 약 20개를 한 번에 돌리는 절차다. 전부 **기록 전용**(반사실 계산, 실주문·점수·매매 불연결)이라
결과 숫자로 전략을 바꾸지 않는다. 판정은 각 사전등록이 정한 시점에 `--judge` 로 1회뿐이고,
그 전에는 코드가 거부한다 — 거부되면 오류가 아니라 정상이다.

## 0. 선결 (건너뛰지 않는다)

그림자들은 A2a 가격이 갱신된 뒤에 돌려야 한다. 일찍 돌리면 묵은 가격으로 기록된다.

1. A2a 월간 증분(월 1~5일)과 `refresh-selections` 가 Actions 에서 녹색인지, 최신 일봉이 들어왔는지 확인.
   10월 selection 은 A2a 가 그 달 1일 일봉을 받아야 생긴다(2026-10 확인).
2. 로컬 `.env` 에 KRX 키. `export PYTHONIOENCODING=utf-8` 먼저(없으면 cp949 로 죽는다).
3. 실행 전 `git status` 로 낯선 변경 확인. 사용자의 미커밋 파일은 건드리지 않는다.

## 1. 증분 수집 (그림자들의 재료)

| 재료 | 명령 | 쓰는 곳 |
|---|---|---|
| KRX 일별 확장 | `python research/strategy-lab/collect_krx_daily_ext.py <이번 달>` | 마감 약세, 업종 모멘텀, 규모 장세 |
| ETF OHLC | `python research/strategy-lab/collect_etf_ohlc_krx.py` | ETF 그림자, FB, 업종 ETF |
| DART 공시 제목 | `python research/strategy-lab/collect_dart_event_titles.py --update` (≈3.4k콜, 한도 2만) | 업종 촉매, 뉴스 1분 |
| 수출 | `python research/strategy-lab/collect_kcs_exports.py` | 업종 모멘텀 |
| 업종지수 20개 | `python research/strategy-lab/run_sideways_regime_forward.py --collect` (KRX 로그인) | 횡보 국면 |

DART 는 동시 2개 이하로만 돈다(IP 차단 사고 2026-10-19). 병렬로 몰아치지 않는다.

## 2. 그림자 실행 (순서 무관, 각자 observations 를 쓴다)

모든 명령은 `research/strategy-lab/` 아래. 출력은 **건수만** — 성과 값을 열어 보지 않는다.
목록은 [references/shadows.md](references/shadows.md) 에 명령·기록 경로·판정 시점까지 표로 있다. 그 표를 위에서 아래로 돈다.
사전등록 해시·과거 참고·함정 원문은 `docs/control/월간점검-forward-상세-2026-10-25.md` 에 있다 — 표에 없는 사정이 의심되면 거기서 찾는다.

## 3. 시기가 정해진 것 (해당 달에만)

- **매월 1~7일**: 유망 테마 예측 3개 + 종목 종합 분석 10개를 Claude 가 직접 쓴다 (`--register YYYY-MM`, 등록일은 오늘만, 소급 금지, 중간 성과는 안 본다).
- **분기 공시 시즌 직후 (11/16 · 4/1 · 5/16 · 8/16)**: 분기 B 그림자 `--collect`, 52주 저점 `--collect-recent`.
- **11월 초 A5 갱신 뒤**: 점수 후보 3종 `run_score_candidates_shadow.py --snapshot`.
- **11월 말**: 연말 고배당 단면 재실행. **1월 초**: `run_night_forward.py --ff <작년>` 과 `dividend_record_filter.py --judge`.
- **A3 는 수동 디스패치** — 사업연도 재무가 안 들어왔으면 묵은 재무로 돈다. 5월 점검에서 확인.

## 4. 커밋

- 생성된 `reports/**/observations.jsonl` 류만 **파일 명시 add**. `git commit -a` 금지(사용자 로컬 변경이 딸려 간 사고, 2026-09-23).
- 메시지 예: `chore(shadow): 2026-11 월간 점검 forward 기록`.
- push 는 확인 후(🟡 은 커밋까지 자율, push 는 CLAUDE.md 의 Git 규칙을 따른다).
- `data/backfill/` 은 로컬에서 커밋하지 않는다 (절대 규칙 4).

## 5. 보고 (한 줄 + 이상만)

- 통과: "n개 그림자 기록, 신규 건수 …, 판정 시점 도달 0".
- 이상만 상세히: 거부 메시지가 판정 시점 때문이 아닌 경우, 가격 미갱신, 해시 불일치(`model_h5.txt` sha256 ≠ freeze.json → 재학습 금지, 기록 거부가 정상), 건수 0 이 이어질 때.
- 판정 시점에 닿은 forward 가 있으면 `references/shadows.md` 의 날짜로 확인하고, 사용자에게 `--judge` 실행 GO 를 묻는다.

## 하지 말 것

- 중간 성과로 판정·정의 변경·셀 추가. 결과를 보고 고르면 다중검정이다.
- 판정 시점 전 `--judge` 우회.
- O2b·O3u 모의 실행 재개 (2026-09-22 중단, 새 GO 없이 안 함). O2b **그림자**는 무관 — 계속 돌린다.
