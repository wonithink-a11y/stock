---
track: kr
factor: infinite-buying-soxl-tsmc-monthly-revenue-pilot
date: 2026-09-13
verdict: REJECT
original_verdict: null
criteria_version: null
conditions: ["TSMC investor.tsmc.com/english/monthly-revenue/{year} 2013~2026-08, 164개월(스냅샷, Cloudflare 차단으로 Claude Browser 패널 수동조회, 조회일 2026-09-13)", "Consolidated Net Revenue만 사용, 원자료 YoY 보존+재계산 검산(평균오차 0.027%p)", "availableFrom = 월말+15일(공표관례 실측 최대지연 13일보다 보수적)", "SOXL +1M/+3M/+6M forward return", "Spearman + Newey-West(HAC) + 완전 비중첩 서브샘플 + 5분위 + 상승/하락전환 이벤트, 5개 factor", "전략화·threshold 최적화 없음"]
reason: "TSMC 월간매출(2013-2026, n=151~160, DART 분기 파일럿의 4배 빈도)로 SOXL 선행 1/3/6개월 수익률과의 관계를 재검증했다. naive Spearman·Newey-West(HAC) 전부 5개 factor x 3 horizon 15개 조합 중 유의(p<0.05)한 것이 하나도 없다. 완전 비중첩 서브샘플에서 6개월 간격(n=26)만 rho=-0.495 p=0.010으로 유의했으나, 같은 관계의 naive(n=151, p=0.184)·HAC(p=0.607) 버전은 전부 무의미해 다중검정 잡음(수십 개 조합 중 하나)일 개연성이 크다. 5분위 forward return은 단조성이 없고(Q3가 최고), YoY 상승전환(n=13, fwd6m +35.4%)과 하락전환(n=13, fwd6m +32.7%) 이벤트의 평균 수익률이 방향과 무관하게 거의 같아 이 이벤트 자체가 SOXL 수익률과 차별적 관계가 없음을 보여준다. DART 파일럿(HOLD, 방향은 콘트래리안이나 표본부족)보다 4배 큰 표본으로도 신호가 강화되지 않고 오히려 흐려졌다 - 표본을 늘려도 안 사는 관계라는 뜻으로 판정 REJECT."
cagr: null
sharpe: null
mdd: null
win_rate: null
n: 151
t_stat: null
---

# SOXL 산업사이클 연구 Stage 2 — TSMC 월간매출 파일럿 (2026-09-13)

> 사용자 GO — Stage 1(DART 분기, HOLD)의 "표본 부족" 문제를 월간 빈도로
> 재검증한다. VIX → IPG3344S → DART → **TSMC**로 이어지는 단계적 검증의
> 네 번째.

## 0. 수집 방법 — Cloudflare 차단, 스냅샷으로 대응

`investor.tsmc.com`은 Cloudflare 봇 차단이 걸려 있다. `requests`로 첫 호출은
196KB 정상 응답을 받았지만 바로 다음 호출부터 "Just a moment..." JS 챌린지
페이지로 막혔다(실측). **우회 시도(TLS 지문 위장, 챌린지 자동풀이)는 하지
않았다** — 접근제어를 피해가는 것이지 기술 문제 해결이 아니기 때문이다.
대신 Claude Browser 패널(실제 브라우저, 챌린지를 정상 통과)로 2013~2026년
14개 연도 페이지를 순회해 값을 얻었고, 스크립트에는 그 스냅샷을 고정값으로
박아뒀다. **이건 DART/FRED처럼 재실행 시 자동 갱신되는 수집기가 아니다** —
갱신하려면 같은 방식(브라우저 수동 조회)을 반복해야 한다. 이 사실을
finding에 명시하는 이유는 "다음에 스크립트만 다시 돌리면 최신화된다"는
잘못된 기대를 막기 위해서다.

## 1. 검산

사용자 지시(§3, 원자료 YoY 보존 + 재계산 검산)대로, 내 `pct_change(12)`
계산값을 TSMC가 표에 직접 게시한 YoY와 대조했다 — **152개월 평균 절대오차
0.027%p, 최대 0.050%p**로 사실상 완전히 일치(반올림 오차 수준). 전사 실수
없음을 확인.

## 2. PIT

TSMC의 financial-calendar 페이지(공표일 목록)는 별도 JS 렌더링이라 이번
스코프에서 스크레이핑하지 않았다. 대신 2025~2026년 실측 캘린더(정규월
발표일이 항상 다음달 8~13일)를 보수적으로 반영해 **월말+15일**을
availableFrom으로 가정했다 — 관측된 최대 지연(13일)보다 며칠 더 늦춰
look-ahead 방향으로 치우치지 않게 했다.

## 3. 결과 — 4배 큰 표본에서도 신호 없음

**naive Spearman**(5 factor × 3 horizon = 15개 조합, n=151~160): 전부
p>0.09, 유의한 조합 0개.

**Newey-West(HAC) OLS**: 겹치는 예측구간의 자기상관을 보정하니 전부
p>0.17로 더 흐려짐(0개 유의).

**완전 비중첩 서브샘플**: 1개월 간격(n=151, 원래 안 겹침) p=0.462, 3개월
간격(n=51) p=0.138, **6개월 간격(n=26)만 rho=-0.495, p=0.010**으로 유의.
그러나 바로 이 6개월 관계의 naive 버전(n=151, p=0.184)과 HAC 버전(p=0.607)은
전혀 유의하지 않다 — **같은 관계를 세 가지 방법으로 쟀는데 그중 하나(가장
표본이 작은 것)만 우연히 걸린 모양**이다. 이번 파일럿에서 5 factor×3
horizon×naive/HAC(30) + 3개 비중첩(3) = 30개 이상의 검정을 돌렸으니,
α=0.05에서 순수 잡음만으로도 1~2개는 우연히 걸린다(이 저장소가 이미
factor-sweep 연구에서 확인한 다중검정 함정과 같은 모양, CLAUDE.md 참고).
**이 p=0.010 하나를 신호로 채택하지 않는다.**

**5분위 forward return**: rev_yoy 최저~최고 5분위 중 fwd1m·fwd3m 최고가
Q3(중간)에서 나온다 — 단조성 없음, 노이즈 패턴.

**상승전환·하락전환 이벤트**(YoY 부호가 바뀌는 달): 상승전환(n=13) 평균
fwd6m +35.4%, 하락전환(n=13) 평균 fwd6m +32.7% — **방향과 무관하게 거의
같다.** 이건 "TSMC 매출 YoY가 플러스로 돌든 마이너스로 돌든 그다음
6개월 SOXL 수익률은 그냥 이 표본 기간의 일반적인 강세 드리프트"라는
뜻이다 — 이벤트 자체가 차별적 정보를 안 준다는 가장 직접적인 반증.

## 4. DART 파일럿과의 비교 — 같은 계열 가설을 더 큰 표본으로 재검증했으나 재현 안 됨

★ 정확한 표현: DART(분기, 삼성·SK하이닉스)와 TSMC(월간)는 같은 표본을 다른
빈도로 자른 것이 아니라 **다른 기업·다른 변수**다. "표본을 4배 늘렸다"는
직관적 요약이지 통계적으로 정확한 문장은 아니다 — 정확히는 **"동일한
산업 실적 계열의 가설('기업 매출 성장률로 SOXL 방향을 잡는다')을 더
높은 빈도·다른 기업(TSMC)의 큰 표본으로 검증했지만 재현되지 않았다"**다.

| | Stage 1 (DART, 분기) | Stage 2 (TSMC, 월간) |
|---|---|---|
| n | 36(중첩)/18(비중첩) | 151(중첩)/26(6M 비중첩) |
| naive 최고 유의성 | 6개월 p=0.033 | 어디에도 없음(최저 0.09대) |
| HAC 보정 후 | p=0.102(소멸) | 전부 p>0.17(소멸) |
| 방향 | 일관된 콘트래리안 | 일관성 없음(부호 뒤섞임) |

DART에서 봤던 "방향은 있는데 표본이 작다"는 가설이 맞다면, 표본을 4배
늘렸을 때 신호가 **더 뚜렷해져야** 한다. 실제로는 반대로 **더 흐려졌다** —
이는 DART의 약한 신호가 애초에 진짜 관계가 아니라 작은 표본의 잡음이었을
가능성을 높인다.

## 5. 판정 — REJECT

TSMC 월간매출은 SOXL 선행 1/3/6개월 수익률에 대해 강건한 신호를 주지
않는다. 표본을 늘려도(분기→월간, n 4배) 관계가 강해지지 않고 오히려
사라졌다 — "표본 부족"이 아니라 "관계 자체가 약하거나 없다"는 쪽으로
결론이 기운다.

## 6. 다음 단계

사용자가 제안한 순서(TSMC → WSTS(skip) → **SEMI Billings** → Micron/ASML/LRCX)
중 SEMI를 다음 GO로 잡았으나, 착수 전 확인(2026-09-13) 결과 **SEMI가 2022년
2월부로 North America Equipment Billings 월간 보도자료 무료 배포를 중단했다**
(SEMI 공식 페이지 명시: "SEMI ceased publishing monthly press release for the
North America Semiconductor Equipment Billings report in February 2022").
Book-to-Bill은 이미 2017년에 끊긴 것으로 알려져 있었는데(사용자 확인),
그 후속으로 대체됐다던 Billings 보도자료마저 무료 경로가 막혀 있다 — 지금은
유료 회원(SEMI 멤버십)에게만 배포된다. 즉 **2022년 이후(SOXL이 가장 크게
움직인 AI 랠리 구간 포함) 최근 4.5년치를 이 무료 경로로는 아예 구할 수
없다** — TSMC처럼 "붙어봤더니 신호가 없었다"가 아니라 **착수 자체가 이
방법으로는 불가능**하다. 사용자가 사전에 정한 기준("SEMI도 실패하면 연구축
자체를 중단")을 데이터 가용성 차원에서 충족한 것으로 본다. DART·TSMC 둘 다
"산업 실적 지표 하나로 SOXL 방향을 맞추려는" 시도였고, 방향(콘트래리안)은
있어 보이지만 통계적으로 재현되지 않는 동일 패턴이 두 번 반복된 데다
SEMI마저 무료로 안 되므로, 이 연구축(반도체 산업 실적/판매 지표 → SOXL
예측)은 여기서 종료를 권한다. 유일하게 남는 대체 경로는 WSTS(무료로 살아
있음, semiconductors.org 월간 보도자료 확인됨)이나, DART·TSMC와 개념적으로
같은 변수 종류(매출 성장률)라 재현 가능성이 낮다고 본다 — 진행 여부는
사용자 판단.

## 산출물

- `research/strategy-lab/semiconductor_cycle_tsmc_monthly.py` — 스냅샷 데이터 + 분석(selftest 5/5)
- `research/strategy-lab/data/semiconductor-cycle/tsmc_monthly_revenue.parquet` — 164행
