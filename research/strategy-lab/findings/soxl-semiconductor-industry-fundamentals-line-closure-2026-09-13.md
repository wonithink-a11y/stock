---
track: kr
factor: soxl-semiconductor-industry-fundamentals-line-closure
date: 2026-09-13
verdict: REJECT
original_verdict: null
criteria_version: null
conditions: ["DART 삼성전자·SK하이닉스 분기실적(2016-2025, n=36/18)", "TSMC 월간매출(2013-2026, n=151/26)", "SEMI Equipment Billings(무료 보도자료 2022-02 중단 확인, 착수 불가)", "WSTS Global Semiconductor Sales(무료로 생존하나 SKIP - 동일 가설 반복)", "SOXL +1M/+3M/+6M forward return, Spearman+Newey-West+비중첩+분위수+전환이벤트 공통 방법론"]
reason: "'반도체 기업/산업의 매출·판매 실적 성장률이 SOXL의 향후 1~6개월 수익률을 예측하는가'라는 단일 가설을 세 가지 서로 다른 표본(한국 메모리 2사·TSMC·글로벌 반도체 판매)에서 시험할 계획이었다. DART는 방향(콘트래리안)은 있으나 표본부족(HOLD/REJECT 경계), TSMC는 4배 큰 월간표본에서도 재현 안 됨(REJECT), SEMI는 핵심 최근 구간(2022~) 무료 데이터 자체가 없어 착수 불가, WSTS는 DART/TSMC와 동일 변수 계열이라 반복할 근거가 약해 SKIP. 두 개의 독립 기업군에서 재현 실패 + 세 번째(SEMI) 데이터 부재 + 네 번째(WSTS) 반복 회피라는 조합으로 연구축을 종료한다. 판정은 '반도체 산업 사이클이 존재하지 않는다'가 아니라 '무료 공개 매출/판매 실적 지표로 SOXL 예측에 쓸 신호를 찾지 못했다'는 스코프 한정 REJECT다."
cagr: null
sharpe: null
mdd: null
win_rate: null
n: null
t_stat: null
---

# SOXL — 반도체 산업 실적/판매 기반 예측 연구축 종료 (2026-09-13)

> `infinite-buying-soxl-semiconductor-cycle-feasibility` →
> `infinite-buying-soxl-semiconductor-cycle-dart-pilot` →
> `infinite-buying-soxl-tsmc-monthly-revenue-pilot` 세 건의 종합.
> 사용자 합의(2026-09-13)로 이 시점에서 연구축을 닫는다.

## 1. 시험한 가설 (하나로 통일)

세 후보(DART·TSMC·SEMI)와 검토만 하고 접은 하나(WSTS)는 표면상 다른
데이터였지만 전부 같은 가설의 변주였다:

> **"반도체 기업 또는 산업 전체의 매출·판매 실적 성장률(YoY/QoQ 변화)이
> SOXL의 향후 1~6개월 수익률을 예측하는가?"**

## 2. 결과 요약

| 후보 | 표본 | 방법 | 결과 |
|---|---|---|---|
| DART(삼성전자·SK하이닉스, 분기) | n=36(중첩)/18(비중첩) | Spearman+HAC+비중첩 | 방향(콘트래리안) 있으나 HAC·비중첩에서 유의성 소멸 — HOLD |
| TSMC(월간매출) | n=151(중첩)/26(6M비중첩) | 동일 방법론 + 분위수 + 전환이벤트 | 4배 큰 표본에서도 재현 안 됨, 상승/하락전환 이벤트 수익률 무차별 — **REJECT** |
| SEMI(장비 Billings) | — | — | 2022-02부로 무료 보도자료 중단 확인, 핵심 최근구간(2022~) 데이터 자체 부재 — **착수 불가** |
| WSTS(글로벌 반도체 판매) | — | — | 무료로 생존하나 DART/TSMC와 동일 변수 계열(매출성장률)이라 반복 근거 약함 — **SKIP** |

## 3. 종료 판단의 근거

1. **두 개의 독립적 기업군(한국 메모리 2사, TSMC)에서 같은 가설이 재현 안
   됐다** — 우연이 아니라 구조적으로 이 방향(매출 성장률 → 가격 예측)에
   안정적 신호가 없을 가능성을 시사한다.
2. **세 번째 후보(SEMI)는 시도조차 못 한다** — 데이터 자체가 무료로 없다.
3. **네 번째 후보(WSTS)는 시도해도 정보 가치가 낮다** — 이미 두 번 반증된
   같은 종류의 변수를 세 번째로 다시 보는 것이라, 유의한 결과가 나와도
   "독립적 확증"이 아니라 "같은 가설의 반복 탐색"에 가깝다(다중검정
   문제를 더 키우는 방향).

## 4. 판정의 정확한 범위 — 중요

**이 REJECT는 "반도체 산업 사이클이 SOXL과 무관하다"는 뜻이 아니다.**
정확히는:

> **"공개적으로 안정 확보 가능한 반도체 기업·산업의 매출/판매 실적
> 성장률 지표만으로는, SOXL의 향후 1~6개월 수익률을 예측할 수 있다는
> 증거를 찾지 못했다."**

시험하지 않은 것(즉 이 REJECT가 덮지 않는 영역):

- DRAM/NAND/HBM **가격**(수요·공급 자체가 아니라 가격 수준·변화)
- CapEx 가이던스·주문잔고(ASML bookings/backlog, 장비사 수주)
- 재고 수준·재고/매출 비율
- 이번에 시도 못 한 SEMI Billings의 유료 경로(가입 비용 발생, 별도 판단 필요)

이 구분을 남기는 이유는 나중에 위 데이터 중 하나가 새로 무료로 열리거나
확보되면, 그건 **이 REJECT를 뒤집는 게 아니라 별도의 새 가설**로
취급해야 하기 때문이다(교훈61과 같은 원칙 — 다른 종류의 증거는 기존
판정과 별개로 평가한다).

## 5. SOXL 연구의 방향 정리

```
❌ 산업 실적 기반 레이어(삼성/SK하이닉스 → TSMC → WSTS → SOXL)  — 종료
✅ 가격/시장구조 기반 레이어(SOXL/SMH/QQQ 추세·모멘텀·drawdown·변동성)
   — 기존 무한매수법 국면결합(1a QQQ 50SMA 스위치) 라인과 자연스럽게 연결,
     이쪽으로 복귀
```

산업 사이클을 억지로 얹은 "Semiconductor Cycle Score" 같은 합성 지표를
만들지 않는다 — 지금까지 실측이 그 방향에 신호가 없다고 세 번 말해줬다.

## 6. 재개 조건

- DRAM/NAND/HBM **가격** 데이터(현재 이 저장소엔 없음, 대부분 유료)를
  무료로 확보할 새 경로가 생기면.
- ASML bookings/backlog, 장비사 주문잔고 같은 **주문 기반**(실적이 아닌
  선행 지표) 데이터를 시도하고 싶다는 새 가설이 생기면 — 단 이것도
  "매출 성장률"류가 아니라 정말 다른 메커니즘(선행 주문)이어야 재개
  사유가 된다.
- SEMI Billings 유료 접근을 실제로 고려할 상황이 되면(별도 비용 승인
  필요, 이 연구축과 별개 결정).

## 6b. 후속 — 가격(PPI) 축도 같은 날 시험·종료 (2026-09-13 추가)

이 문서가 열어뒀던 "가격" 후보를 바로 이어서 시험했다 —
[infinite-buying-soxl-semiconductor-ppi-pilot-2026-09-13.md](infinite-buying-soxl-semiconductor-ppi-pilot-2026-09-13.md).
FRED `WPU1178`(반도체 PPI, 1965~2026, 무료·무가입, n=198)로 동일 배터리
(Spearman+HAC+비중첩+분위수+전환이벤트)를 돌렸으나 **동일한 반증 패턴**이
나왔다 — naive 전부 무의미, HAC에서 딱 하나(ppi_yoy_accel/1개월,
p=0.001) 유의했지만 다른 horizon·다른 검증에서 전혀 안 받쳐줘 다중검정
잡음으로 판단, 상승/하락전환 이벤트 수익률이 방향 무관 거의 동일(TSMC와
같은 모양). 커밋 전 독립검토에서 "WPU1178이 FRED 블로그 인용 표준계열"
이라던 근거가 틀렸다는 게 드러나(실제 인용 계열은 산업기준 `PCU3344133441`)
그 계열로도 재검증했고, 결과는 동일했다(HAC p=0.012, 나머지 전부 무의미
또는 반증). **DART(기업매출)·TSMC(산업매출)·PPI(가격, 2계열) 전부
REJECT로 수렴**했다 — 이 문서 §6이 열어뒀던 유일한 후보(가격)까지
남은 구멍 없이 닫혔으므로, 남은 재개 조건은 위 목록 중 DRAM/NAND 현물가·
주문기반 지표뿐이다.

## 7. 관련 문서

- [infinite-buying-soxl-semiconductor-cycle-feasibility-2026-09-13.md](infinite-buying-soxl-semiconductor-cycle-feasibility-2026-09-13.md)
- [infinite-buying-soxl-semiconductor-cycle-dart-pilot-2026-09-13.md](infinite-buying-soxl-semiconductor-cycle-dart-pilot-2026-09-13.md)
- [infinite-buying-soxl-tsmc-monthly-revenue-pilot-2026-09-13.md](infinite-buying-soxl-tsmc-monthly-revenue-pilot-2026-09-13.md)
- [infinite-buying-soxl-semiconductor-ppi-pilot-2026-09-13.md](infinite-buying-soxl-semiconductor-ppi-pilot-2026-09-13.md)
- [infinite-buying-regime-hybrid-2026-09-12.md](infinite-buying-regime-hybrid-2026-09-12.md) — 복귀할 가격/시장구조 라인
