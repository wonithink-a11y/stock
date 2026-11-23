---
track: us-kr
factor: idiosyncratic-crash
date: 2026-11-24
verdict: PREREGISTERED
lane: C
criteria_version: RP-2.1
conditions: ["국내 확인 = KRX 2010-01~2016-01 홀드아웃(krx-pbr-history/daily, 폐지 포함) 유동 500, 사건 2010-02~2015-10 (63일 결과가 2016-01 안)", "미국 확인 = S&P500 PIT 2006~2015 패널(us_pit_pre2016 panel, 커버리지 ≥ 95% 게이트), 사건 2007-01~2015-09", "정의·결과·검정은 E 와 동일(idio_crash.py --confirm kr|us), 방향 국내 < 0 · 미국 > 0, 단측 월 군집 t p ≤ 0.05 각각", "E 에서 그 표본이 통과한 경우에만 그 표본의 C 를 판정한다(아니면 기록 전용)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 종목 고유 급락 뒤 63일(E: idio-crash-explore-prereg-2026-11)을 탐색과 겹치지 않는 구간에서 시장별 단일 검정.
---

# 종목 고유 급락 — 확인(C) 사전등록 (2026-11-24)
동결. 국내 홀드아웃은 RP-2.1 상 C 전용 — 여기서 처음으로 이 가설에 연다. 미국은 Tiingo 2006~2015 수집 완료 뒤.
확인돼도 점수·매매·알림 반영은 🔴 별도 GO.
