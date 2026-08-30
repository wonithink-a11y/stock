---
track: kr
factor: github-strategy-sources-usability
date: 2026-08-26
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "GitHub 전략 저장소 10개 팩트체크(gh api 전수 일치)+활용성 A~D 등급 - Qlib TopkDropout가 유일한 실참고 가치, 채택 서열·다음 실험 후보 제시(조사)"
---
# GitHub 전략 저장소 활용성 조사 — Ox Alpha 산출 + Claude 검증 (2026-08-26)

Ox Alpha(OpenCode, `opencode/x-preview-f-free --variant max`)가 "GitHub에
실제 코드가 있고 Star/Fork가 많으며 전략 로직을 확인할 수 있는 프로젝트"
기준으로 10개 저장소를 조사했고, Claude가 `gh api`로 전수 재확인했다
(생산자·검증자 분리, `AGENTS.md` §5).

## 검증 결과 — GitHub 팩트체크(10개 저장소 전수, 2026-08-26 `gh api` 직접 확인)

| 저장소 | 주장 | 실측 | 판정 |
|---|---|---|---|
| freqtrade/freqtrade-strategies | 5,394⭐ | 5,394⭐ | 일치 |
| microsoft/qlib | 47,930⭐ | 47,930⭐ | 일치 |
| freqtrade/freqtrade | 53,624⭐ | 53,624⭐ | 일치 |
| mementum/backtrader | 22,959⭐, "마지막 의미있는 커밋 2023-04" | 22,959⭐ · 실제 커밋 로그 최종 2023-04-19("Version 1.9.78.123") | 일치(레포 API의 `pushed_at`은 2024-08로 나오나 태그 등 다른 ref push로 확인 — Ox Alpha가 표면 지표가 아니라 커밋 히스토리까지 확인했다는 뜻) |
| nkaz001/hftbacktest | 4,478⭐, 활동 중 | 4,478⭐, 2025-12 push | 일치 |
| aws-samples/algorithmic-trading | 289⭐, "4년 방치" | 289⭐, 마지막 push 2022-08 | 일치 |
| letianzj/quanttrader | 765⭐, "2년 정체" | 765⭐, 마지막 push 2024-06 | 일치 |
| jesse-ai/jesse(본가) | 8,377⭐ 활발 | 8,377⭐, 2026-08-19 push | 일치 |
| cryptofish7/jesse(원 ChatGPT류 분석이 링크한 것) | "⭐0 포크 — 본가 아님" | 정확히 0⭐/0포크 | 일치 — 원본 분석이 놓친 오류를 정확히 잡아냄 |
| Erfaniaa/crypto-trading-strategy-backtester | 99⭐, "3년 방치" | 99⭐, 마지막 push 2023-09 | 일치 |

Qlib `TopkDropoutStrategy` 코드도 직접 열어 확인 — `topk: 50`, `n_drop: 5`,
백테스트 기간 `2017-01-01~2020-08-01`(CSI300) 전부
`examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml`
원본과 정확히 일치.

이 프로젝트 내부 인용(V3 Sharpe 1.20→CAGR -4.05%, PBR +7.06%→+2.95%,
LOWMOM60 +13.90%→+5.09%, Opening Fade TRAIN t=2.6~3.1→TEST t=-3~-4,
REV20 +6.7%→-11~-13%, CAND1 21.43bp→1.48bp)도 CLAUDE.md 상태블록 원문과
전부 일치.

**검증 못 한 것**: 대만 데이트레이더(<1%)·브라질 선물(97% 손실) 등 학술
논문 인용 수치는 원문 대조를 안 했다 — 방향성은 알려진 문헌과 일치하나
정확한 %까지 재확인은 안 됨. "미검증"으로 남긴다.

## 이 프로젝트 사용가능성 판정 (Ox Alpha 원안 + Claude 승인)

```
A급 - 실제 참고 가치
  Qlib: TopkDropoutStrategy(topk/n_drop 방식) + Alpha158 팩터 목록
        우리 구조(Factor→Score→Top-K→Portfolio→비용반영)와 같은 계열

B급 - 아이디어 공급원(로직 그대로 이식 불가, 가설만 참고)
  freqtrade-strategies, Backtrader samples
        암호화폐/미국종목 기술적 조합 - 이미 이 프로젝트가 유사 계열
        (TREND-BREAKOUT-v1, V3 Bollinger+RSI)을 전체 유니버스로 검증해
        기각한 전례가 있어 추가 가치 낮음

C급 - 데이터 축이 없어 원리적으로 불가
  hftbacktest: 호가창(L2/L3) 데이터가 이 프로젝트에 없음(분봉도
        249영업일뿐) - 장기 로드맵 항목으로만 남김

D급 - 방치되었거나 구조가 안 맞아 제외
  aws-samples(4년 방치)·quanttrader(2년 정체)·Erfaniaa(3년 방치)·
  Jesse(BTC 선물 전용, LONG_ONLY 현물 엔진과 안 맞음)
```

## 실전 성공확률에 대한 학술 근거(방향성만 확인, 정확한 % 미검증)

대만 데이트레이더 15년 전체 거래 데이터 기준 순수익 지속자 <1%, 브라질
선물 신규 트레이더 300일 지속자 중 97% 손실 등 — 리테일 단기매매 전략의
구조적 실패율이 높다는 문헌과, 이 프로젝트가 자체적으로 반복 관측해온
"오프라인 사전점검 → 실엔진 → OOS에서 침식·반전"(PBR·LOWMOM60·Opening
Fade·REV20·CAND1 전부 해당) 패턴이 방향적으로 일치한다.

## 결론 — 채택 서열

1. Qlib TopkDropout의 n_drop(부분 교체) 메커니즘 — 이 프로젝트 PBR/
   LOWMOM60가 아직 안 써본 진짜 새 축(아래 "다음 실험 후보" 참고)
2. freqtrade-strategies 조건 조합 — 가설 spec으로만, 전체 유니버스
   검증 없이는 채택 안 함(V3 전례)
3. Backtrader samples — TREND-BREAKOUT-v1으로 이미 같은 계열 검증
   완료, 추가 가치 낮음
4. hftbacktest — 데이터 없음, 장기 로드맵
5. AWS/QuantTrader/Erfaniaa/Jesse — 제외

## 다음 실험 후보 (착수 전, 별도 확인 필요)

`strategies/pbr_value_v1/build_selection.py`·`lowmom60_v1`의 실제 선정
로직을 확인한 결과 **매달 순수 top-N 하드컷**만 쓰고 있고(전월 보유
여부를 전혀 안 봄), Qlib이 쓰는 "매달 일부만 교체"(dropout) 방식은
이 프로젝트에 아직 없다 — 흉내가 아니라 진짜 새 축이다.

가설: 매달 top-N을 통째로 새로 뽑는 대신, 기존 보유 중 순위가 가장 낮은
n_drop개만 교체하면(Qlib topk=50/n_drop=5 관례) 회전율·거래비용이
줄어 net 성과가 개선될 수 있다. PBR·LOWMOM60 둘 다 이미 월별 리밸런싱
인프라가 있어 selection 생성 로직만 바꾸면 되고, 새 데이터·시크릿
불필요.
