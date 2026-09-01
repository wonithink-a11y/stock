# CLAUDE.md — 주식 스코어링·모니터링 프로젝트

Claude Code가 매 세션 자동으로 읽는다. **길어지면 매 요청의 토큰 비용이 된다.**
여기에는 매번 지켜야 할 규칙과 현재 트랙만 둔다. 나머지는 아래 지도에서 찾아 읽는다.

```
Validated against
  정책      UN-1.2 · PR-1.6 · FN-1.6 · REG-1.6 · MN-1.2 · SB-1.0 · SD-1.0
  현재 트랙  A3c·T1·A2b·A4 전부 종료됐다(아래 완료 참고) — A3c는 finalize 완료
               (2026-08-16, a997f9a), T1은 REPRODUCIBILITY FAIL(PASS 아님),
               A2b는 PR-1.6(480/440/20%) 전량 재실행 finalize 통과
               (2026-08-17, manifest 88d5756), A4는 종목별 일별 수급 전량
               finalize 통과(2026-08-18, manifest 74ac94e). 다음 항목 참고
  다음      PBR 연구 라인 종료(당분간) — **"연구 가치 있는 factor 후보,
            production alpha 확정 아님"**으로 최종 분류(2026-08-22,
            세션인수인계-2026-08-22.md). 겹침판정 수정(e526cf8)·연속보유
            병합 옵션(9d755c1) 둘 다 커밋 완료 — 지난 세션이 미룬 "다음
            세션이 고를 것"은 해소됐다. 그 뒤 실제 엔진으로 MTM(월별
            시가평가) 재계산하니 이전에 인용하던 Sharpe 2.25·MDD -10.5%가
            착시였음이 드러나 **Sharpe 0.46·MDD -21.7%**(CAGR +4.72%, EW
            벤치마크 대비 +1.68%p)로 정정됐다. 이어서 그 +1.68%p 우위를
            로그수익률로 연도분해하니 **2022년 단 한 해가 전체의 98.6%**
            였고(나머지 9.6년 합산은 사실상 0), 2022년 원인을 업종 데이터로
            분해하니 저PBR/고PBR 버킷이 거의 교과서적인 가치주/성장주
            업종분할과 일치(2022년 전세계 금리인상기 성장주 셀오프와 겹침).
            섹터중립 재검증(업종 내부에서만 PBR 랭킹) 결과 신호는 살아있지만
            (3구간 전부 부호 유지) 크기는 대략 절반, **가장 최근 구간(OOS
            2023-2026)의 within-sector IC가 t=1.94로 통상 유의성 기준
            바로 아래**다. 추가 스윕(비용·topN·유동성·구간분할)은 이미
            여러 번 반복돼 여기서 중단 — 재개하려면 목적이 "PBR이 좋은가"가
            아니라 "이미 확인된 신호를 실제 포트폴리오로 구현했을 때
            거래비용·MTM·현금타이밍·회전율을 다 반영하고도 경제적 가치가
            남는가"로 바뀐다. 선결 조건: `pbr_value_v1/`(policy.json
            포함, 여전히 로컬 미커밋)의 재현성 사슬 완성(`valuation-
            panel.jsonl` 커밋 또는 산출 스크립트 정리). LOWMOM60+기관수급
            (ChatGPT A/B/C) — **완료(아래 완료 참고, 2026-08-24)**. 실제로
            검증까지 끝난 건 후보 C뿐이라는 걸 확인해 C만 구현 —
            실제 엔진 CAGR +5.09%(사전점검 +13.90%보다 낮음, PBR과 같은
            패턴). "연구 후보, production 미확정"으로 PBR과 동일 분류.
            A2b 소비 단계(priceSource.js PRIMARY 연결·043090
            처리·Core 백필)도 여전히 미착수(아래 "착수 가능" 참고, 우선순위
            미정). ★ 2026-08-23 후속 — Macro Regime Layer(아래 완료 참고)로
            "PBR이 왜 좋았나"를 다시 열었다. 미국 10년물(usTreasury10y)
            trailing 6개월 변화 축이 **2022년을 빼도 방향이 유지되는
            유일한 축**(한국 국고채·신용스프레드는 2022년 하나로만 설명,
            제외 시 부호 반전) — PBR 분류를 "가치주 노출"에서 "미국
            장기금리 상승기 조건부 가치주 노출"로 좁혔다. 단 이걸 **실제
            진입 타이밍 필터로 구현하면 오히려 나빠진다**(CAGR +4.72%→
            +2.26%, Sharpe 0.4556→0.3293, Calmar도 악화 — 2022년 PBR
            자신의 절대수익은 -2.38%로 마이너스였고 EW가 더 나빴을 뿐이라,
            "상대적 우위를 설명하는 축"과 "타이밍 필터로 쓸 축"은 다른
            질문임을 확인). CAND1은 같은 축에서 PBR과 정반대 방향(단
            데이터 창 1년이라 약한 증거), Opening Fade는 무관(설명력 없음,
            PF 전 구간 1.00~1.01). PBR 최종 분류("연구 후보, production
            alpha 미확정")는 안 바뀌었지만 진입 필터 경로는 완전히 닫혔다.
            ★ 2026-08-23 후속 2 — 이진 필터 대신 **비중을 연속으로 조절**
            하는 방식(exposure_frac(scalar)로 매달 top-K 컷, 레버리지 없이
            0x~1.0x)을 시도(엔진에 마진 개념이 없어 1.5x 확대는 공유 엔진
            변경 필요 — 사용자 확인 후 축소만으로 범위 한정). 이진 필터보다
            확실히 낫다(CAGR -0.29%p, 이진필터 -2.46%p보다 훨씬 작음·MDD
            -21.70%→-17.49%·Calmar 0.2175→0.2533 개선) — 그러나 Sharpe
            개선은 +0.0047로 사실상 오차범위이고, 2022년 사례에서 "비중
            축소" 효과와 "PBR 랭킹 하위 컷에 의한 구성 변화" 효과가 뒤섞여
            해석에 잡음이 남는다. 여전히 "연구 후보, production 결정 보류"
            — 채택 사유로 확정하지 않는다. findings/pbr-sizing-macro-
            continuous-2026-08.md
            ★ 2026-08-24 후속 3 — 사용자 지시로 그 잡음(노출효과 vs 구성효과)을
            분리 검증. **구성을 baseline과 100% 동일하게 고정**하고 이미
            계산된 baseline 월간수익률에 exposure_frac(scalar)만 곱하는
            순수 오버레이(랭킹컷과 같은 exposure_lookup() 재사용, 새
            selection.json 없음, 엔진 무변경)로 다시 측정한 결과 **개선이
            사라졌다** — CAGR +4.72%→+2.65%, Sharpe 0.4556→0.3976,
            Calmar 0.2175→0.2146(둘 다 baseline보다 악화). 랭킹컷과 오버레이
            둘 다 평균노출이 거의 같은데(47.5% vs 46.8%) 성과가 크게
            갈린다는 것 자체가 08-23의 "개선"이 타이밍이 아니라 **랭킹컷이
            노출을 줄일 때 항상 PBR 하위부터 빼서 우연히 "더 타이트한 저PBR
            스크리닝"이 된 구성 효과(기존 decile IC t=6.30 재확인)**였음을
            보여준다. **타이밍/사이징 경로는 이진·연속 둘 다 이제 닫혔다**
            — 다음에 이 방향을 열려면 "언제 살까"가 아니라 "topN 자체를
            줄이는 독립적인 팩터 강도 실험"이라는 별개 질문이 된다(이번
            범위 밖). findings/pbr-exposure-overlay-vs-ranking-cut-2026-08.md
            (커밋 `67f5517`, push 완료)
            ★ 2026-08-24 후속 4 — overnight OpenCode(opencode/x-preview-f-free
            무료 티어, 병렬 3job) 확장으로 "이미 검증된 전략 × 아직 안 써본
            축" 조합을 마저 채웠다. LOWMOM60+기관수급 10축 전체(job1) —
            미국10Y·신용스프레드만 유의미, KOSPI 강한 역방향. PBR/CAND1/
            OpeningFade 미검증 6축(job2) — **한국 일반순환지수**가 세 후보
            모두에서 유의미(부호는 제각각). TREND-BREAKOUT-v1·5DC-v1A-P
            10축 전체(job3) — 미국10Y+신용스프레드 클러스터에서 PBR·
            LOWMOM60과 **정반대 방향**(추세추종 vs 가치·역모멘텀 성격 차로
            설명됨). 부수: job3 도중 `engine/portfolio/portfolio.py`에서
            `KeyError` 발견 → 원인은 `pbr_vs_ew_monthly_mtm.py`(연구용 복제
            스케줄러)가 `engine/runner.py`의 2026-08-22 `exit_symbols_queued`
            가드를 반영 못 한 옛 버전이었던 것(engine 자체는 무결함). Claude가
            직접 수정 후 PBR baseline 재실행으로 완전 무변경 확인(closed=756,
            CAGR 4.72%, MDD -21.70%, Sharpe 0.4556 — 소수점까지 일치, 오늘
            세션 PBR 결과 전부 안전). OpenCode도 독립적으로 같은 원인을
            진단해 자기 스크립트 안에 로컬로 같은 가드를 구현 - 교차검증됨.
            findings/overnight-macro-regime-cross-candidate-synthesis-2026-08.md
            · pbr-vs-ew-monthly-mtm-exit-dedup-fix-2026-08.md(커밋 `839a54e`)
            ★ 2026-08-24 후속 5 — 후속4가 찾은 "TREND-BREAKOUT-v1·5DC-v1A-P는
            미국10Y hiking에 불리"라는 상관관계에 후속3과 같은 순수노출
            오버레이 방법론(부호만 반전) + **상수노출 대조군**(신규, 평균
            노출을 오버레이와 동일하게 맞춰 디레버리징 효과와 타이밍효과를
            분리)을 적용. **TREND-BREAKOUT-v1은 타이밍가치 없음**(순수
            타이밍가치 CAGR -0.55%p·Sharpe -0.0599 — baseline 대비 개선처럼
            보였던 건 전부 평균노출 53% 축소라는 디레버리징 효과였다).
            **5DC-v1A-P는 작지만 진짜 타이밍가치 존재**(CAGR +0.52%p·
            Sharpe +0.0423, 세 지표 다 대조군보다 우수) — 단 baseline·
            오버레이·대조군 셋 다 여전히 깊은 마이너스(-5%~-11%)라 손실
            완화 신호이지 수익 신호는 아니다. PBR에서 이미 확인한 "상관관계
            ≠ 타이밍가치" 교훈이 재현됨. findings/trendbreakout-5dc-exposure-
            overlay-timing-value-2026-08.md(커밋 `f7e3ab5`, 전부 push 완료)
            ★ 2026-08-24 후속 6 — 같은 분리검증을 LOWMOM60+기관수급에도 적용해
            **PBR·TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60 4개 후보 전체의 미국10Y
            타이밍가치 분리검증을 완결**했다. LOWMOM60은 순수 타이밍가치
            CAGR +1.90%p(4개 후보 중 가장 큼)이지만 **MDD는 오히려 악화**
            (-6.73%p)돼 Calmar 기준으로는 상수노출 대조군이 더 낫다(0.4144
            vs 오버레이 0.3819) - "고위험-고수익" 트레이드오프가 그대로
            드러남, 지표별로 결론이 갈려 순채택 근거 아님. **4개 후보 중
            어느 하나도 모든 위험조정지표에서 명확히 이기지 못했다** -
            이 축(미국10Y trailing 6개월)을 타이밍/사이징 규칙으로 쓰는
            방향은 이제 4개 후보 전부에서 닫혔다. "발견한 축을 필터로
            만들기 전에 디레버리징 대조군으로 분리검증한다"는 절차가 이번에
            4번 반복 검증돼 이 프로젝트의 표준 절차로 굳어졌다.
            findings/lowmom60-exposure-overlay-timing-value-2026-08.md
            ★ 2026-08-26 후속 — Ox Alpha(OpenCode, opencode/x-preview-f-free
            --variant max) 조사(GitHub 전략 저장소·학술 문헌)를 Claude가
            gh api·WebSearch로 재검증(생산자·검증자 분리, AGENTS.md 원칙)한
            뒤, 그 조사가 찾은 새 축 하나(Qlib TopkDropoutStrategy의 회전율
            제한)와 학술 후보 하나(Nartea/Wu/Liu 2014 MAX효과)를 PBR에 신규
            실험. **dropout**(매달 top-30 전체 재선정 대신 전월 보유 최하위
            3개만 교체) — CAGR +0.64%p(4.72%→5.36%)·Sharpe +0.0345·MDD 개선,
            회전율 -40.6%. **MAX제외**(top-30 중 그 달 MAX5 상위 20% 대체
            없이 제외) — CAGR **+0.95%p**(→5.67%)·Sharpe **+0.1258**(4개
            실험 중 최대)·MDD 개선, 거래건수는 늘었는데도 net 개선(회전율
            효과가 아니라 "MAX 상위 종목 자체가 나쁜 편입"이라는 방향).
            둘 다 1회 실행·단일 파라미터만 테스트 - 채택 근거 아님.
            findings/pbr-dropout-turnover-limit-2026-08.md ·
            pbr-max-exclusion-2026-08.md · github-strategy-sources-
            usability-2026-08.md · github-literature-return-enhancement-
            candidates-2026-08.md(업종모멘텀 인용은 실제 최신 논문과 정반대
            결론이라 기각, MAX·PEAD는 원문 대조로 확인)
            ★ 2026-08-26 후속2 — 위 두 실험의 공통 한계였던 "T1/T3(대형주)
            분해 안 함"을 확인. 절대임계값(turnover20>=1억원)으로는 PBR
            자체가 이미 유동성 필터를 거친 선별 유니버스라 거의 전부(98~99%)
            가 고유동성 쪽으로 잡혀 표본이 희박(T1 6~10건) - 참고용. 전략이
            실제로 고른 거래 내 상대 tercile(하위/상위 33%, 이미 고정된
            거래집합의 사후 진단이라 tercile을 필터로 쓸 때의 오염 문제와는
            다름, 표본 150~295건)로 재분해한 결과 **둘 다 문헌이 경고한
            "소형주에서만 플러스, 대형주에서 반전" 패턴이 아니다**(부호
            반전 0건). dropout은 T1·T3 둘 다 개선되고 오히려 T3에서 개선폭이
            더 큼(+7.63%p vs T1 +3.83%p). MAX제외는 평균수익률은 두 버킷
            다 baseline과 거의 같으나(-0.3~0.6%p) 승률이 둘 다 개선(+0.6~
            1.9%p) - Sharpe 개선이 평균수익 상승이 아니라 승률/꼬리위험
            축소에서 온다는 뜻. findings/pbr-dropout-maxexcl-t1t3-
            decomposition-2026-08.md
            ★ 2026-08-26 후속3 — dropout·MAX제외 결합 실험(세션인수인계
            §5-1, "단순 합산 가정 금지"). `pbr_value_v1_combined`(dropout의
            매달 보유목록 위에 maxexcl과 동일한 MAX5 상위20% 제외를 한 겹 더
            적용, 순서 고정 - MAX제외를 먼저 하면 dropout의 nDrop 예산 계산이
            달라짐) 결과 **세 지표 전부 단순 합산보다 더 큰 개선**(초가산적) —
            CAGR 단순합산 +1.59%p vs 실제 +2.15%p(+0.56%p 초과), Sharpe
            단순합산 +0.1603 vs 실제 +0.2253(+0.065 초과), MDD도 개별 최선
            (maxexcl -20.80%)보다 combined(-18.90%)가 더 낮음. 상쇄가 아니라
            증폭 - 두 필터가 서로 다른 축(회전율 대 종목별 복권효과)으로
            같은 풀을 걸러내며 상호보완적으로 작동한 것으로 해석.
            findings/pbr-dropout-maxexcl-combined-2026-08.md
            ★ 2026-08-26 후속4 — 위 결합 실험이 nDrop=3·percentile=80% 단일
            조합에서만 나온 것인지 파라미터 스윕(nDrop∈{2,3,5}×percentile∈
            {0.7,0.8,0.9}, 9격자)으로 확인. 스윕 인프라 첫 버전에 버그
            발견·즉시 수정(MAX5 제외 임계값을 "그 달 보유 30종목" 내부에서
            계산하던 것을 원래 정의인 "그 달 적격 유니버스 전체 ~800종목"
            기준으로 고침 - 수정 후 (3,0.8) 재현치가 기존 결합 실험 결과와
            소수점까지 일치해 인프라 정확성 확인). **결과: 시너지(초가산적
            효과)는 nDrop 전체에서 재현**(naive_sum 대비 초과분 nDrop=2
            +0.27%p·nDrop=3 +0.56%p·nDrop=5 +0.18%p, 전부 양수) - "결합이
            상쇄되지 않는다"는 견고하나 "얼마나 증폭되는가"는 파라미터
            의존적. **percentile=80%가 세 nDrop 전부에서 국소최적**(70%·
            90%보다 항상 나음) - 임의 선택이 아니었음을 확인. 단
            **nDrop=3은 이 격자에서 최선이 아니었다** - nDrop이 낮을수록
            (회전율을 더 강하게 제한할수록) dropout 단독 CAGR이 단조
            증가(nDrop=2 6.52%>3 5.36%>5 4.84%), **nDrop=2+pct=0.8
            조합(CAGR 7.74%·Sharpe 0.7406)이 스윕 전체 최선**(MDD만
            nDrop=3·pct=0.8가 근소하게 더 나음). 격자가 3×3으로 좁고
            (nDrop<2·percentile 극단값 미확인), 여전히 OOS 미검증이라
            이 사후적 최적 파라미터 선택 자체에 look-ahead 위험이 있다 -
            바로 채택하지 않는다. findings/pbr-combined-paramsweep-2026-08.md
            ★ 2026-08-26 후속5 — PEAD(실적발표 후 드리프트) 착수 시도,
            착수 전 재확인에서 전제 자체가 틀렸음을 발견. Ox Alpha 조사가
            "데이터 매핑 타당(A3b·A3d·pitSelector.js)"이라 적어 뒀지만
            실제로 `data/backfill/fundamentals/a3b/`를 열어보면 fiscalYear당
            1건뿐인 **연간 EPS만 있다**(reprtCode 필드 자체가 없음 - A3c
            발행주식수는 분기 reprtCode 4종이 있는 것과 대조). A3d는 기업행위
            데이터로 실적발표와 무관. **표준 분기 PEAD는 이 프로젝트
            데이터로 재현 불가능** - "데이터 매핑 확인됨" 판정이 파일
            존재만 봤지 분기 단위 여부를 안 열어본 오류였음을 정정.
            완전히 막힌 건 아니라 보고 연간 SUE 대체판(Foster/Olsen/Shevlin
            1984 seasonal random walk)을 정찰했으나 **기각** - T+20 IC
            t=1.86(유동성필터 시 t=1.32, 통상 유의성 기준 미달)·T+60은
            신호 소멸(t=0.16~0.35), T+20 IC는 양인데 decile 스프레드는
            음이라 방향도 내부 불일치. 진짜 분기 PEAD를 하려면 DART
            분기보고서 손익계산서 신규 수집이 필요(별도 🔴 결정, 이번
            범위 밖). findings/pead-annual-precheck-2026-08.md
            ★ 2026-08-26 후속6 — 사용자 지시로 진짜(분기) PEAD 재시도. DART
            API를 실측(사용자가 세션에 키 제공, 파일 미기록)해 분기 단독
            실적을 누적값 차감 없이 바로 얻는 방법 확인 -
            `fnlttSinglAcnt.json`을 reprtCode=11012(반기)·11014(3분기)로
            조회하면 `thstrm_amount`가 이미 그 분기 단독값(반기report의
            thstrm_amount=Q2단독, 3분기report=Q3단독), `frmtrm_amount`도
            전년동기 단독값 - 삼성전자 2023 실측으로 Q1+Q2단독=반기누적,
            +Q3단독=3분기누적이 소수점까지 일치함을 확인. 유동성 상위
            100종목 로컬 파일럿(2,250콜, 실패 266건) 결과 **연간판과 정반대
            패턴** - 연간은 T+20이 강하고 T+60에 신호 소멸(t=1.86→0.16)
            했는데, 분기는 **T+20이 약하고(t=1.20) T+60에서 오히려
            강해진다(t=1.96, 통상 유의성 경계에 정확히 걸침)** - 시간이
            지날수록 드리프트가 커지는 이 모양이 PEAD 문헌의 고전적 그림에
            더 가깝다. 단 100종목·28개 공시월짜리 파일럿이라 "있다"고
            단정할 단계는 아니다. findings/pead-quarterly-pilot-2026-08.md
            ★ 2026-08-26 후속7 — 사용자 확인 후 전면 수집 착수(연구 전용
            스코프 - data/backfill/·GH Actions·정책 파일 없음, PBR의
            valuation-panel.jsonl과 같은 패턴, `research/strategy-lab/
            build_quarterly_earnings_panel.py` 커밋). 전체 25,531
            corp-year×3콜≈76,600콜, DART 일일한도(4만) 안전마진(3.6만)에서
            자동정지·재실행시 이어감(state 파일). 2~3회 실행(1~2일) 필요,
            착수 시점 기준 진행 중 - 완료 후 `analyze_pead_quarterly_oos.py`
            (TRAIN/VALID/TEST 60/15/25 시간분할, CAND1·Opening Fade와 같은
            원칙 - 파일럿의 "전체기간만 봄" 한계 해소, 부분패널로 코드
            경로 검증 완료)로 재검증 예정.
            ★ 2026-08-30 후속 — 전면수집 완료 확인 + OOS 검증까지 끝났음을
            뒤늦게 발견(당시 세션이 인수인계를 안 남기고 넘어감). state
            파일 실측: `doneKeys` 24,750개 = A3 그리드 전체(위 "25,531"은
            착수 시점 추정치였고 실제 그리드는 24,750, 2026-08-28 15:07
            마지막 갱신 이후 미해결 0건 — 부분 성공이 아니라 완전 종료).
            `analyze_pead_quarterly_oos.py`도 이미 그 완전한 데이터로
            실행 완료(65,048 quarterly records·2,912 tickers). **결론:
            기각.** IC 부호는 TRAIN/VALID/TEST 세 구간 전부 양(+)으로
            유지되나(REV20·Opening Fade가 겪은 "TEST 반전"은 없음),
            유의성은 TRAIN T+20(t=3.15) 하나뿐이고 나머지 5개 셀(TRAIN
            T+60·VALID·TEST 전부)은 t<2. 파일럿이 보였던 "T+60이 T+20보다
            강해진다"는 패턴도 전면수집에서는 재현 안 됨(오히려 정반대).
            TEST T+20 unfiltered는 IC(+)와 decile 스프레드(-)가 어긋나는
            내부 불일치까지 있음 — 연간판 기각 근거와 같은 결함. **PEAD는
            연간판·분기 파일럿·분기 전면수집 세 번 다 이 프로젝트 표준
            검증(TRAIN 최선이 VALID·TEST까지 유지)을 통과 못 해 최종
            기각으로 종결한다** — 이 라인은 더 이상 열지 않는다.
            findings/pead-quarterly-oos-validation-2026-08.md
            ★ 2026-08-26 후속8 — 수집 대기 중 Ox Alpha 엔진개선 제안 중
            역변동성 가중 시도. `engine/portfolio/portfolio.py`의
            `Portfolio.process_day()`에 opt-in `weights` 인자 추가(기본
            None=기존 동일비중/전액현금 동작 완전 불변, 회귀 143건 전체
            재통과 확인 - 다른 전략은 인자를 안 넘겨 무영향).
            pbr_value_v1_combined에 60일 변동성 역수로 가중한 결과
            **사실상 무승부** - CAGR 6.87%→6.68%(-0.19%p)·MDD -18.90%→
            -17.94%(+0.96%p 개선)·Sharpe 0.6809→0.6811(사실상 동일).
            전형적 위험-수익 트레이드오프일 뿐 어느 쪽 우위도 아니다 -
            단일 실행(60일 창 하나)이라 노이즈와 구분 안 됨, 결론
            안 냄. 버퍼랭크(2번째 제안)는 메커니즘이 문서에 없어 설계부터
            필요, 미착수. findings/pbr-combined-invvol-weighting-2026-08.md
            ★ 2026-08-26 후속9 — 사용자 지시로 버퍼랭크는 판단해서 스킵
            (dropout/nDrop과 개념적으로 같은 회전율제한 메커니즘이라 새로
            만들어도 이미 확인한 "회전율 낮출수록 좋다"는 결론을 다른
            방식으로 재확인할 가능성이 높다고 판단, Claude 자체 판단).
            대신 combined 파라미터 스윕(nDrop=2+pct=0.8이 최선)이 전체기간을
            다 보고 사후에 고른 것이라는 한계를 `run_pbr_combined_oos_
            validation.py`(커밋)로 검증 - CAND1·Opening Fade와 같은 원칙
            (TRAIN에서만 스윕, VALID·TEST는 고정 선택을 보고만 함)을 12격자
            전체에 적용. 월별 시가평가 128개월을 60/15/25分(TRAIN 2016-01~
            2022-06·VALID 2022-06~2024-01·TEST 2024-01~2026-08)로 분할.
            **결과: TRAIN에서 고른 최선이 전체기간 스윕이 골랐던 것과 정확히
            일치**(nDrop=2/pct=0.8) - 순전한 look-ahead 산물이 아님. **12격자·
            3구간 전부 Sharpe 양(+), 부호반전 0건** - 이 프로젝트가 REV20·
            Opening Fade에서 겪은 "TEST 반전" 패턴이 여기선 안 나타난다,
            지금까지 PBR 계열 실험 중 OOS 반전 위험이 가장 낮은 축. VALID
            (2022-06~2024-01)가 전 격자 공통으로 가장 약하고 TEST가 공통으로
            가장 강함 - 파라미터 문제가 아니라 구간 자체의 국면 효과. dropout
            +maxexcl·nDrop=2/pct=0.8은 "연구 후보"에서 "production 결정을
            실제로 고려해볼 후보"로 한 단계 상향 - 단 2022년 concentration
            문제를 이 검증이 직접 배제하진 않고, production 채택은 여전히
            별도 🔴 결정. findings/pbr-combined-oos-validation-2026-08.md
            ★ 2026-08-26 후속10 — 사용자 확인 후 마지막 관문 재확인: OOS
            통과가 "2022년 하나만 맞고 나머지는 소음"이라는 baseline의 옛
            문제(로그초과수익 98.6%가 2022 단독)를 combined도 그대로
            갖고 있는지. `pbr_combined_2022_concentration_check.py`(커밋,
            원 98.6% 계산 스크립트는 저장소에 안 남아있어 새로 짬)로 재계산
            - **98.6%→45.7%로 대폭 완화**됐으나 **2022+2024 두 해가 여전히
            초과분의 74.0%**(2022 45.7%+2024 28.3%). "1년 몰빵"에서 "2년
            몰빵"으로 개선된 것이지 완전히 분산된 건 아니다. 두 해 다
            매크로 레짐 연구가 지목한 "미국 10년물 조건부 가치주" 시기와
            겹침 - 근본 성격은 안 바뀌었을 가능성. **종합 판단: "production
            결정을 실제로 고려해볼 후보" 상향은 유지**(baseline보다 뚜렷이
            개선, OOS 반전 없음) - 단 "완전히 분산된 안정 알파"로 과장
            않음, 조건부(매크로 국면 의존) 성격 그대로 인지하고 판단할 것.
            findings/pbr-combined-2022-concentration-2026-08.md
            ★ 2026-08-26 후속11 — 사용자 제안("2022년 약세장에 방어적이면
            약세장 타이밍 신호로 쓰자")을 이 프로젝트 표준 절차(순수 노출
            오버레이+상수노출 대조군, PBR·TREND-BREAKOUT·5DC·LOWMOM60에
            이미 4번 적용한 방법)로 실제 검증. baseline(노출100%) CAGR
            7.74%·MDD -19.40%·Sharpe 0.7406 → 동적 오버레이(평균노출
            0.468) CAGR 3.83%·MDD -10.00%·Sharpe 0.6314 → 같은 평균노출
            상수 대조군 CAGR 3.70%·MDD -9.34%·Sharpe 0.7406(baseline과
            수학적으로 동일, 상수배율은 Sharpe 불변). **순수 타이밍가치
            (오버레이-대조군): CAGR +0.13%p(사실상 0)·MDD -0.66%p(대조군
            보다 나쁨)·Sharpe -0.1092(뚜렷이 나쁨) - 기각.** 2022년 평균
            노출이 실제로 0.922(전 구간 최고)였다는 것 자체는 사실이나,
            그 신호를 실시간 추종해도 그냥 디레버리징보다 나을 게 없다 -
            baseline PBR이 이미 겪은 "상관관계 ≠ 타이밍가치" 결론이 5번째
            사례(PBR·TREND-BREAKOUT·5DC·LOWMOM60·combined)로 재확인.
            combined의 production 후보 판단은 안 바뀜(오버레이 없는
            baseline combined 그대로가 여전히 검토 대상). findings/
            pbr-combined-exposure-overlay-timing-value-2026-08.md
            ★ 2026-08-26 후속12 — PBR/PEAD과 별개인 신규 팩터 후보 트랙
            시작. Ox Alpha(OpenCode)가 병행 세션에서 독자적으로 DD252
            (52주 고점 대비 낙폭, skip-1m, JT 관례) 팩터를 조사해 로컬
            산출물 3단계(정보력 발견→생존편향 재검증→전략화 설계, 전부
            미커밋 - Ox Alpha 규칙) + 부수 연구 4건(유동성·A4 유동성
            플로어·변동성/ATR·MACD 정보력, 전부 관측치 문서로 채택판단은
            Claude·사용자 몫)을 만들었다. Claude가 독립 검증(생산자·
            검증자 분리) - ①코드: `dd_252_skip1m` 계산이 종목별 shift
            뒤 종목구분 없이 rolling max를 거는 패턴이라 언뜻 경계오염
            버그로 보였으나, 토이예제+실제 A4 534만행 전체 재계산 대조로
            **최대오차 0.0 확인 - 버그 아님**(shift(21)의 결측구간이
            min_periods=232와 맞물려 구조적으로 오염 불가능). ②재현성:
            독립 재실행 결과가 기존 JSON과 바이트 단위 완전 일치.
            ③통계: 설계문서가 헤드라인으로 내세운 "일별 IC t=32.6·
            직교화 t=50.8"이 **자기상관 보정 없는 naive t**로 부풀려진
            수치임을 발견 - 같은 스크립트가 월별 decile 스프레드에는
            Newey-West 보정을 정확히 적용했으면서 일별 IC에는 빠뜨린
            내부 불일치. **신뢰할 수치는 NW보정 월별 스프레드 t=2.08
            (MERGED, d120)** - 통상 유의성 기준은 넘으나 "t=32~53"이 주는
            인상만큼 압도적이지 않음, PEAD 분기파일럿(t=1.96)과 비슷한
            급의 경계선 신호. **종합: 연구 후보로 유지, 단 확신도 재조정**
            - 신호 계산·PIT·재현성·생존편향·모멘텀독립성은 전부 정확히
            확인됐으나 강도는 문서 주장보다 약함. 실제 롱온리 백테스트
            (설계문서 §10, 비용포함)는 전혀 실행 안 됨 - 다음 단계.
            findings/dd252-skip1m-verification-2026-08.md
            ★ 2026-08-27 후속 — 실제 롱온리 백테스트 완료, **최종 기각**.
            사용자가 설계 최종 PASS 확정 후 6-cohort 격리 회계(단순
            maxHoldingSessions 아님, 사용자가 명시적으로 금지)로
            `strategies/dd252_v1_cohort/` 신설·구현(회전 경계 슬롯캡
            초과 버그 발견·수정, 미진입 6.0%→0.36%). Full backtest 겉보기는
            우수(CAGR 10.72%·MDD -27.77%·Sharpe 0.5872, 전부 EW벤치마크
            상회)했으나 구조분해에서 뒤집힘 — **2026(부분연도) 제외 시
            CAGR 6.26%로 벤치마크(6.49%)보다 낮아짐**(우위가 진행중
            부분연도 하나에 전부 의존), 초과수익의 93%가 불장 5개년에
            쏠려 국면 무관 구조적 alpha가 아니고 종목 집중도도 높음.
            연구 종결·production 후보 제외로 확정, 이 라인은 더 이상
            열지 않는다. findings/dd252-final-rejection-2026-08.md
  착수 가능  A2b 종료로 풀렸다. 순서 없음, 각각의 착수는 별도 사용자 승인이다
            ① **priceSource.js·043090 처리 둘 다 완료**(2026-08-24) —
              docs/BF-1.1-백필계약.md §2 "운영(A5o)/연구(A5) 분리" 확정에 따라
              **오늘 유니버스에 없는 폐지종목 가격은 A5o에 필요 없다**는
              재정의가 맞음을 코드로 재확인(`scripts/analyze.js`는 라이브
              가격을 별도 경로로 받고 A2a/A2b 백필과 무관). 실제 자리는
              BF-1.1 10년 역사적 백필의 가격 조회뿐 — `lib/a5/priceSource.js`
              신설(A2a 우선·A2b 폴백 통합 조회, findPrice·findCandles),
              `scripts/probe-bf11-vertical-slice.js`에 연결해 폐지종목
              (000060/메리츠화재해상보험, A2b 폴백)까지 실데이터로 검증 —
              resolver→score() 정상 도달(fundamental은 해당 corp의 A3가
              2016년분을 안 갖고 있어 정직하게 null, 버그 아님). 회귀
              `scripts/test-price-source.js`(9건) 신설, 전체 11개 파일
              재확인. **043090**(`survivorship-attribution-design/DESIGN.md`
              §6.4가 남긴 경계 사례 — A1b 소속인데 가격은 A2a에 전체 존재)도
              같은 A2a-우선 규칙으로 실측 확인(`findPrice('043090', ...)` →
              `source:'a2a'`) — 그 문서가 요구한 "병합 실행 시 소스 우선
              규칙 명시"를 이 모듈이 충족한다. **10년 전체 백필 자체는
              여전히 미착수**(이 항목은 그 첫 부품일 뿐, 우선순위 별도 결정)
            ② Strategy Lab PRIMARY **정식 승격 — 완료됨**(2026-08-24, 아래
              "완료" 참고). 세션인수인계-2026-08-16.md §5 끝이 남긴 두 가지
              (engine/runner.py의 A1A_ONLY assert 완화 · 병합 유니버스 실제
              배선) 전부 끝났다
            ③ 전체 2,579종목 249영업일 분봉 백필 — **완료**(수집 2026-08-23,
              GitHub 승격 2026-09-01). 로그에 "할 일 없다"(538회 스킵 후 종료)
              도달, EGW00201 누적 0건, 루프(`minute-backfill-loop.service`)는
              2026-08-20 23:16에 이미 정상 stop됨. ★ 2026-09-01 후속 —
              구 `stock` VM(`~/minute-raw`, git을 855ad14로 갱신·`oci`
              SDK 2.185.0 신규 설치 후)에서 `upload-minute-oci.py --all`로
              로컬 manifest 258개 전량을 OCI에 업로드(정합성 확인 — 결측
              0건), `promote-minute-manifest.yml`을 `--days 50` 배치
              5회(수동 트리거, 매 회 3~4분)로 나눠 승격 — **258개 중
              258개 전부 통과·거부 1건**(2026-08-17, 광복절 대체공휴일이라
              `rows:0`으로 정직하게 기록된 날 — 게이트가 설계대로 빈 parts를
              거부, 데이터 손실 아님). `data/backfill/minute/manifest/`에
              258개 파일 존재(2025-08-08~2026-08-31, 2026-08-17만 결측).
              일별 운영 cron(`minute-collect.timer`, `--days` 기본 3)과
              `minute-oci-upload.timer`(매일 18:00 KST)는 이 백필과
              무관하게 계속 정상 작동
            ④ A5-3 valuation/peg 연결(lib/a5/resolver.js, A2a 수정주가 ↔ A3b
              원본 EPS 조정 기준 정의) — A3c 완료(2026-08-16)로 데이터는
              열렸으나 아직 착수 안 함(TASKS.md A5-3). 2026-08-18 SB-1.0
              KR_4AXIS 정찰이 이걸 재확인했다 — valuation 결측이 단순 라벨링
              문제가 아니라 fundamental+technical만으로는 절대 규칙 1(커버리지
              60%)을 통과 못 한다는 사실을 발견했다(세션인수인계-2026-08-18-b.md).
              SB-1.0 KR_4AXIS 재개의 전제조건이 됐다. **★ D2 vs D4 방향 확정:
              D4**(2026-08-20, 사용자 GO, docs/A5-3-peg-조정기준-결정브리프.md
              §14) — GO-5(a)(b) 소표본 검증(KIS·KRX-native raw 교차확인 완전
              일치, 034020 권리락 정밀검증, 065170 복합사건·079650 조정
              메커니즘 확인)으로 D4의 핵심 불확실성 해소, D2 전량 수집
              (KRX-native 기준도 ~8.6시간급)은 비용 대비 이득이 낮다고 판단.
              **방향만 확정이고 구현(정책 스키마·resolver.js)은 별도 🔴 결정**
              이었으나 그 뒤 구현·A3d 백필·PIT 버그 수정까지 전부 끝났다
              (위 "완료"의 2026-08-20 A3d 신설·2026-08-21 PIT 버그 수정 항목
              참고). **★ A3d 실제 재수집도 완료됨**(2026-08-21, 사용자 확인
              후 트리거, manifest 커밋 `ca9cffd`) — 실제 산출물에서 방향모순
              0건 직접 재확인(split 261행·reverseOrConsolidation 161행).
              **★ featureRegistry.js peg/pbr available:true 전환도 완료**
              (2026-08-21, 사용자 확인 후) — `availableWeight().total`이
              0.65로 `minimumDataCoverage`(0.6)를 처음 넘었다(valuation
              availableFraction 0→0.5). scripts/test-a5-framework.js의 옛
              단정 2건(coverage<0.6·valuation 전부 불가)을 새 상태로 갱신,
              25개 회귀 스위트 전체 재확인. **★ V7 최종 수직 슬라이스도 완료됨**
              (2026-08-21, 커밋 `4e9716a`, 아래 "완료" 참고) — 이 항목(A5-3
              valuation/peg 연결)은 이제 전부 끝났다. 이 문단은 2026-08-23
              세션이 CLAUDE.md 갱신 누락(V7 완료가 상태블록에 반영 안 됨)을
              발견해 정정했다
            ★ minute.v1.json의 pendingT1 승격 — 🔴. T1이 답한 것만 승격한다.
              emptyResponseRetries는 T1이 못 답했다(관측 기회 0건, 실측기록 참조)
  언제든    perRelative(업종 PER 횡단면) — A5-3 부분 재개(아래) 이후에도 여전히
            미착수. 날짜별·업종별 PIT 중앙값 인프라가 새로 필요해 resolver.js의
            종목 단위 인터페이스에 안 맞는다. 🔴급 설계 결정, 백테스트 eligible
            표본이 3건뿐이라(LAB-4) 지금 열어도 검증할 데가 없어 급하지 않다
            LAB-2(FY2015 EPS 라벨링) 방향 보류 — 서두를 이유 없음(2026-08-12)
            BF-1.1(10년 Historical Backfill) — 원재료 완료, 소급 스코어 재현
            (data/backfill/scores/)은 여전히 미실행. 2026-08-12 최소 수직
            슬라이스(2016-04-08/005930)로 Universe→PIT→가격→resolver→운영
            score() 실데이터 연결 GO 확인(820f097). resolver.js↔scoringEngine.js
            필드명 불일치(fundamentals→fundamental)를 발견해 수정(7a4c00c,
            finalScore null→87.5 회복). peg가 A3c 완료로 열리면 다시 확인
            10년 전체 백필은 여전히 미착수, 우선순위 미정. ★ 2026-08-24
            착수 — A5 채점 백필(3,801종목×553주간 스냅샷)에 들어가기 전,
            A6 Primary 결론을 막는 GATE-EP-1(§6.4, A1b exitReason 100%
            UNKNOWN)부터 풀기로 순서를 정했다(A5는 계산량이 큰 다일짜리
            작업이라, 끝내놓고도 결론을 못 내는 상태로 남는 걸 피하려는
            판단). exitReason 복원 Tier A 완료 — 2026-08-16에 시도됐다
            폐기된 `dartModifyDate` 앵커(실제 폐지일과 수개월~수년 어긋남)
            대신, 그 이후(2026-08-17) A2b가 만든 `exitAtConfirmed`(가격
            데이터 기반 실측 폐지일)로 재설계. 이미 커밋된 A3d
            `mergerSpinoff.jsonl.gz`(A1a·A1b 전체 대상 기수집 공시)를
            시간축으로 대조하는 순수 로컬 조인만으로 **새 DART 호출 0건**
            으로 508종목 중 179종목(35.2%)을 MERGED로 분류(365일 창,
            결과를 보기 전에 고정). `scripts/build-exit-reason-
            overlay.py`(selftest 9건) 신설, `data/backfill/`에는 쓰지
            않음(규칙 4, 로컬 진단 전용).
            ★ 2026-08-24 후속 — Tier B(합병 외 사유) 완료. Tier B 대상
            329종목(exitAtConfirmed는 있으나 Tier A가 못 잡은 나머지)에
            새 DART `list.json`(pblntf_ty=I, corp당 1회, 366콜) 조회 —
            패턴을 짜기 전에 20종목 무작위 표본의 실제 report_nm을 먼저
            읽고 다섯 정규식(VOLUNTARY="자진상장폐지"·BANKRUPTCY="회생절차
            개시결정"/"부도발생"/"파산선고"(파산신청·파산신청기각은 결정된
            사건이 아니므로 제외)·AUDIT_OPINION="의견거절/의견부적정"·
            CAPITAL_IMPAIRMENT="자본잠식"·DELISTING_REVIEW_FAILED="상장적
            격성실질심사")을 고정. 329종목 중 69종목(21.0%, VOLUNTARY 22·
            DELISTING_REVIEW_FAILED 21·BANKRUPTCY 20·CAPITAL_IMPAIRMENT 5·
            AUDIT_OPINION 1) 분류. **핵심 발견 — KRX 공식 공시 템플릿이
            감사의견과 자본잠식을 한 제목에 합쳐서 낸다**
            (`"반기검토의견부적정,의견거절또는완전자본잠식사실발생"`) —
            title만으로는 어느 쪽이 실제 방아쇠였는지 못 가르는 56종목
            (17.0%)을 지어내지 않고 ambiguousAuditCapital로 남겼다(AUDIT_
            OPINION이 1건뿐인 것도 이 모호성 때문 — 실제로 드문 게 아니라
            대부분 이 56건에 섞여 빠졌다). 나머지 204종목(62.0%)은 창 안에
            다섯 신호 자체가 없음(noSignal) — SPAC 청산·투자회사 만기청산
            등 애초에 다섯 카테고리 밖일 가능성(표본에서 실제 확인:
            교보14호·케이비제18호기업인수목적, 아시아퍼시픽13호선박투자
            회사). `scripts/build-exit-reason-overlay-tierb.py`(selftest
            11건) 신설, `data/backfill/`에는 쓰지 않음(규칙 4).
            **GATE-EP-1까지는 아직 한참 멀다** — Tier A+B 합산해도 A1b
            1,223종목 중 248종목(20.3%)만 분류, UNKNOWN 975종목(79.7%)이
            남아 임계(5%)를 크게 초과한다. 낙관적으로 보고하지 않는다.
            ★ 2026-08-24 후속 2 — "GATE-EP-1을 이 접근으로 넘길 수 있는가"
            부터 먼저 재확인했다(A2b `_diagnostics.json` 실측, 새 DART
            호출 없음). exitAtConfirmed가 없는 715종목의 정확한 구성:
            591종목(48.3%, 전체 A1b의 절반 가까이)은 수집 구간(2014~2026)
            전체에서 KIS/KRX가 가격을 단 한 행도 안 준 것 — 앵커 자체가
            없어 Tier C를 아무리 설계해도 원리적으로 분류 불가능하다.
            122종목은 raw 가격은 수집됐으나 품질 게이트가 통째로 제외했고
            (UNADJUSTED_CORPORATE_ACTION 107·TRANSIENT_PRICE_SPIKE 15),
            그 raw 행 자체가 로컬에 없어(연도별 산출물은 이미 필터링 후
            값만 저장) 재수집 없이는 복구 불가. 2종목은 단순 네트워크
            예외. **결론: GATE-EP-1(분모 A1b 전체 1,223)은 이 방법론으로
            구조적으로 도달 불가능** — 591종목만으로 이미 5% 상한(61건)의
            9.7배다. 분모를 "가격 흔적이 있는 A1b"(630종목=508+122)로
            재정의하면 UNKNOWN이 79.7%→60.6%로 낮아지지만 **그래도
            임계를 12배 초과**(31건까지 낮춰야 통과, 남은 382건의
            91.9%를 새로 분류해야 함) — 재정의만으로 해결되지 않는다.
            정책은 변경하지 않았다(config/policies/exit.v1.json·
            BF-1.1-백필계약.md §6.4 그대로).
            ★ 2026-08-24 후속 3 — 재정의 자체를 보류로 확정했다(사용자
            판단, 새 DART 호출 없이 로컬 데이터만으로). **가격 흔적이
            없는 591종목의 80.2%가 dartModifyDate=2017 배치값 하나에
            몰려 있다**(가격 흔적 있는 630종목은 2017~2026에 16.2%로
            고르게 분산) — Group A 508종목의 실제 exitAtConfirmed가
            2014~2026에 고르게 퍼져 있어(2014~2015도 9.4%) 가격 수집이
            오래된 폐지도 정상적으로 잡는다는 게 확인됐으므로, 이 몰림은
            수집 결함이 아니라 **Group B가 수집 캘린더(2014-01) 이전에
            이미 사라진, 훨씬 더 오래된 폐지 종목이라는 뜻**이다. "가격
            흔적 있는 630종목만 분모로" 재정의하면 최근 폐지는 남고 오래된
            폐지는 조직적으로 빠진다 — **재정의 자체가 survivorship bias를
            재도입할 위험이 실측 확인됨**, 채택하지 않는다. 업종 축은 A1b에
            필드 자체가 없고 이름패턴 대체(8개 카테고리)로는 양쪽 다
            87~93% 미분류라 결론 근거가 못 됨 — 연도 신호가 이미 결정적이라
            업종 확인용 추가 DART 호출(최대 1,223콜)은 하지 않기로 함.
            **부수 발견 — 분류가 다 같은 무게를 갖지 않는다**:
            `exit.v1.json` mode를 보면 MERGED·SPINOFF·UNKNOWN은 전부
            exclude(A6 계산 기여 없음), BANKRUPTCY류 4종+VOLUNTARY만
            실손실을 표본에 반영한다 — Tier A의 MERGED 179건은 GATE
            수치는 낮추지만 실질적 편향 보정 기여는 0, 실제로 편향
            보정을 작동시키는 건 Tier B가 분류한 69건(5.6%)뿐이다. GATE를
            어떻게 재정의하든 이 사실은 안 바뀐다. **다음 판단은 이
            문서 밖 — "GATE-EP-1이 이렇게 막힌 상태에서 A5를 어떤 방식으로
            진행할 것인가"**(다음 세션). 참고: A5 스코어 계산 자체는 GATE와
            무관하게 실행 가능(GATE는 A6 Primary 결론에만 적용), Strategy
            Lab(PBR·5DC 등 지금까지 돌려온 백테스트 엔진)은 이 GATE·
            exit.v1.json과 무관한 별도 시스템이라 이번 트랙과 무관하게
            그대로 유효하다.
            ★ 2026-08-24 후속 4 — 위 참고사항("A5는 EP를 안 읽는다", §5
            계약)을 근거로 A5 착수를 GATE-EP-1과 분리하기로 사용자 확정.
            순서: exit overlay 설계 고정 → 20종목×52주 파일럿(2샤드,
            재개·결정성 검증) → 통과 시 overlay 계약 확정 → GH Actions
            본수집 설계 → 3,801×553주 본백필 → A6 진단 → EP-1/2 재평가.
            exit overlay(A5 baked-in exitReason과 별개로, Tier A/B/C가
            늘어나도 A5 재계산 없이 최신 분류를 반영하는 별도 파일 —
            오늘 만든 `build-exit-reason-overlay*.py`와 같은 패턴을
            정식화) 설계·파일럿 종목 선정 기준(무작위 금지 — 활성 8·
            Tier B분류 4·MERGED 2·UNKNOWN 6 최소구성, fwdStatus=EXIT
            실제 발생 구간 포함)까지 확정. 위임 경계도 정함 — 스키마·
            선정기준·fwd/fwdStatus 로직은 Claude. ★ 위임 경계를 사용자
            지시로 강화 — OpenCode는 단순 재실행/집계가 아니라
            `research/strategy-lab/a5-pilot-independent/`에 **독립
            재구현**을 작성해 Claude 산출물과 비교한다(exit_symbols_queued
            가드를 Claude·OpenCode가 각자 독립 구현해 교차검증한 선례와
            같은 패턴, AGENTS.md §4 "판단은 자동으로 안 고른다"를 그대로
            적용 — AGENTS.md 자체는 안 고침). 독립 구현 대상은 이번에
            새로 설계한 부분만(fwd/fwdStatus·샤드재개·overlay 조인) —
            resolve()·score()·priceSource.js는 이미 검증됐으니 둘 다
            읽기 전용으로 그대로 쓴다. A6이 overlay를 어떻게 읽을지는
            여전히 별도 🔴 결정(이번엔 안 다룸). ★ 2026-08-24 후속 —
            `scripts/build-a5-pilot.js` 구현·실행 완료(커밋 `3561202`).
            20종목×52주(1,040격자) 결과 793행, Tier B 4종목 d120 EXIT
            건수(11·10·9·26)가 설계안 §3.1 사전 실측표와 정확히 일치 —
            fwd/fwdStatus 로직이 맞다는 독립 신호. 실행 중 버그 둘 발견·
            수정: (1) `createWriteStream`+`process.exit()`가 버퍼 flush
            전에 종료해 "기록했다"는 진단과 달리 파일이 비어 있었다 →
            `appendFileSync`로 교체. (2) `noPriceAtAsOf` 스킵 분기가
            상태 파일 쓰기를 건너뛰어 재개 시 마지막 종목의 후행 스킵
            구간이 "미완료"로 재처리됐다(데이터 유실은 아님, 재개
            완결성 버그) → done.add+상태쓰기를 분기 공통 경로로 통합.
            SIGKILL 중단(156/520)→재개, 전체 재실행 바이트 동일성
            (결정성) 둘 다 확인 — 설계안 §4 요구 항목 전부 통과.
            listingStatus/exitReason/exitAt는 corp 상수(빌드 시점 A1b
            값)로 해석해 구현(설계안 §1이 명시 안 한 부분, A6이 실제로
            원하는 의미와 다를 수 있어 별도 🔴 결정 시점에 재확인 필요).
            ★ 같은 날 후속 — OpenCode(`nemotron-3-ultra-free`, 지정
            모델 deepseek 무료티어 종료로 대체) 독립 재구현 교차검증
            완료(커밋 예정). scripts/build-a5-pilot.js를 안 보고 스펙
            문서만으로 fwd/fwdStatus를 다시 짜 같은 격자에서 793행 산출
            — 2,379건(793셀×3horizon) 전부 일치(fwdStatus·fwd 수치
            둘 다), 불일치 0건. 일치가 정답 확정은 아니라는 단서(AGENTS.md
            §4)는 findings.md에 명시돼 있다. ★ 같은 날 후속2 — §5.2
            (재실행 검증)도 OpenCode(`x-preview-f-free`, 사용자 지정
            1순위로 즉시 성공)에 위임해 완료. build-a5-pilot.js를 수정
            없이 그대로 재실행 — 완전 재실행 결정성(md5 완전 동일)·
            SIGKILL 중단(130/520)→재개(중복 0·유실 0)·exitReason/exitAt
            bake-in 전수 대조(delisted 12종목 377행+active 8종목 416행
            =793행 전체, 불일치 0) 셋 다 통과. 설계안 §4~§5(파일럿 통과
            확인)가 이걸로 전부 끝났다.
            ★ 2026-08-24 후속3 — 본백필 인프라 구현 완료(사용자 지시로
            바로 착수, 커밋 `93f6818`). `scripts/build-a5-backfill.js`
            (파일럿과 같은 resolve()+score()·priceSource.js·fwd/fwdStatus,
            격자만 3,801종목×553주로 확장·샤드는 corp 단위)·
            `.github/workflows/scores-a5.yml`(8샤드 matrix+finalize,
            A2b 패턴 — 네트워크 없는 순수 계산이라 A3d식 다일 collect
            불필요)·`config/policies/scores.v1.json`(샤드·인수조건 정책화,
            registry 등록)·`lib/backfillManifest.js`(A5 REQUIRED_UPSTREAM에
            A3b/A3c/A3d 추가 — resolver.js가 실제 읽는 의존성 반영, 기존
            A3만으로는 그 셋의 재수집 drift를 못 잡았다)·
            `scripts/verify-diagnostics.js`(A5 계약 등록, smokeTest
            forbidden). 표본 실측(60종목×전체 553주, 56.6초, 정적로딩
            37.7초 포함) 외삽 전체 순차 약 1.0시간 — 8샤드면 샤드당 약
            7~8분. 로컬 검증(`--universeLimit 20`, 4샤드) — accept 경로
            (corpsIncomplete=0·manifest 작성)·reject 경로(부분 실행 시
            게이트 발동)·fail-injection(exit 2)·verify-diagnostics.js의
            smokeTest 거부 전부 확인, 기존 JS 회귀 전체 재통과, 로컬
            산출물은 되돌림(규칙 4).
            ★ 2026-08-24 후속4 — **본백필 완료**(사용자 GO 후 트리거,
            GH Actions run 32711717340). 1차 트리거(32710516850)는 8샤드
            수집·finalize 전부 성공(125만행 계산 정상)했으나 마지막
            "Verify diagnostics contract"에서 거부돼 manifest·commit이
            스킵됐다 — 원인은 `scripts/verify-diagnostics.js`의 forbidden
            체크가 `k in d`(키 존재)로 판정하는데 `smokeTest:false`를
            무조건 채워 넣어 실제 본수집도 "플래그가 있다"로 오탐한
            것(커밋 `e0195c0`으로 수정 — smokeTest는 참일 때만 키를
            넣는다, A3d와 동일 관례). 재트리거 완전 성공 —
            `data/backfill/scores/{2016~2026}.jsonl.gz`(총 11개 연도)·
            `data/backfill/manifest/A5.json` 커밋 `8226a58`.
            **실측: 레코드 1,254,759행**(사전 추정 순차 약 1시간이 실제로는
            8샤드 병렬 벽시계 약 4~5분, finalize 1분 9초) · corpsIncomplete=0
            (3,801/3,801 완료) · assembleFailed=0 · exitReasonUnknown
            95,745건(Tier A/B가 A1b에 아직 승격 안 된 상태 그대로 정직하게
            반영, 결함 아님) · 연도별 100,910~133,899행(2026은 반년치라
            79,644행, 정상). `data/backfill/scores/`가 이 프로젝트 역사상
            처음으로 실제 산출물을 갖게 됐다. 다음은 exit overlay 계약
            확정(A6이 Tier A/B/C 분류를 어떻게 읽을지, §1이 이미 "별도
            🔴 결정"으로 남겨둔 것) — 아직 미착수.
            세부: docs/verification/
            BF-1.1-exitReason-TierA-결과.md ·
            BF-1.1-exitReason-TierB-결과.md ·
            BF-1.1-GATE-EP-1-재정의-비교.md ·
            BF-1.1-A5-파일럿-1차실행-결과.md ·
            docs/A5-파일럿-exit-overlay-설계안.md
            ★ 2026-08-24 후속5 — A6 설계 착수(사용자 GO, "진단 전용 v1"로
            범위 확정). 두 블로커를 먼저 확인했다: (1) `exit.v1.json`의
            liquidation/tender 모드가 요구하는 exitPrice(정리매매 최종가·
            공개매수가)를 어느 단계도 수집하지 않는다(A5는 `exitPrice:null`을
            "A6 몫"으로 그대로 저장) — 신규 데이터 소스 확보 문제라 이번
            범위 밖. (2) GATE-EP-1(§6.4)이 Primary 결론을 막는다. §6.4가
            HOLD 상태에서도 허용하는 `exitReasonCoverage`·GATE 판정만 구현—
            Primary IC/분위 스프레드는 만들지 않았다(막혀 있는데 만들면
            죽은 코드). ① exit overlay 승격 파이프라인 신설
            (`scripts/build-exit-overlay.py` — 기존 Tier A/B 로컬 진단
            스크립트를 새 로직 없이 그대로 재사용해 병합, `--promote`일
            때만 씀. `config/policies/exitOverlay.v1.json`·
            `.github/workflows/exit-overlay.yml`·registry.json
            dataPolicies 등록·`lib/backfillManifest.js`에 EO 상류(A1b·
            A2b·A3d)/정책 선언·`scripts/verify-diagnostics.js`에 EO 계약
            등록). **사용자 확인 후 실제 트리거 완료**(GH Actions run
            32716383305, 5분 4초, 전 스텝 통과) — DART list.json 331콜,
            list 오류 0건. Tier A 179건(MERGED)·Tier B 69건(VOLUNTARY 22·
            DELISTING_REVIEW_FAILED 21·BANKRUPTCY 20·CAPITAL_IMPAIRMENT 5·
            AUDIT_OPINION 1), 합계 248/508(48.8%) — Tier A/B가 로컬에서
            먼저 낸 수치(2026-08-24 후속2·3)와 소수점까지 정확히 일치
            (교차검증). `data/backfill/exitOverlay/v1.jsonl`(248행)·
            `manifest/EO.json` 커밋됨. ②
            `scripts/build-a6-coverage-report.js` 신설 — A1b baked
            exitReason(현재 전건 UNKNOWN) 위에 EO overlay가 있으면 그 값을
            덮어쓰는 방식으로 join(설계안 §1이 남겨둔 "overlay 우선?" 결정을
            이 스크립트가 구현), exitReasonCoverage·GATE-EP-1(corp 단위,
            A1b DELISTED 전체 분모)·GATE-EP-2(A5 커버리지가 있는 corp만
            대상, 폐지 직전 최종 finalScore 5분위 UNKNOWN율 Q5/Q1)를 계산해
            `docs/verification/BF-1.1-A6-coverage-gate-{날짜}.md`에 리포트.
            **EO 승격 후 실측(2026-08-24) — GATE-EP-1 UNKNOWN 975/1223
            = 79.7% FAIL**(2026-08-24 후속2가 손으로 낸 79.7%와 정확히
            일치 — 파이프라인 자체의 교차검증). exitReasonCoverage 분포:
            UNKNOWN 79.7%·MERGED 14.6%·VOLUNTARY 1.8%·
            DELISTING_REVIEW_FAILED 1.7%·BANKRUPTCY 1.6%·
            CAPITAL_IMPAIRMENT 0.4%·AUDIT_OPINION 0.1%. **GATE-EP-2는
            PASS**(eligibleCorps 461·Q5/Q1=0.70, 임계 3.0) — 오히려 최고
            점수 분위(Q5)의 UNKNOWN율(36.6%)이 최저 분위(Q1, 52.2%)보다
            낮아, "제외가 상위 분위에 편중"되는 편향 패턴은 실측상 없다.
            **종합 판정: HOLD**(GATE-EP-1 단독 FAIL로 충분) — A6 Primary
            결론은 여전히 금지, 이 리포트(진단)만 유효하다.
            ★ 2026-08-24 후속6 — 사용자 지시로 Tier C 착수 전에 타당성부터
            조사(신규 DART 호출 0건, 이미 커밋된 A1b·A2b·EO만으로 재구성).
            975건 UNKNOWN의 구성: Group A 미분류 260(noSignal 204·
            ambiguousAuditCapital 56) · 품질게이트 제외(anchor 없음) 122 ·
            가격 흔적 자체가 없음 593(dartModifyDate≈2017 배치값 몰림
            474[80.0%, pre-2014 폐지 추정] · 상대적으로 최근인데 가격 0인
            119[20.0%, 원인 미확인]). **산수로 확정**: GATE-EP-1 통과에는
            UNKNOWN≤61건(전체의 5%)이 필요한데, 낙관적으로 260+122+119=501건
            **전부** 100% 분류해도(현실 Tier B 실측 성공률은 같은 유형에서
            21.0%뿐이었다) UNKNOWN은 474/1223=38.8%로 여전히 임계의 7.8배 —
            474(2017 배치값 몰림 cluster)를 안 건드리면 Tier C를 아무리
            잘 만들어도 통과 불가능. 474는 anchor 자체가 없고 DART 보관범위도
            불확실해 이 프로젝트의 방법론으로 접근 경로가 없다. **결론:
            Tier C를 만들지 않는다** — 260·122건을 붙잡아도 GATE 통과에
            산수로 기여 못 한다(exitReasonCoverage 소수점만 조금 채우는
            수준). A6 Primary는 이 EP-1.0/GATE-EP-1 프레임워크 위에서
            **무기한 HOLD로 남는다 — 이것도 정직한 결론이다**(GATE의
            원래 목적이 "사유 미상 상태에서 결론 안 내기"였다). exitPrice
            수집도 HOLD 상태에서는 착수 이유가 없다. 유일하게 열린 갈래는
            "474건에 DART 아닌 다른 원천(KRX 상장폐지 공고 아카이브 등)이
            존재하는가"라는 훨씬 앞 단계의 정찰 질문뿐 — Tier C 설계가
            아니라 그 이전 단계이고, 신규 데이터 소스 통합이라 착수하면
            별도 🔴 결정 — 착수 여부는 다음 세션(또는 이 세션 뒤이어)
            사용자 확인 대상. 다른 트랙(Strategy Lab·10년 백필)은 이
            GATE와 무관하게 계속 진행 가능하다는 점만 참고로 남긴다.
            docs/verification/BF-1.1-GATE-EP-1-TierC-타당성조사-2026-08-24.md
            ★ 2026-08-30 후속 — 유일하게 열려있던 갈래("474건에 DART 아닌
            다른 원천이 있는가")를 착수할지 사용자 재확인 — **착수 안
            하기로 결정**. 이유 둘: ①산수 — 5% 기준 통과에는 474건 거의
            전부를 새로 분류해야 하는데 부분적 성공으로는 문턱에 못 미친다.
            ②가치 — `exit.v1.json`에서 실제 편향보정에 기여하는 건 MERGED·
            SPINOFF가 아니라 BANKRUPTCY·VOLUNTARY류뿐이고 Tier B 실측
            비율(21%)을 적용하면 474건을 전부 복원해도 결론에 영향 주는 건
            ~100건 정도뿐일 가능성이 높다. 새 소스 자체도 2014년 이전
            커버리지·PIT 안전성 전부 미검증이라 순서가 거꾸로다. **A6
            Primary는 이 결정으로 무기한 HOLD가 최종 확정** — 재개하려면
            A6 Primary 결론이 필요한 구체적 이유가 먼저 생겨야 한다.
  안 한다   LAB-1 16종목(13개 신규상장+2개 신탁업+1개 기존확인) 재수집 —
            사용자 결정(2026-08-12). 데이터 없는 종목은 이미 절대 규칙 1대로
            정직하게 '유보'로 뜬다. 13개 전용 스캔 범위 로직을 새로 짜는 비용이
            개인 프로젝트에서 안 맞는다 — 나중에 특정 종목이 실제로 필요해지면
            그때 1회성으로 처리한다(docs/verification/LAB-1-조기종료-결과.md)
  완료      ★ LOWMOM60+기관수급(ChatGPT A/B/C) 재개 — 후보 C만 실제 엔진
              검증 (2026-08-24) — 재개 전 코드를 직접 확인해보니 "+13.90%로
              재검증됨"이라던 사전점검(`lowmom60_institutional_eligible_
              precheck_v2_absolute.py`)이 실은 A4 기관수급 데이터를 전혀
              쓰지 않고 LOWMOM60+절대유동성필터만 쓴다는 걸 발견 — 이건
              후보 C(저모멘텀+유동성필터)이지 A/B(저모멘텀+실제 기관/외국인
              순매수 결합)가 아니다. A/B는 필터 결합 방식이 이 프로젝트
              어디에도 구체적으로 정의된 적이 없어(원 ChatGPT 제안 원문
              미보존) 이번 범위 밖 — 사용자 확인 후 C만 구현.
              `strategies/lowmom60_v1/`을 pbr_value_v1과 완전히 같은 패턴
              (오프라인 selection.json + engine 무변경)으로 신설 — PBR이
              겪은 고정 21일 근사 문제를 처음부터 정확 holdSessions 계산으로
              피하고 연속보유 병합도 처음부터 켰다. 실제 엔진 결과: **CAGR
              +5.09%**(사전점검 +13.90%보다 낮음)·MDD -27.77%·Sharpe 0.77·
              2,437건(승률 46.9%) — PBR도 겪은 같은 종류의 낙폭(포트폴리오
              실제 회계가 오프라인 EW 근사보다 항상 불리), 버그 신호 없음
              (신규 회귀 4건 포함 전체 138건 통과). MDD가 상당히 깊어
              **"채택할 만큼 강하다"고 보긴 이르다** — PBR과 동일하게
              "연구 가치 있는 후보, production alpha 미확정"으로 분류.
              코드는 PBR과 같은 이유로 로컬 미커밋(재현성 사슬 미완성).
              findings/lowmom60-candidate-c-engine-verification-2026-08.md
  완료      ★ Strategy Lab PRIMARY 정식 승격 — A1A_A1B_MERGED 실제 배선
              (2026-08-24, GATE-EP-1과 무관한 트랙으로 선택) — A2bProvider·
              MergedPriceProvider 신설(PriceProvider 인터페이스가 원래
              예상해 둔 확장 경로 그대로, `data/backfill/price/a2b` 읽기),
              `engine/runner.py`의 `A1A_ONLY` assert를 `A1A_A1B_MERGED`도
              허용하도록 완화. 실제 병합 유니버스(3,801종목)로 5DC-v1A-P를
              2014-05-13~2026-08-03 전체 재실행 성공(847.6초) — 신규 회귀
              8건 + 기존 126건 전부 통과.
              **실행 중 GATE-EP-1과 같은 구조의 문제를 발견** — policy.json의
              기존 "PRIMARY requires full A2a+A2b coverage" 기준(2026-08-16
              작성, A2b 완성 전)이 원리적으로 충족 불가능함을 확인
              (missingPriceTickers 734/3801=19.3%, 폐지종목 상당수가 가격
              흔적 자체가 없다 — 오늘 세션 앞부분 GATE-EP-1 조사와 정확히
              같은 근본 원인). 사용자 확인 후 PRIMARY 기준을 "100% 커버리지"
              에서 "병합 유니버스로 실제 실행했는가"로 재정의 — 결측은
              숨기지 않고 `diag.universeCoverage`에 그대로 남긴다(exitReason
              Coverage와 같은 패턴). `strategies/5dc_v1a_p/policy.json`의
              mode를 `A1A_A1B_MERGED`로 전환해 이 전략만 PRIMARY로 승격 —
              다른 전략(PBR·TREND-BREAKOUT-v1 등)은 각각 별도 검증 없이는
              A1A_ONLY 그대로 둔다. 이 재실행 자체의 성과 수치(CAGR -7.94%
              등)는 2026-08-17 비교(-8.1847%)와 정확히 일치하지 않는데,
              그 사이 engine이 same-bar·portfolio scheduling 등 여러 번
              고쳐졌기 때문 — 이 프로젝트가 이미 받아들인 "냉동 baseline은
              engine commit 바운드로만 유효" 원칙 그대로다, 새 이상 신호
              아님
  완료      ★ 5DC Risk-Off 필터 실제 runner 검증(P0-1 후속) + TREND-BREAKOUT-v1
              일반화(P0-2) (2026-08-24) — Ox Alpha 인수인계의 오프라인
              counterfactual(findings/5dc-riskoff-filter-validation-2026-08.md,
              MDD -75.00%→-54.84%)을 실제 Portfolio 스케줄러(슬롯/현금
              재배정 포함)로 검증. **5개 지표(CAGR·MDD·PF·승률·finalEquity)
              전부 개선 방향 유지**하나 **규모는 오프라인의 63~76%**(MDD
              개선 20.16%p→12.74%p) — 원인: Risk-Off로 차단된 원시 진입
              후보 1,706건 중 실제 거래감소는 109건뿐(나머지는 어차피
              maxPositions=10 슬롯경쟁에서 탈락할 후보). 오프라인 문서 자신의
              "2차 재배치 효과는 보수적 방향" 예측과 **반대** — 실제로는
              효과가 작아짐. 최종판정 A(개선 확인, 규모 축소).
              findings/5dc-riskoff-runner-validation-2026-08.md. ★ 임시 CI
              shard(원 스크립트 요구, 로컬 부재) 대신 정식 finalize된
              `data/backfill/price/a2b`로 대체 - baseline이 frozen 1,592건과
              소폭 다름(1,585건, 원인 미확정이나 A/B 비교 자체는 일관적).
              ★ 같은 패턴을 TREND-BREAKOUT-v1에 일반화(OpenCode 위임 -
              `run_5dc_pipeline()`이 이름과 달리 완전 범용 함수임을 확인해
              전략ID만 교체하는 기계적 작업으로 판단) — 여기서도 5개 지표
              전부 개선 방향 확인(CAGR -14.85%→-12.53%, MDD -86.73%→-81.63%),
              2차 재배치 비율은 더 낮음(3.7%, 신호밀도가 높아 슬롯경쟁이
              더 치열함). 단 이 전략 자체는 필터 후에도 CAGR -12.5%로 깊은
              마이너스 - "필터가 전략 무관하게 통한다"는 근거로만 인용,
              "TREND-BREAKOUT-v1이 쓸만해졌다"는 근거 아님.
              findings/trend-breakout-riskoff-runner-validation-2026-08.md.
              ★ CAND1은 P0-2 대상이었으나 **착수 보류** — 기존
              `findings/cand1-regime-conditional-2026-08.md`(2026-08-23)가
              이미 CAND1의 Risk-Off 구간이 5DC와 정반대로 **여전히 net
              +10.01bp 플러스**(가장 낮은 MDD -5.03%)임을 보여줘, 진입차단
              필터가 CAND1에는 오히려 해로울 가능성이 높다고 판단했다.
              CAND1은 엔진도 다르다(분봉단위 청산, 일별 Portfolio 스케줄러
              아님) - 이미 있는 반대 방향 증거를 무시하고 새 엔진까지
              붙여가며 확인할 필요는 낮다고 판단해 보류(사용자 확인 후)
              ★ P1-1(VIX가 Risk-Off 라벨과 별개 정보를 주는가) — Claude가
              직접 설계(통계 프레이밍이라 OpenCode 위임 안 함). regime_labels
              .parquet가 이미 `regime`(합산 라벨)과 `vixState`(VIX 단독
              Low<20/Mid20-30/High≥30, 기존 production 임계값) 둘 다 같은
              usableFromDate로 갖고 있음을 확인 — 새 임계값 없이 라벨 안에서
              vixState별로 쪼개기만 함. **답: 그렇다, VIX는 잔여정보가
              있다** — 5DC·TREND-BREAKOUT-v1 두 전략, Risk-On/Neutral/
              Risk-Off 세 구간 **전부(6/6 조합)에서 VIX Low→Mid→High로
              갈수록 승률·평균PnL이 단조 증가**, 예외 없음. 특히 Risk-Off
              안에서: VIX Low인데 Risk-Off로 분류된 날(다른 3축이 나빠서)이
              가장 나쁘고(승률 14.7~16.0%), VIX가 진짜 높은 패닉 국면의
              Risk-Off는 오히려 승률 30~33%·평균PnL 플러스로 반전 — Ox
              Alpha 문서(§9, VIX 급등후 리바운드)와 방향 일치. 단 상관관계
              관측일 뿐(다중검정·유의성 검정 없음, High VIX×Risk-On은
              n=2~3로 참고 수준) — "Risk-Off AND VIX Low/Mid일 때만 차단"
              정제 필터로 이어질지는 별도 실제 runner 검증 필요(사용자
              지시로 착수, 아래 참고). findings/vix-incremental-info-
              check-2026-08.md
              ★ 정제 필터("Risk-Off AND VIX Low/Mid만 차단", VIX High인
              Risk-Off는 다시 허용) 실제 runner 검증 → **기각**. baseline
              (CAGR -8.18%)보다는 낫지만(-7.34%) 원본 "Risk-Off 전부 차단"
              필터(-5.09%)보다 명확히 나쁘다(CAGR -2.25%p·MDD +9.71%p
              악화). 원인: P1-1은 거래단위 평균을 봤지만(VIX-High×Risk-Off
              거래만 떼면 승률 33%·플러스), 실제 runner에서 그 거래들을
              다시 허용하면 다른 후보와 슬롯(maxPositions=10) 경쟁을
              벌인다 — "거래 자체가 나쁘지 않다"와 "그 슬롯의 최선의
              선택이다"는 다른 질문. P0-1(오프라인이 개선폭 과대평가)과
              **같은 메커니즘의 반대 사례**(이번엔 정제가 손해). **원본
              필터 유지가 최종 결론** — TREND-BREAKOUT-v1로 확장 안 함
              (원인이 슬롯경쟁이라는 엔진 공통 구조라 재현 가능성 높고
              한계효용 낮음, 사용자 확인). findings/5dc-riskoff-vix-refined
              -filter-rejection-2026-08.md — 이걸로 P0-1·P0-2·P1-1 Risk-Off
              필터 연구선 일단락
  완료      ★ Video 전략 후보 V3(Bollinger+RSI) 5DC 독립성 검토 통과 후
              전체 유니버스에서 기각 + Ox Alpha "5DC Risk-Off 필터" 인수인계
              문서 검증 (2026-08-24) — `video-strategies-2026-08/audit.md`
              (2026-08-22)가 "★ 흥미로움"(스모크 30종목 Sharpe 1.20)으로
              표시하고 "5DC와 독립성 검토 필요"로 막아뒀던 V3를 재개. 신호
              겹침 실측(완전 동일일 0.00%, 근접 20거래일 선후관계 17.78%)
              으로 독립성 확인(findings/v3-5dc-signal-independence-2026-08.md)
              → 전체 유니버스(2,543종목) 백테스트 결과 **완전히 뒤집힘**
              (CAGR +5.39%→-4.05%, Sharpe 1.20→-0.2248) — 30종목 소표본이
              우연히 유리한 구간에 치우친 착시였다. **V3 기각**
              (findings/v3-bollinger-rsi-full-universe-rejection-2026-08.md).
              ★ 별도로 Ox Alpha가 작성한 "5DC Risk-Off 필터" 인수인계
              문서(사용자 제공)를 검증 — P0-1(5DC Risk-Off 신규진입 차단
              counterfactual: MDD -75.00%→-54.84%, 부트스트랩 P(개선)=
              96.45%)은 findings/5dc-riskoff-filter-validation-2026-08.md
              와 소수점까지 정확히 일치. 단 그 1,592건 frozen baseline은
              `run_5dc_v1a_p_merged.py`(**A1A_A1B_MERGED**, 생존편향 제거)
              로 만든 것인데, 오늘 밤 Claude가 TREND-BREAKOUT/5DC 타이밍가치
              검증에 쓴 5DC baseline(CAGR -10.88%)은 `policy.json` 기본값
              **A1A_ONLY**(생존편향 있음)로 만든 것 — **둘 다 유효하지만
              서로 다른 유니버스라 직접 비교 불가**, 혼동 방지용으로 기록.
              인수인계 문서의 "P1-2: VIX ETN 최종 승격 여부"는 이미
              `vix-etn-regime-robustness-2026-08.md`가 B→C로 하향해 답한
              상태(문서 자체가 낡음 — 이 프로젝트가 반복 겪은 "착수 가능
              목록이 실제보다 낡아있다" 패턴). 진짜 남은 항목은 P0-1 잔여
              (실제 runner 검증)·P0-2(Risk-Off 필터를 TREND-BREAKOUT·CAND1에
              일반화)·P1-1(VIX가 Risk-Off 라벨과 별개 정보를 주는지) — 전부
              미착수, 오늘 밤 다룬 "금리 축 타이밍"과는 별개의 연구선
  완료      ★ Macro Regime Layer 구축 + PBR/CAND1/Opening Fade 3전략
              규제-조건부 검증 + 진입필터 실전 backtest + GPT·Ox Alpha
              감사 독립검증 (2026-08-23, 다수 커밋 — 1b2e836·4989745·cf90a86·
              df8a424·470ae34·ac170cb·9441fa5·5801426·96822eb) — 기존
              market-regime(VIX·USD/KRW·4축)에 미국금리(FRED DFF·DGS10)·
              미국시장(NASDAQ)·한국시장(KOSPI)·한국금리·신용스프레드·물가·
              경기(전부 한국은행 ECOS, 사용자 키 발급)를 추가해 10개 컬럼
              (`market_regime_features.parquet` 25→45컬럼) PIT-safe 백필.
              **핵심 발견**: FRED 경유 한국 물가·경기 지표는 2023-11~
              2024-03에서 갱신 정지 상태였는데(실측), 같은 지표를 ECOS
              원천으로 받으면 정상 최신 — 문제는 한국이 통계를 안 낸 게
              아니라 FRED가 그 시점 이후 안 받아온 것이었다. 이 10개 축
              (특히 미국10년물)을 PBR/CAND1/Opening Fade에 적용한 결과와
              PBR 진입필터 backtest 결과는 위 "다음" PBR 항목에 정리.
              부수: GPT·Ox Alpha가 독립 작성한 market-regime 데이터
              인벤토리 보고서를 검증해 실제 오류 1건(US10Y 등 8개 시리즈를
              "raw 단계, 정규화 필요"로 오기 — 실제로는 이미 병합 완료,
              자기 문서 안의 다른 항목과도 모순) 발견·기록, KOSPI 3,000행
              캡(네이버 API 응답 상한, count 파라미터 무관)은 라이브
              재현으로 정확함을 확인 — Claude 자신의 이전 백필 보고서
              설명을 정밀화하는 부수 효과. 세부: research/strategy-lab/
              findings/macro-regime-layer-*·pbr-macro-rate-regime-check-
              2026-08.md·cand1-macro-rate-regime-check-2026-08.md·
              opening-fade-macro-rate-regime-check-2026-08.md·
              macro-rate-regime-synthesis-2026-08.md·pbr-ratefilter-
              backtest-2026-08.md·market-regime-final-data-inventory-
              verification-2026-08.md
  완료      ★ CAND1 익일종가 근사 + Opening Fade 롱온리 walk-forward 검증 —
              둘 다 기각 (2026-08-24) — "단기·초단기 종가매매" 새 팩터를
              찾기 전에 이미 "검증됐다"고 기록된 CAND1·Opening Fade 두
              후보부터 실제로 엔진에 얹을 수 있는 형태인지 열어봤다.
              **CAND1**: 검증된 청산(익일 09:35)을 엔진이 지원 못 해 "익일
              종가로 근사"를 먼저 research 레벨에서 확인 — net이 baseline
              (21.43bp) 대비 93% 침식돼 1.48bp만 남고 MDD도 -21.77%→
              -38.97%로 악화(TEST t도 3.94→2.01). CAND1의 edge는 신호 후
              09:35까지의 좁은 창에만 있고 익일 종가까지 들면 거의 증발한다
              — 09:35 청산을 실제 지원하는 엔진 확장(🔴급) 없이는 테스트
              불가로 판정. **Opening Fade**: CLAUDE.md가 인용해 온 "T+5
              net+29.2bp·T+10 net+23.1bp"가 실은 **Q1롱+Q5숏 페어·2xRT
              비용**이었음을 코드로 확인 — 이 프로젝트는 LONG_ONLY라(최상단
              규칙, 엔진에 마진/숏 개념 없음) 그대로 못 쓴다. Q1(롱)만 편도
              비용(20bp)으로 떼어 CAND1과 같은 TRAIN/VALID/TEST(60/15/25%)
              walk-forward로 처음 검증한 결과 TRAIN(+35.1bp/일, t=2.63)·
              VALID(+59.3bp/일, t=3.08)는 강한 양성이지만 **TEST(최근
              63거래일)에서 부호가 완전히 반전**(T+5 -79.1bp/일 t=-3.10,
              T+10 -122.2bp/일 t=-4.01) — 감사(published gross 재현)는
              통과해 계산 버그가 아니라 진짜 workforward 실패. 전체 집계가
              순양(+16.8bp/일)으로 보였던 건 TRAIN+VALID 이익이 TEST 손실을
              상쇄한 착시였다. **결론: 이 세션에서 "단기·초단기 종가매매"
              방향의 기존 검증 후보 둘 다 실전 형태로 재검증하니 탈락 —
              새 팩터 탐색보다 다른 트랙(BF-1.1 10년 백필·CAND1 Risk-Off
              필터 등)으로 넘어가는 게 낫다는 판단으로 이 방향은 일단
              중단**(사용자 확인 후). findings/cand1-close-exit-
              approximation-2026-08.md · opening-fade-longonly-
              walkforward-2026-08.md
  완료      ★ Ox Alpha 후속배치 3건 독립검증 + CAND1 미시구조 검증 + 코드리뷰
              커밋 2건 (2026-08-23, 세션인수인계-2026-08-23-b.md) — 오프닝
              페이드 비용반영(T+5 net+29.2bp·T+10 net+23.1bp, 관례비용
              30bp 기준으로도 생존, **★ 2026-08-24 정정 — 이 숫자는 Q1롱+
              Q5숏 페어·2xRT다, 아래 참고**)과 CAND1 국면분해(VALID 약화가 특정
              변동성 국면 편중이 아님)는 스크립트 로직·수치 대조로 타당성
              확인. **H6 재정의 실험은 결론 무효로 판정** —
              `h6_last30_execution.py`가 요구하는 "15:20 종가 봉"이 KRX
              구조상 사실상 없다(15:20부터 장마감 단일가 전환, 40일
              샘플 15:00봉 67,721건 대 15:20봉 2건) — 유효표본이 하루
              5.2종목(전체 유니버스의 0.2%)까지 붕괴했는데 문서 본문의
              "평균 2,464종목/일"은 이 붕괴를 반영 안 한 오기. "재정의
              시 신호 소멸" 결론은 노이즈이지 실측이 아니다(study.md에
              독립검증 메모 추가, 재정의 방향 제안만 하고 재실행은
              범위 밖). CAND1(오후급락→익일반등, walk-forward
              +0.369%/일 t=3.94)은 미시구조 검증(저유동성 함정 중앙값
              기준 기각, 단 하위 5~10%는 실제로 얇음)까지 마쳤으나
              VALID 구간 약화 원인은 이번 국면분해로도 못 찾아 **여전히
              연구 후보, 전략화 결정 대기** 상태다. ★ 5DC-v1A-P 정본
              냉동 베이스라인은 커밋 `7e1bc61`(PBR 겹침판정 수정) 이후
              HEAD로 재실행하면 1,592→1,590건으로 드리프트한다
              (reports/2026-08-22-reproducibility-drift-audit/) —
              **냉동 baseline은 "engine commit 바운드"로만 유효**, 이
              각주가 이전까지 CLAUDE.md 어디에도 없었다. 부수: 당일
              재진입+same-bar 이중큐잉 KeyError 방지(커밋 377dd6e)·
              samebar 러너 TR/CAGR anchor convention(커밋 cf9e1e4,
              회귀 115 passed) — 둘 다 push 안 함. Oracle VM 이전계획
              (`docs/control/VM-이전계획-2026-08-23.md`) 8단계 확정,
              실행은 SSH 키 로컬 경로 확인 후 별도 승인. 분봉 LIVE
              적립은 실은 2026-08-10부터 이미 상시화 운영 중이었음을
              재확인(수집 자체는 정상, 미완은 GitHub 승격 파이프라인뿐)
  완료      ★ PBR 겹침판정·현금타이밍 엔진 수정(커밋) → MTM 재계산으로 Sharpe
              2.25 폐기 → 2022년 단일 연도가 로그초과수익의 98.6%임을 확인 →
              섹터중립 재검증으로 "연구 가치 있음, production alpha 미확정"
              최종 분류 (2026-08-22, 세션인수인계-2026-08-22.md) — 겹침판정
              `<=`→`<` 한 줄 수정(e526cf8)과 연속보유 병합 opt-in 옵션
              (9d755c1, PARAMS["scheduling"]["continuousHoldOnRenewal"],
              기본 false라 5dc_v1a_p·trend_breakout_v1 무영향) 둘 다 커밋,
              회귀 18개 파일 전체 재확인. 실제 엔진으로 PBR·EW를 월별
              시가평가(mark-to-market)로 재계산하니 실현손익 누적 방식이
              연속보유 장기포지션의 손익을 마지막 청산일이 속한 해에 몰아
              심하게 왜곡했음을 발견(EW "2026년 +53%" 착시로 첫 발견) —
              정확한 기준값은 PBR CAGR +4.72%·MDD -21.7%·Sharpe 0.46(EW
              동일유니버스 벤치마크 CAGR +3.04%·MDD -22.6%·Sharpe 0.29,
              CAGR 우위 +1.68%p). 이 우위를 로그수익률로 연도분해하니
              2022년 단독 기여가 98.6%(나머지 9.6년 합산은 사실상 0) —
              2022년 원인을 업종 데이터로 분해하니 저PBR/고PBR 버킷이
              가치주/성장주 업종분할과 거의 일치(2022년 금리인상기 성장주
              셀오프와 겹침). 섹터중립(업종 내부 PBR 랭킹, top-1→decile
              두 방식) 재검증 결과 신호는 3구간 전부 부호 유지하되 크기는
              절반, OOS 2023-2026의 within-sector IC는 t=1.94로 유의성
              기준 경계선. 신규 스크립트 다수(전부 로컬 미커밋, 관례대로) —
              세션인수인계-2026-08-22.md 참고
  완료      ★ 투자대가 방법론 타당성 조사 → turnover20 tercile 테스트베드
              결함 확정으로 종결 (2026-08-21, 세션인수인계-2026-08-21-c.md)
              — GPT 제안(버핏·린치·그린블라트·오닐)의 데이터 필드 매핑을
              서브에이전트 2개로 조사(Greenblatt는 ROIC/EV/EBITDA 원재료
              자체가 없어 사실상 불가, CAN SLIM은 분기 EPS 원천 데이터 없음·
              상대강도 코드 없음으로 절반만 가능). Lynch PEG·Buffett Quality
              (ROE) precheck를 돌린 결과 둘 다 "저유동성 tercile(T1)에서만
              플러스, 대형주(T3)에서 반전"(PBR·REV20·LOWMOM60+수급에 이은
              3~4번째 재현). 팩터 순위 없이 T1/T3 버킷 자체를 무작위로 사는
              플라시보 테스트로 확정: 무작위 T1 30종목(CAGR +10.26%)이 PEG
              (+4.08%)·ROE(+8.68%)로 고른 T1보다 오히려 높다 — 세 팩터가
              잡은 건 팩터 알파가 아니라 T1 버킷 소속 자체였다.
              ★ 사용자 질문("왜 이렇게까지 유효한 검증이 없었나")을 계기로
              T3 안에서 ROE 하위분위 배제 전략을 실제로 백테스트(단조적
              개선 확인, decile IC t=8.06과 일치, 최대 +4.1%p) 했으나 전부
              여전히 마이너스였던 걸 파고들어 원인을 확정했다:
              `testbed_mechanics_diagnostic.py`로 tercile 없이 전체 유니버스
              월별 리밸런싱만 하면 CAGR +2.94%(매수-보유 벤치마크 +4.78%
              대비 정상적 비용 드래그)로 정상 범위임을 확인 — 리밸런싱
              메커니즘도 30bps 비용 가정도 원인이 아니었다. **문제는
              `turnover20` rolling tercile을 "유동성 통제변수"로 쓰는 것
              자체가 중립적이지 않고 그 자체로 강한 방향성 있는 예측변수
              였다는 것**(T3 baseline -5.77% vs 벤치마크 +4.78%, 10.5%p
              격차가 전부 이걸로 설명됨). 서로 다른 경제적 근거를 가진
              7개 가설(5DC·TREND-BREAKOUT·LOWMOM60·REV20·PBR·PEG·ROE)이
              하나같이 "저유동성에서만 플러스"로 수렴한 이유가 바로 이것 —
              팩터 각각의 문제가 아니라 전부가 공유한 "유동성 통제변수"가
              실은 팩터보다 훨씬 강한 숨은 신호였다.
              ★ 사용자 질문("실험실 테스트 다 다시해야 하나")에 코드를 직접
              확인해 정확한 영향 범위를 좁혔다 — 이 tercile 방식을 실제로
              쓴 결론은 2건뿐(ChatGPT 저모멘텀+수급 A/B/C 기각, PBR 대형주
              반전). LOWMOM60·REV20의 원래 robustness는 절대 거래대금
              임계값을 써서 무관, 5DC·TREND-BREAKOUT은 turnover/tercile
              자체를 안 써서 무관. 절대임계값(turnover20≥1억원)의 중립성을
              먼저 검증(`absolute_turnover_filter_validation.py`, 전체
              유니버스 baseline 대비 갭 -0.68%p)한 뒤 그 2건을 재실행하니
              **둘 다 판정이 뒤집혔다**: LOWMOM60+수급 대형주 -11.8%→
              **+13.90%**, PBR 대형주 -1.48%→**+7.06%**(유동성 무관하게
              견고, 저유동성 대조군도 +7.48%로 비슷). 상대 tercile이 낸
              "채택 불가"는 팩터가 진짜 죽어서가 아니라 오염된 통제변수
              때문에 죽어 보인 오판이었다. **PBR/A5-3 밸류에이션·LOWMOM60+
              기관수급 두 후보가 다시 열렸다** — decile/IC 정밀검증으로
              top-30 결과가 노이즈가 아님도 확인(저PBR IC t=6.30, 저모멘텀60
              IC t=5.24, 둘 다 decile 1→10 거의 단조 감소). 실제 Strategy
              Lab 정책화는 미착수(다음 세션 판단). 신규 스크립트(전부 로컬
              미커밋):
              scripts/build-a5-quality-panel.js · research/strategy-lab/
              lynch_garp_factor_precheck.py ·
              buffett_quality_factor_precheck.py ·
              meta_pattern_liquidity_check.py · t3_factor_decile_check.py ·
              t3_roe_quality_strategy_backtest.py ·
              testbed_mechanics_diagnostic.py ·
              absolute_turnover_filter_validation.py ·
              lowmom60_institutional_eligible_precheck_v2_absolute.py ·
              a5_valuation_factor_precheck_v2_absolute.py ·
              absolute_liquidity_decile_check.py.
              ★ 이어서 PBR을 실제 엔진(engine.runner.run_smoke())에 연결
              시도 - 기존 엔진이 종목별 기술적 신호만 지원하고 횡단면 랭킹
              전략을 지원 안 한다는 걸 발견(strategies/base.py 계약), 사용자
              승인("엔진 확장") 후 strategies/pbr_value_v1/를 신설해 엔진
              무변경으로 흡수(오프라인 랭킹 selection.json + generate_signals가
              features에 직접 값을 써서 risk_spec_for에 전달). 실제 실행 결과
              CAGR +2.95%(사전점검 +7.06%보다 낮음, MDD -23.6%·Sharpe 0.75는
              개선) - 원인은 engine/runner.py의 겹침방지 로직이 연속 선택
              종목의 갱신 신호를 버리는 것으로 확정, 이 로직 수정은 모든
              전략이 공유하는 핵심 루프라 범위가 커 중단(사용자 승인). 엔진
              파일 중 유일한 변경은 row["atr"] 하드코딩을 row.get("atr", 0.0)
              으로 바꾼 안전한 방어 수정뿐(기존 회귀 전체 재확인, 커밋됨).
              pbr_value_v1 전략 코드 자체는 재현성 사슬 미완성(소스 패널
              미커밋) + 겹침판정 미해결로 로컬에만 남기고 커밋 안 함
  완료      ★ A5-3 V7 최종 수직 슬라이스 — valuation(D4) 실데이터 연결 확인
              (2026-08-21, 커밋 `4e9716a`, docs/A5-3-peg-조정기준-결정브리프.md
              §22) — 005930/2019-06-03은 2016년 mergerSpinoff 공시로 valuation이
              정책대로 정직하게 유보됨을 확인(버그 아님). 002100(경농)/2019-06-03은
              per·pbr·peg 전부 채워져 Universe→PIT→가격→resolver→score()까지
              valuation이 실제로 흘러 들어가는 것을 처음 실데이터로 확인 —
              이게 V7의 본 목적. A5-3 valuation/peg 연결 트랙 전체가 이걸로
              완전히 닫혔다. 부수 발견(capitalReal 유보 게이트가 사건-비교연도
              관련성을 안 보고 그 이후 전부 막는 범위 확인)은 별도 🔴 결정 대상으로
              남기고 이 세션은 판단하지 않음
  완료      ★ A3d 브래킷 PIT 버그 2건 발견·수정 + A5-3 실데이터 회귀 (2026-08-21,
              커밋 11c1f96·63fc757·18d2126) — A3d finalize(201e17c) 산출물의
              reverseOrConsolidation 후보 69건 중 56건(81%)이 배수>1(병합인데
              주식수 증가, 논리모순)로 나오는 걸 발견. 원인 1:
              `_pit_select_asof()`가 같은 회계연도 안에서 reprtCode 우선순위를
              실제 접수일보다 먼저 비교해 더 늦게 접수된 분기보고서 대신 오래된
              반기보고서를 골랐다(069640 실사례, production
              lib/a5/pitSelector.js와 다른 규칙이었음 — 정렬키 순서 교정).
              원인 2: "공시일 이후 첫 변화 = 그 공시 효과"라는 가정이 그 사이에
              무관한 별개 사건이 끼면 깨졌다(001140 실사례) —
              `a3c_bracket_ratio()`에 `expected_direction` 추가해 카테고리
              기대 방향(split=증가·reverseOrConsolidation=감소)과 안 맞는
              변화는 건너뛰고, 끝까지 없으면 지어내지 않고 유보하게 고침.
              로컬 재계산(DART 재수집 없음) 결과 전체 493건 방향모순 0건.
              scripts/test-a5-d4-real-samples.js(N=24 실데이터 통합 회귀, 98
              통과) 신설 — docs/A5-3-peg-조정기준-결정브리프.md §14 4번이
              요구한 작업. **실제 data/backfill/fundamentals/a3d/ 산출물은
              아직 옛(버그 있는) 값이다** — 재수집(GitHub Actions, ~35분~1시간·
              DART 예산)은 "실행"이라 사전 확인 대상, 트리거 안 함. 그러므로
              lib/a5/featureRegistry.js의 peg/pbr `available:true` 전환도
              보류(재수집 후 판단) — 아래 "착수 가능" ④ 갱신 참고. 세부:
              research/strategy-lab/findings/a3d-bracket-candidates/README.md
  완료      ★ 저장소 미커밋 파일 정리 2차 (2026-08-20) — DEEPSEEK-4(저장소
              루트)·DEEPSEEK-5(strategy-lab 루즈 파일) OpenCode 감사.
              DEEPSEEK-5는 51개 전량 분류 성공(23개 커밋 추천 — 이미 커밋된
              리포트의 생성 스크립트임을 출력 코드로 확인), DEEPSEEK-4는
              OpenCode가 조사만 하고 표를 출력 안 해(2회 재시도 실패) Claude가
              24개 직접 읽고 판단. 그 과정에서 **5DC-v1A-P post-fix 같은-바
              STOP 120건 중 16건(13.3%)이 무조정 가격의 기업행위 갭으로
              발생했다는, 문서화 안 돼 있던 조사 결과**를 발견해 커밋
              (e0fad6a) — A2a 품질 게이트(PR-1.4)가 20종목은 걸렀으나 이
              16종목은 통과해 들어옴. `verify_a1b_pnl.py`가 기존 survivorship
              리포트의 "새 A1A 거래 240건" 주장을 재검산해 359건 불일치도
              발견(후속 확인 필요, 미해결). strategy-lab 23개 재현성 확보
              커밋(838512a). 삭제 27개(667MB `full_smoke_result.pkl` 포함,
              생성 스크립트 없고 내용은 이미 커밋된 산출물이 보존 — 사용자
              승인 후 삭제)
            ★ Codex slot-marginal 발견 (2026-08-19,
              research/strategy-lab/findings/slot-marginal-contribution/) —
              KR-2.2 19개 슬롯을 LOO(leave-one-out)로 측정. (1) production
              baseline(재무+기술)이 최소 비교 4종 중 유일하게 유의한 IC
              (d120 +0.0411, t=3.48), 수급 5일 추세를 얹으면 오히려 IC 감소.
              (2) full 모델에서 IC를 결정적으로 올리는 슬롯은 **pbr** 하나
              (ΔIC d120 +0.0385) — 단 CA(기업행위) 배제로 표본 120종목 중
              42종목(35%)이 valuation 자체를 측정 못 함. (3) 수급 슬롯이
              쓰는 5일 추세 ordinal은 음(-) IC인데 A4 연구(20일 누적)는
              양(+) IC — **같은 수급 정보라도 5일 정의가 역방향**. (4) base는
              coverage 60%를 원리적으로 못 넘음(최대 0.579) — 등급을 내려면
              수급이 사실상 필수. `docs/control/KR-2.3-supplyDemand-설계안.md`는
              이 발견(5일 분류가 역방향일 수 있다는 우려의 실증)으로 재검토
              전까지 보류 — 재개 조건은 `trendFromWindow()`를 20일 창으로
              바꿨을 때의 classification IC를 먼저 재는 것
            ★ A4 수급 데이터셋 + DEEPSEEK-2 marginal IC 독립검증
              (2026-08-18~19, 커밋 c63340d·699ed18) — Strategy Lab 연구용
              A4 데이터셋 추가. DeepSeek 독립 재구현으로 재현 확인 +
              구조적 원인 규명: **개인 순매수축은 외국인·기관축의 완전한
              선형결합**(foreign_nb_20d+inst_nb_20d+indiv_nb_20d=0,
              5,348,454행 전부 오차 0) — 시장청산 항등식(전체매수=전체매도)
              에서 필연. "개인축을 4번째 지표로 추가"는 정의상 불가능
              (marginal이 낮은 게 아니라 독립 정보 자체가 존재할 수 없음).
              d120에서 개인축 marginal이 사라지는 이유가 이 완전공선성임을
              확정
            ★ SL-2(3) stop_distance 비교 독립 재현 검증 (2026-08-19, 커밋
              38a08e5) — ORIGINAL_2xATR·FIXED_MEDIAN·CAP_P75 세 방식 전
              수치가 slim_trades.json(2,154건) 원시 데이터에서 소수점까지
              정확히 일치. 예외 1건: ATR%-MAE 상관(문서값 r=0.820)이 전체
              2,154건으로는 재현 안 됨(r=0.684) — STOP 청산 거래만 추리면
              0.838로 근접, 원 상관계수가 부분집합 기준이었을 가능성
              (생성 스크립트 부재로 미확정)
            ★ REV20 결합 견고성 검증 — 채택 불가로 하향 (2026-08-18,
              research/strategy-lab/reports/2026-08-18-strategy-candidates/
              README.md §11) — 비용·유동성·가격 필터를 동시 적용(기존엔
              하나씩만 테스트)하자 survivorship 제거로 살아났던 REV20
              (+6.7%)이 전부 손실로 뒤집힘(cost60bps+turnover1억 -11.5%,
              최악 조합 -13.0%). 원인은 필터 부작용이 아니라 **알파 자체가
              5,000원·1억원 미만 저가·저유동성 종목에서만 존재**(<5,000원
              mean +3.94%/월 vs ≥5,000원 -0.14%/월). 현재 조건에서 REV20
              채택 불가 확정
            ★ SB-1.0 KR_4AXIS 백테스트 정찰 — valuation 블로커 재확인, 보류
              (2026-08-18) — A4 완료로 착수한 3단계 vertical slice(5→35종목,
              553주간 snapshot, 2016~2026)에서 resolver.js가 valuation을
              아직 안 붙인다는 사실(A5-3, 2026-08-12부터 알려진 블로커)이 이
              트랙을 막고 있음을 실측으로 재확인했다. baseline(fundamental+
              technical만)을 lib/backtester.js의 runBacktest()에 태우면
              19,355건 전량이 INSUFFICIENT_COVERAGE로 걸러진다(절대 규칙 1,
              커버리지 60% 미만 유보) — valuation 결측은 라벨링 문제가 아니라
              이 재현 경로 자체의 전제조건이었다. 수급을 더한 유일한 측정
              가능 조합(baseline+supplyDemand, KR_3AXIS/KR_4AXIS 어느 쪽도
              아님)도 예측력이 약함(평균 IC 0.004, 등급 비단조, A등급이
              d60·d120에서 최하위권). 전체 2,578종목 확대는 지금 구조로는
              정보 가치가 낮다고 판단해 보류 — A5-3을 열지가 재개의 전제
              (위 "착수 가능" ④ 참고). 재사용 가능한 진단 스크립트 둘 커밋:
              scripts/probe-a4-supplydemand-vertical-slice.js ·
              scripts/probe-a4-runbacktest-comparison.js. 세부:
              세션인수인계-2026-08-18-b.md
            ★ A4(종목별 일별 수급) 전량 finalize 통과 (2026-08-18, manifest
              74ac94e) — 2026-08-17 하루 6회 실행 전부 실패. 15:47 실행은
              16샤드 전량 KRX 로그인·수집까지 성공했으나 finalize가 전량
              (약 585만 행)을 리스트 하나에 올리다 OOM으로 죽었다("runner
              has received a shutdown signal"). 검증+연도라우팅을 스트리밍
              2단계로 바꿔 고친 뒤(f8a893d), 이미 수집 성공한 그 실행의 샤드
              아티팩트를 재사용하도록 워크플로에 sourceRunId 입력을 추가해
              (1ca9832) KRX 재수집 없이 finalize만 재실행 — 16분 32초에
              통과. 확보 2,578/2,578(100%)·5,409,687행·2016-01-04~
              2026-08-14·unresolved 0·missingRate 19.42%. SB-1.0 KR_4AXIS
              백테스트의 블로커가 풀렸다(위 "착수 가능" 참고, 착수 자체는
              미착수). 세부: 세션인수인계-2026-08-18.md
            ★ A2b(폐지 종목 가격) 전량 수집·finalize 통과 (2026-08-17) — KIS
              전환(PR-1.5, 2026-08-16) 후 첫 전량 실행이 규모 게이트 2건에서
              FAIL(504<600·456<550), 표본 31건 교차검증으로 원인을 정리매매
              (상장폐지 직전 가격제한폭 없는 구간)로 확정 — KIS 오류·판정
              오탐 0/31. 실측을 그대로 임계로 승격하지 않고 PR-1.4가 정찰에
              적용한 것과 같은 ~5%·~4% 여유를 재적용해 PR-1.6(480/440,
              qualityExcludedRateWarn 20%)으로 승격 후 재실행 — 확보 508·
              분석구간 460·품질제외율 19.37%, 실패·EGW00201·EGW00316 0건.
              manifest data/backfill/manifest/A2b.json(커밋 88d5756). Strategy
              Lab PRIMARY 전환·운영 PRIMARY 가격소스 연결의 블로커가 풀렸다
              (위 "착수 가능" 참고, 착수 자체는 미착수). 세부:
              세션인수인계-2026-08-16.md §4
            ★ T1 재현성 정찰 종료 — REPRODUCIBILITY FAIL (2026-08-16 확정,
              Day1~Day7 전체 완주). 08-15 한 번 Day5 기준 조기종료·PASS를
              시도했으나 사용자 지시로 취소하고 원계획대로 Day7까지 마쳤다 —
              Day6·Day7 관측이 그 PASS 판단을 뒤집었다.
              ★ FAIL의 대상은 KIS 데이터 자체가 아니라 **"재조회하면 기존
              저장값과 완전히 같다"는 동치 가설**이다. 가격(OHLC) 변경은 증거
              있는 전 비교에서 0건. 000660/08-04 anchor는 두 값 사이를 진동
              (A B A A A B B, Day7까지 안 굳음). 005930/08-13은 15:32 종가 바가
              사후 삭제된 채 복귀하지 않아 저장해 둔 production(381행)이 지금
              API(380행)로 재현되지 않는다 — 단 어느 쪽도 가격 필드는 안 바뀌었다.
              결론: **KIS는 계속 쓴다** · 수집 당시 snapshot이 백테스트·분석의
              기준 원본 · 재조회 결과는 snapshot을 덮어쓰지 않고 별도
              버전/관측으로만 취급(MN-1.0 §4가 이미 이렇게 설계돼 있었다) ·
              `pendingT1.versionRetention: keep-all` 유지 · 15:32/NXT/시간외를
              문제 구간으로 확정하지 않는다(KIS 응답에 세션 식별자가 아예 없어
              미확정) · A2·production 정책·KIS 공급원·threshold 전부 미변경.
              액면분할 · 빈응답 재시도(관측 기회 0) · 000880 값 재현성 · 일자간
              diff의 필드(crossRun이 sha만 남긴다)는 여전히 미측정이다. 상세:
              docs/operations/T1-Day1to7-최종판정-2026-08-16.md ·
              docs/operations/T1-후속검토-판정명칭및운영권고-2026-08-16.md
            ★ Strategy Lab 신설 + 5DC-v1A-P SMOKE baseline 동결 (2026-08-14,
              364e279) — research/strategy-lab, production과 완전 격리
              (A2a 읽기 전용). 공통 engine(indicators·execution·portfolio·
              metrics)·5DC-v1A-P 계약·B0~B3 ablation 전부 구현 + 실데이터
              (A1A_ONLY 2,558종목) 검증 완료, execution 계약 26,090건 전수
              위반 0. A2a 거래정지 아티팩트(open=high=low=0) 발견·수정,
              execution 성능 병목(pandas 문자열 재파싱) 프로파일링 후 계약
              무변경으로 최적화(FastBars). A1A_ONLY라 runClass=SMOKE 고정,
              A2b 완료 전까지 정책·파라미터 동결. 세부:
              docs/control/세션인수인계-2026-08-14.md ·
              research/strategy-lab/reports/2026-08-14-5dc-v1a-p-baseline/
            ★ TREND-BREAKOUT-v1 탐색 + engine/runner.py same-bar 스케줄링
              버그 발견·수정 (2026-08-14) — Donchian 채널 돌파 후보를
              5DC-v1A-P의 RiskSpec/execution/portfolio/cost 계약 그대로
              재사용해 구현(신규 코드는 indicators/donchian.py뿐). SMOKE
              실행 중 당일진입+당일청산(same-bar) 거래의 청산이 누락되고
              같은 심볼의 나중 거래 청산과 잘못 병합되는 버그를 발견 —
              최초 baseline(1,400건) 중 136건(9.7%) 병합 오염 + 종료시점
              미청산 10건 전부 버그 산물(합 10.4% 영향). runner.py의
              day-loop을 _schedule_portfolio()로 추출 후 same-bar 재시도
              로직 추가(진입/청산 파라미터 무변경), 신규 회귀
              test_runner_scheduling.py 포함 전체 15개 파일 통과. **이
              수정은 research/strategy-lab 공통 엔진에 반영돼 5DC-v1A-P를
              포함한 이 엔진의 모든 실행에 영향을 준다** — 5DC-v1A-P의
              2026-08-14 baseline은 이 수정 이전에 만들어졌고, 재실행
              여부는 아직 결정되지 않았다. 수정 후 TREND-BREAKOUT-v1
              baseline 재실행 결과 2,154건(이전 1,400건 대비 +54%),
              CAGR -12.25%(이전 -8.30%)·MDD -83.34%(이전 -70.89%)로
              성과는 악화 — same-bar 즉시청산으로 자본회전이 빨라져 동일
              음의 기대값 거래에 더 자주 노출된 결과로 관찰됨. **1,400건
              기준으로 나온 이전 분석(연도별·국면연결·초기 MFE/MAE)은
              오염 가능성이 있어 재확인 전까지 인용하지 않는다.** 2,154건
              기준 재분석(ATR%×MFE 교차, ATR×2.0 stop 구조 검증)은 완료 —
              ATR%-MAE 상관 r=0.82로 손실폭이 stop_distance 공식에 강하게
              연동됨을 확인, 고변동 종목 고유의 "추가" 위험은 평균적으론
              미미(초과손실 -0.13%p)하나 꼬리 위험(표준편차)은 5배 큼.
              TREND-BREAKOUT-v1은 여전히 미채택 탐색 전략. 세부:
              docs/control/세션인수인계-2026-08-14-b.md
            A0.5 · A0.7 · A1a · A1b · A2a · A3 · A3b · A5 프레임워크
            A1a·A1b 갱신 (2578 / 1223, 2026-08-10) · FN-1.4 임계 승격
            A3b 계약 확정 + 정찰 GO + 수집기 구현 (FN-1.5)
            ★ A3b finalize 완료 (2026-08-12) — 8샤드 3,801법인 전량 · 25,531레코드
              · manifest data/backfill/manifest/A3b.json · EPS확보 92.95%
              (상장종목 96.82%) · rcept_no 완전성 1.0 · 미해결 0건
            ★ A5-5 (1) pitSelector 정규화 (2026-08-12, aa694ee) — A3b의 YYYYMMDD를
              정규화 없이 비교해 asOf와 같은 해 레코드가 전부 미래로 오판되던 것과
              freshnessDays가 전건 null이던 것을 고쳤다. 실측: lte 탈락 2,752→0,
              freshnessDays null 25,531→0, A3 회귀 0건. resolver.js는 미변경
            ★ A5-5 (2) RCEPT_MISMATCH 정책 확정 (2026-08-12, 사용자 GO,
              docs/A5-1.0-입출력계약.md §5) — 63건은 어느 쪽도 안 고르고
              withhold(missing[] 반영·provenance에 두 rceptNo 기록). 정상
              24,627건은 영향 없음. LAB-8 잠정치 위의 임시 정책이라 실험실
              재확인에서 달라지면 다시 연다
            ★ A5-3 부분 구현 (2026-08-12, 5bcd738·ff17675) — shareholderReturn·
              technical을 resolver.js에 연결(RCEPT_MISMATCH withhold 반영),
              featureRegistry.js의 낡은 available:false 플래그를 실제 구현
              상태로 정정. 실측 raw score 87.5→90.2, 회귀 0건. peg는 A2a(수정
              주가)↔A3b(원본 EPS) 조정 불일치로 여전히 중단(LAB-7이 발견) —
              A3c(발행주식총수) 완료가 이 블로커의 해소 경로, perRelative는
              별개(위 "언제든")
            ★ LAB-7 발행주식수 소스 정찰 (2026-08-12) — DART stockTotqySttus의
              istc_totqy로 peg를 EPS 우회 계산(price/(순이익÷발행주식수))할 수
              있음을 확인. PIT(rcept_no)·tie-break(사업보고서>반기>3분기>1분기,
              동일 availableFrom)·carry-forward 규칙을 40법인 실측(41
              corp-year)으로 replay 검증 — direct 94.19%·carryForward
              5.81%·neverValid 0%. 삼성전자 2018년 분할 케이스로 기중 변경
              반영 정밀도 한계(약 91일, 다음 정기보고서까지)도 확인해 정책에
              명시
            ★ A3c 정책·수집기 구현 (2026-08-12, 268c40a·5d4964a) — 위 규칙을
              fundamentals.v1.json에 정식 반영(FN-1.5→FN-1.6), build-
              fundamentals-a3c.py를 A3/A3b 샤드/재개/finalize 패턴으로 구현.
              31법인 스모크(1,159레코드) istc_totqy확보 97.33%, 인수 조건
              전량 통과(maxConsecutiveMissing·neverValidRatio는 이미 WARN
              전용으로 확인)
            ★ A3c 본수집 finalize 완료 (2026-08-16, a997f9a) — 샤드 3이 응답
              불안정으로 170분 타임아웃에 반복 걸려 워크플로 timeout을
              330/345분으로 올린 뒤(8c3e91c) 8샤드 전량 완료. 격자 134,112셀
              전수 스캔·istcTotqyRowFoundRate 95.257%·레코드 98,684·
              corp-year 25,661(direct 97.74%·carryForward 2.26%·neverValid
              0.2%). manifest data/backfill/manifest/A3c.json. peg 연결
              (lib/a5/resolver.js, A5-3 게이트3)은 데이터는 열렸지만 별도
              승인 필요한 연결 작업이라 착수하지 않았다(TASKS.md A5-3 참고)
            백테스트 표본 편입 계약 · A5 게이트4 결정 (SB-1.0, 2026-08-11)
            ★ 게이트4를 analyze.js 운영 경로에 연결 (2026-08-12, 9aed997) —
              latest.json이 KR_4AXIS·US_3AXIS 미선언으로 축을 섞어 냈다.
              onMismatch:withhold 연결 후 실측 143종목 중 142 유지·1 withhold
              (088980, 기존 dataCoverage 게이트로도 이미 '유보'였다)
            ★ KR_3AXIS 백테스트를 KR_4AXIS(운영)의 검증으로 승격하지 않는다
            승인 3등급 · 실험실 트랙 가동 (2026-08-11) — LAB-5 인수 완료
            실험실은 GitHub 공개 raw 로 읽는다. 인계서는 docs/control/handoff/
            분봉 T0·커버리지 정찰 · Collector v1 · 상시화 · 첫 Broad 수집
            실측 수치와 근거는 완료기록·계약 문서에 있다. 여기 옮기지 않는다
  완료      ★ 분봉(MN-1.0) manifest 승격 파이프라인 구현 + resume 재검증
              버그 수정 (2026-08-31~09-01) — 위 항목들이 "아직 미구현"으로
              오래 남겨뒀던 VM→Object Storage→Actions→commit 경로가 실제로
              동작한다. 계기는 `stock-new` 첫 실주행(08-31) 관측 — 16:10
              실행이 432980 09:02 `openOutOfRange`로 FAIL했는데 17:40
              재실행(resume)이 이월 스테이징 조각을 재검증 없이 그대로
              PASS로 승격시켰다(이미 완료로 기록된 티커는 resume 시
              재조회 안 되고, 그 조각은 flush()의 validate_rows()를 안
              거친다). `revalidate_carried()` 신설로 이월 조각을 로컬에서
              재검증(네트워크 재호출 없음) — `scripts/collect-minute-
              kis.py` 커밋 `2088e47`, 회귀 22b가 432980 사례를 그대로
              fixture화. 위반 자체(초저유동성 종목의 open이 그 1분의
              [low,high] 밖으로 나온 것)는 단발성이라 면제 규칙은 넓히지
              않고 observation으로만 남겼다(`docs/operations/minute-
              실측기록.md`, 커밋 `4fc4d27`) — 향후 누적 시 종목·유동성·
              시간대·HALT여부·발생패턴으로 재검토.
              ★ OCI 콘솔 IAM(Group `github-actions-readers`·User
              `github-actions-minute-reader`·Policy·API Key, 전부 사용자가
              콘솔에서 생성)이 준비된 뒤 파이프라인 구현 — `scripts/oci-
              object-storage.py`(VM Instance Principal·Actions API Key
              공용 transport, KisTransport와 같은 원칙) · `scripts/upload-
              minute-oci.py`(VM, 조각 먼저·manifest 마지막 순서로 업로드 -
              manifest 존재가 "이 날짜가 완전히 올라갔다"는 뜻이 되게 한다,
              IAM이 OVERWRITE·DELETE를 안 줘 재시도는 멱등이지 덮어쓰기가
              아니다) · `scripts/promote-minute-manifest.py`(Actions, 인수
              조건을 다시 계산하지 않고 "OCI 객체가 manifest가 말하는
              그대로인가"만 본다 - 조각별·결합 sha256과 행 수, 교훈43·50) ·
              `.github/workflows/promote-minute-manifest.yml`(평일 19:30
              KST + workflow_dispatch, 날짜 단위로 검증해 배치 일부 실패가
              나머지 통과분의 커밋을 안 막는다) (커밋 `2385430`). 실제
              4개 날짜(08-21·27·28·31)로 VM→OCI→Actions→commit 전체
              round-trip 검증 완료(run 33408137682·33408401163) —
              `data/backfill/minute/manifest/`가 이 프로젝트 역사상 처음
              실제 파일을 갖게 됐다. `deploy/install-oci-upload.sh` 신설
              (이미 잘 작동하는 install-vm.sh는 안 건드림) —
              `minute-oci-upload.timer`를 stock-new에 설치·활성화, 매일
              18:00 KST(17:40 수집 뒤) 자동 실행하도록 배선 완료(커밋
              `f0abedd`). 부수: 스테일 테스트 2건(정책버전 MN-1.1→1.2
              반영 누락) 정정. **남은 것**: `stock-minute-ip-test` 진단용
              버킷·정책 정리 여부(사용자 콘솔 확인 대상, 미확인) · 249일
              전체 과거분 백필 업로드는 아직 미착수(`--all` 옵션은 준비돼
              있음, 착수는 별도 결정)
  운영 중    ★ 2026-08-30 분봉 수집기 VM 이전 완료(docs/control/VM-이전계획-
            2026-08-23.md 7단계, 사용자 확인 후) — 분봉 수집(16:10·17:40)·
            감시(18:10)는 `stock-new`(VM.Standard.A1.Flex, ARM, 1 OCPU·10GB,
            129.225.145.14)로 이관. 기존 `stock`(x86, 1 OCPU·1GB,
            129.225.177.125)의 해당 크론·타이머는 비활성화(파일 보존,
            즉시 복원 가능) — **폴백 대기, 삭제 아님**. **T1(19:10)·
            메인 스코어링(`stock.service`, `~/stock`)은 이번 이전 대상이
            아니라 여전히 기존 `stock` VM에서 운영 중**(같은 VM에 두
            애플리케이션이 함께 살던 것 중 분봉 수집기만 옮겼다) — 별도
            판단 없이는 혼동하지 않는다. 월요일(2026-08-31) 16:10 실주행이
            새 VM에서의 첫 실거래일 검증, 아직 확인 전이다.
            Broad 약 2,455/2,578종목 · 하루 약 22분 · 약 60만행/일
            Raw는 저장소 밖 ~/minute-raw. manifest도 VM에서는 저장소 밖이다
```

### 문서 지도

```
계약      docs/MN-1.0-분봉Raw저장계약.md        분봉 (현재 트랙)
          docs/BF-1.1-백필계약.md               manifest·인수 조건의 원 계약
          docs/A3b-1.0-배당EPS계약.md           A3b (구현 완료·실행 대기)
          docs/A5-1.0-입출력계약.md
완료기록   docs/A3-완료기록.md · docs/A3-회고-재사용패턴.md
          docs/operations/minute-실측기록.md    VM·smoke·첫 Broad 수집 실측치
교훈      docs/LESSONS.md                       51개 전문. 아래에는 일곱만 둔다
운영      docs/operations/test-guide.md         테스트·수집·게이트 검증 명령 전문
          docs/operations/data-source-availability.md   막힌 소스 (재론 금지)
결정 대기  docs/A3b-결정브리프.md · docs/FN-1.4-measured승격절차.md
협업      CHATGPT.md                            ChatGPT의 진입 규칙
          docs/AI협업-업무분담.md               업무 경계 · 인계 형식 · 출처 규칙
          docs/control/TASKS.md                 현재 업무 배정. 정본이 아니다 —
                                                코드·계약·실측과 다르면 그쪽이 맞다
```

계약은 **무엇을 지켜야 하는가**, 완료기록은 **무엇이 관측됐는가**, 교훈은 **왜
그렇게 했고 어떤 실패를 피해야 하는가**다. 셋을 섞지 않는다.

### 이 문서가 구현보다 낡았는가

기준선을 손으로 적지 않는다. **낡은 해시는 영원히 참인 경고가 되고, 영원히 참인
경고는 모두가 무시하는 법을 배운다** — 옛 기준선(`44972a4`)이 53커밋째 참이었다.

```bash
git log --oneline $(git log -1 --format=%H -- CLAUDE.md)..HEAD -- lib scripts config deploy .github
```

비어 있지 않으면 **이 문서가 갱신된 뒤에 구현이 바뀐 것이다.** 그 커밋들을 읽고 상태
블록을 고친다. 기준선이 자기 자신에서 나오므로 갱신할 해시가 없다.

한계를 함께 적는다: 구현과 이 문서를 같은 커밋에서 고치면 이 명령은 항상 비어 있다.
그것이 우리가 원하는 규율이고, 코드만 고치고 문서를 안 고친 순간 바로 드러난다.

---

## 프로젝트 한 줄

한국·미국 주식을 정량 점수화하고 그 예측력을 백테스트로 검증하는 시스템.
**조회·알림 전용이다.** 주문·매매 실행 코드를 추가하는 변경은 반드시 사람 확인을 먼저 받는다.

---

## 절대 규칙

1. **결측 지표에 기본점수 금지.** `null` 처리하고 커버리지 60% 미만이면 등급 '유보'.
   뉴스·추정치·공매도는 점수에 넣지 않고 맥락·경보용으로만 쓴다. ("정직한 점수")
2. **시크릿을 코드·JSON·로그에 절대 넣지 않는다.** 저장소는 공개다.
   API 키는 환경변수로만. `.env`는 `.gitignore`에 있어야 한다.
3. **시각은 항상 KST(UTC+9).** 서버 UTC 기준 사용 금지.
4. **`data/backfill/` 산출물을 로컬에서 커밋하지 않는다.**
   로컬 실행은 진단·디버깅 전용이다. 산출물과 manifest는 GitHub Actions만 쓴다.
   로컬 실행 후 반드시 `git checkout -- data/`로 되돌린다.
5. **불변 스냅샷을 수정하지 않는다.** `config/criteria/KR-2.2.json`·`US-2.2.json`은 동결이다.
   기준을 바꾸려면 새 버전 파일을 만들고 `config/policies/registry.json`의 version을 올린다.
6. **정책 임계값을 코드에서 느슨하게 고치지 않는다.** 완화는 정책 파일 버전 승격으로만 한다.
   그래야 파일 해시가 바뀌고 manifest에 흔적이 남는다.
7. **`static/index.html` 전체를 읽지 않는다** (116KB). grep으로 구간만 본다.
8. npm 프로젝트가 아니다. 빌드·타입체크가 없으므로 문법 오류는 런타임에야 드러난다.

---

## 검증 강도 (확정 2026-08-10)

**검증 강도는 파일 종류가 아니라 실패의 모양이 정한다** — 얼마나 조용히 틀리는지,
발견 후 되돌릴 수 있는지를 기준으로 한다.

|  | 되돌릴 수 있음 | 되돌릴 수 없음 |
|---|---|---|
| **시끄럽게 실패** | 최소 대응 | 사전 확인 |
| **조용히 틀림** | 강한 회귀 | **최고 수준 검증** |

파일 종류로 나누면 어긋난다(실측 6건 중 4건). 임계 완화는 '데이터 계약'이지만
인수 조건이 시끄럽게 잡아 몇 시간 만에 고쳤고, 문서 정리는 '최소'지만 줄 단위
대조가 실제 손실을 찾아냈다. 볼 것은 두 질문뿐이다 —
**이게 틀리면 내가 언제 알게 되나. 알면 되돌릴 수 있나.**

검증 방법은 비용이 다르므로 갈라서 쓴다.

```
읽기 검증   코드 경로를 눈으로 따라간다     항상 한다. 사실상 공짜
기계 검증   기존 회귀·게이트·해시 대조      항상 돌린다. 전체 7.8초 (실측)
실행 검증   부작용이 있는 실제 실행         위험도에 맞춰
독립 검증   다른 주체가 다시 한다          정말 필요한 고위험 판단에만
```

**기존 회귀는 변경 위험과 관계없이 항상 실행한다.** 최적화 대상은 불필요한 신규
회귀 작성과 독립 검증이며, 둘은 실제 위험이 있을 때만 추가한다.

**검증 결과는 통과 시 한 줄로 보고하고, 실패·경계조건·판정 변경이 있을 때만 상세히
설명한다.** 이번 세션에서 토큰을 쓴 것은 회귀 실행이 아니라 그 보고였다.

---

## 모델 위임 기준 (확정 2026-08-11)

메인 세션은 소넷이 기본이다. **세션 전체를 오퍼스로 돌리는 건 자동화 대상이 아니다**
— 사용자가 모델 피커에서 직접 고르는 별개 행위다. 자동으로 되는 것은 그 안에서:
위 검증 강도 표의 **최고 수준 검증**(조용히 틀리고 되돌릴 수 없음) 칸에 해당하는
판단만 그 자리에서 Agent 도구를 `model: "opus"`로 호출해 위임한다. 새 창이 필요
없고, 이 세션이 끝나면(새 대화를 열면) 이 기준도 함께 사라지므로 이 문서에 적어 둔다.

해당 예: T1 Day 7 판정 · A5 조인 리졸버 설계(A5-5) · `config/policies`·
`config/criteria`급 아키텍처 결정(🔴 승인 등급과 대체로 겹친다).
수집 실행·finalize·회귀·버그 수정·문서 작성은 소넷으로 충분하다.

**오퍼스 결과도 관점 하나다, 승인이 아니다.** 일치는 승인 근거가 아니라는
교훈61이 여기도 적용된다 — 🔴 등급 승인은 여전히 사용자의 GO/STOP을 거친다.

---

## OpenCode 위임 기준 (확정 2026-08-19)

독립적인 조사·실험·검토가 필요할 때 OpenCode CLI를 서브에이전트로 쓴다. 대량
토큰이 들어가는 작업은 사용 환경·범주와 무관하게 위임 가능 여부부터 검토한다
— 대량 파일 탐색·반복 분석·1차 조사·단순 집계·자료 취합처럼 판단이 아닌
기계적 부분은 어디서든 OpenCode로 분리해 위임한다. 실행은 프로젝트 루트에서
`opencode.cmd run`, 모델은 매 호출 `-m opencode/deepseek-v4-flash-free`를
명시한다 — 생략하면 다른 기본 모델로 조용히 돈다(실측 2026-08-19).

단 **판단 자체는 토큰량과 무관하게 위임하지 않는다.** 계약·정책·PIT·데이터
무결성·보안·아키텍처 결정처럼 판단 책임이 큰 작업은 그 작업이 아무리 토큰이
커도 최종 판단은 Claude가 직접 한다 — 위 모델 위임 기준의 최고 수준 검증
칸과 같은 경계다. 단 그 판단에 필요한 자료 취합·탐색 같은 기계적 전처리는
위임 가능하면 위임한다. 같은 이유로 OpenCode가 설계한 결정을 OpenCode
스스로 검증하게 하지 않는다(생산자·검증자 겸임 금지, 아래 AI 협업 구조와
동일 원칙).

결과는 `docs/verification/`·`docs/control/`류에만 남기고 manifest·
`data/backfill/`에는 쓰지 않는다(실험실과 동일 원칙 — 아래 "쓰기 권한은
경로가 정한다" 참고). **OpenCode 결과는 관점 하나다, Claude의 판단과 동일시
하지 않는다** — 근거와 함께 독립 결과로 구분해 적는다(오퍼스 위임과 같은
원칙, 교훈61).

파일 수정·커밋은 기본 금지. 코드 변경이 필요하면 먼저 사용자 승인을 받는다.
credential·API key 등 민감정보는 전달하지 않는다(규칙 2).

---

## AI 협업 구조 (확정 2026-08-10)

Claude Code 외에 **ChatGPT**(설계·계약 검토, 진입 규칙은 `CHATGPT.md`)와
**OpenCode/DeepSeek**(기계적 전처리 서브에이전트 — 판단은 위임하지 않는다,
진입 규칙은 `AGENTS.md`, 2026-08-21 Codex에서 전환)와 **모두의 AI 실험실**
(독립 실행·검증, 현재 GitHub 접근 불가)이 있고, **VM이 매일 자동으로
산출물을 만든다.**
GitHub `main`이 공통 정본이다 — 다른 주체의 작업을 기억이나 추측으로 다루지 않고
시작 전에 Git 상태와 관련 문서를 확인한다.

### 정본을 쓰는 주체는 하나다

VM은 매일 도는 생산 시스템이다. 여기에 GitHub write 권한을 주면 두 번째 자동
writer가 생긴다. **VM에 GitHub 자격증명을 넣지 않는다.** 자격증명이 없어지는 것이
아니라 폭발 반경이 줄어든다 — 객체 저장소 토큰은 산출물까지지만 GitHub 토큰은
코드·정책·히스토리를 다시 쓴다.

```
VM        수집 → staging / Object Storage (parquet + manifest)
            ↓
Actions   산출물과 대조 → 승격 → commit     ← Git writer는 여기 하나뿐
            ↓
GitHub main
```

**★ manifest를 만드는 것과 승격하는 것은 다르다.** 인수 조건은 응답을 본 수집기만
계산할 수 있다 — 미해결 비율·gapReason·dayVerdict는 parquet 안에 없다(교훈75).
그러므로 manifest는 VM이 만들고 Actions는 그것을 산출물과 대조(sha256·rows·스키마)해
승격한다. **Actions가 인수 조건을 다시 계산하지 않는다 — 잴 수단이 없다.**

이 구조로 규칙 4는 그대로 유효하다(VM은 Git에 쓰지 않는다).
**2026-09-01 구현·검증 완료, 249일 과거분도 같은 날 전량 승격**(위 "착수 가능"
③·"완료" ★ 분봉 manifest 승격 파이프라인 항목 참고) — VM→OCI→Actions→commit
전체 round-trip 확인 후 구 `stock` VM의 258개 날짜까지 배치로 전부 승격했다.

### 같은 작업에서 생산자와 검증자를 겸하지 않는다

'실험실 = 검증자'로 두면 실험실이 백필을 생산할 때 자기 산출물을 자기가 검증하게
된다(교훈72의 조직판). 주체가 아니라 **작업 단위**로 가른다.

```
실험실이 생산한 백필   → Claude 인수 조건·회귀 + 사람
Claude가 생산한 수집   → 실험실 독립 재실행 + ChatGPT 계약 대조
```

독립 재현 검증은 **T1 재현성 정찰(MN-1.0 §6.1) 이후에** 본격화한다. 그 전에는 두
실행의 차이가 결함인지 소스의 정상 변동인지 가릴 수 없고, 대개 구현자를 의심하게 된다.

**실험실이 GitHub을 못 읽는 동안은 독립 검증 대행자가 없다**(2026-08-21,
Codex 사용 중단 — 사용자 결정). OpenCode/DeepSeek은 판단을 위임받지 않으므로
이 자리를 대신하지 않는다(위 "OpenCode 위임 기준" 참고). 실험실 복구 전까지
Claude가 생산한 백필의 독립 재현 검증은 비어 있다 — 필요하면 ChatGPT 계약
대조나 사람 확인으로 보완한다.

### Git 규칙

판단이 아니라 게이트로 막는다. 실제로 non-fast-forward가 났고, 막은 것은 규율이
아니라 git이었다(2026-08-10).

```
force push 금지 · --force-with-lease 도 금지
push 거절 → 상대 commit의 변경 파일 확인 → 겹치면 중지하고 보고
                                       → 안 겹치면 rebase → 재검증 → push
push된 히스토리를 다시 쓰지 않는다. 되돌릴 일은 revert로 앞으로 간다
(아직 push하지 않은 로컬 커밋의 rebase는 허용)
```

### 쓰기 권한은 경로가 정한다

'누가 무엇을 담당한다'는 겹칠 때 해석이 갈리고 '누가 어디에 쓰는가'는 갈리지 않는다.

| 경로 | Writer |
|---|---|
| `scripts/` · `lib/` · `deploy/` · `.github/` | Claude |
| `config/policies/` | Claude (사용자 승인 후. 규칙 6) |
| `config/criteria/` | 없음 — 동결 (규칙 5) |
| `docs/*계약*.md` | Claude가 구현 반영 · ChatGPT는 지적만 |
| `CLAUDE.md` | Claude |
| `CHATGPT.md` | ChatGPT |
| `AGENTS.md` | Claude가 관리 (OpenCode 진입 규칙, OpenCode는 파일 수정·커밋 기본 금지라 스스로 못 씀) |
| `docs/AI협업-업무분담.md` · `docs/control/` | Claude |
| `docs/data/` · `data/backfill/` | GitHub Actions |
| VM staging · Object Storage | VM |
| `docs/verification/` | 실험실 (또는 OpenCode 결과를 Claude가 옮겨 적는다 — ChatGPT 계약 피드백과 같은 relay) |

**실험실의 검증 결과를 `data/backfill/**/manifest/`에 쓰지 않는다.** 그러면 manifest가
'생산자가 인수 조건을 통과시켰다'에서 '누군가 통과했다고 말한다'로 바뀐다. OpenCode도
같다 — 애초에 판단을 위임 안 하니 쓸 이유가 없지만, Claude가 대신 옮겨 적을 때도
manifest·`data/backfill/`은 대상에서 뺀다.

계약·아키텍처 변경은 구현과 별개의 결정이며 사용자 승인 없이 하지 않는다.

### 승인은 세 등급이다 — 등급은 '무엇을 건드리는가'가 정한다 (확정 2026-08-11)

'중요도'로 나누면 경계에서 해석이 갈리고, 그 해석을 하는 것은 넓은 자율을 얻는
쪽이다(교훈72의 조직판). 쓰기 권한을 경로로 가른 것과 같은 이유로 대상으로 가른다.

```
🔴 승인  config/policies · config/criteria · docs/*계약* · 인수 조건 · 동결 목록 ·
         manifest 계약 · 표본 정의 · 실매매 관련 일체 · 이 문서의 구조 변경
         → 권고 하나를 낸다. A/B/C를 고르게 하지 않는다. 사용자는 GO/STOP만 한다
🟡 보고  위에 안 닿는 lib · scripts · .github · 문서. 되돌릴 수 있는 변경
         → 판단하고 진행한 뒤 커밋과 함께 한 줄로 보고한다
🟢 자율  오타 · 포맷 · 주석 · import · 회귀 실행 → 보고하지 않는다
```

**★ 등급은 '변경'에만 적용한다. 부작용을 내는 '실행'은 등급과 무관하게 사전 확인이다.**
수집 실행 · Actions 수동 트리거 · VM 배포 · push · 상태 디렉터리 삭제.
코드는 revert로 되돌아가지만 이틀짜리 수집과 API 예산은 그렇지 않다.

ChatGPT는 🔴만 검토한다 — **독립 검토자이지 승인자가 아니다.** 🟡·🟢을 보내면
왕복만 는다. **★ 일치는 승인 근거가 아니다.** 같은 답을 내는 것은 정보를 거의
주지 않는다(교훈61). 근거는 실측과 계약이고 검토의 값은 불일치에서 나온다 —
ChatGPT가 Claude와 다를 때만 그 불일치를 사용자에게 설명한다.

---

## manifest 계약 (2026-08-04 승격)

`data/backfill/manifest/*.json`은 **"이 산출물이 인수 조건을 통과했다"**를 뜻한다.
단순히 "파일이 존재하고 해시가 같다"가 아니다.

따라서:

- 인수 조건 실패 시 산출물 파일을 쓰지 않는다. 쓰고 나서 `exit(1)`하면 안 된다.
- 워크플로의 manifest·commit 스텝은 `if: success()`다. `if: always()` 금지.
- 진단(`_diagnostics.json`)은 실패 경로에도 쓰되, 실패 실행은 커밋하지 않고 아티팩트로만 남긴다.

`verifyUpstream()`은 '선언된 상류의 변조'만 잡는다. '선언 자체의 누락'은
`lib/backfillManifest.js`의 `REQUIRED_UPSTREAM` 표가 잡는다.
A5가 A1b를 인용하지 않으면 생존편향 상태로 채점되므로, 이 표를 느슨하게 만들지 않는다.

**규칙과 예외는 manifest에서 다른 필드로 갈린다.** `policyHash`는 '어떤 규칙으로
만들었는가'이고 `approvalHash`는 '어떤 예외를 인정했는가'다(REG-1.5의 `approvals`
네임스페이스). 승인 목록을 정책 파일에 두면 corp 하나를 승인할 때마다 그 정책을 읽는
모든 단계의 manifest가 흔들린다. `REQUIRED_APPROVALS`가 선언 누락을 거부하며,
`--extra`에 해시를 얹는 우회는 쓰지 않는다 — 그러면 선언이 강제되지 않는다.
**승인은 수집 동작을 바꾸지 않는다.** 바꾼다면 그것은 승인이 아니라 규칙이다.

진단 계약은 `scripts/verify-diagnostics.js`의 단계별 표 하나가 단일 출처다.
워크플로에 검사를 인라인하지 않는다 — 계약이 워크플로 수만큼 복사되면 필드를 늘릴 때
한 곳만 고치는 경로가 생긴다. 새 단계를 추가하면 이 표에 `required`·`trueFlags`를 등록한다.

**정책 버전을 올리면 그 정책을 읽는 단계를 상류부터 순서대로 재실행한다.**
단, **그 단계가 읽는 키가 바뀌었을 때**다. 같은 파일에 다른 단계용 블록이 추가된 것만으로는
재실행하지 않는다 — 산출물이 같은데 `policyHash`만 새 버전으로 찍히면 "그 단계가 새 기능을
썼다"는 틀린 이력이 남는다. 실례: PR-1.4(a2b 블록 추가)는 A2a를 재실행하지 않았다.
바이트 동일성 확인이 필요하면 재실행이 아니라 별도 rebuild 검증으로 한다.
`verifyUpstream()`은 데이터 해시만 보므로 상류 manifest의 옛 `policyHash`는 그냥 통과한다.
재실행은 무해한 연산이 아니다 — A1a는 KIND를 다시 읽으므로 산출물이 바뀔 수 있고,
바뀌면 하류 수치도 따라 바뀐다. 정상이며, 재실행 후 행 수 확인이 절차의 일부다.

---

## 수집 VM 운영 기준 (2026-08-09 고정)

Oracle에서 추가 VM 생성이 계속 실패했다. **기존 `stock-MonitorAlways`를 그대로 쓴다.**
새 VM을 전제로 코드를 쓰지 않는다 — 나중에 큰 VM이 생기면 코드가 아니라 실행 환경만 옮긴다.

```
VM.Standard.E2.1.Micro · 1 OCPU · 1GB RAM · Ubuntu 20.04 · Python 3.8
~/collector-venv (기존 stock-monitor와 환경을 공유하지 않는다)
```

이 환경이 코드의 전제다.

1. 하루치 전체를 메모리에 적재하지 않는다.
2. **전체 종목을 한꺼번에 submit하지 않는다.** 청크로 제출한다 —
   실측에서 배치 쓰기와 행 버리기는 듣지 않았고 인플라이트를 묶어야 내려갔다
   (389 → 371 → 375 → 145MB).
3. 동시성은 2에서 시작해 최대 4. `EGW00201`은 재시도 가능으로 분류한다.
4. parquet는 조각 단위로 스테이징에 쓰고, 인수 조건 통과 후에만 승격한다.
5. 실패한 종목이 전체 수집을 멈추지 않는다(fail-soft). 미해결은 UNRESOLVED로 남는다.
6. 요청일자와 응답일자를 반드시 대조한다. `DATE_MISMATCH`를 성공으로 세지 않는다.
7. **pykrx를 분봉 Collector의 필수 의존성으로 만들지 않는다.** KRX 빈 응답이
   확인됐고, 핵심 경로는 KIS다. 필요하면 별도 어댑터로 격리한다.
8. 경로·설정·서비스를 하드코딩하지 않는다.
9. 메모리는 구현 후 RSS로 검증한다. 추정으로 넘어가지 않는다.

**Python 3.8이라 pyarrow는 구버전으로 고정된다.** 결정적 쓰기 같은 성질은
pyarrow 버전의 함수이므로 VM에서 다시 잰다 — `scripts/check-vm-readiness.py`.

---

## 식별자 계약

```
ticker    ::= [0-9A-Z]{6}   대문자 유지, 길이 6 고정
corp_code ::= [0-9]{8}      DART 법인코드. 재무 조인은 반드시 이 키로 한다
```

2025-11 이후 신규상장에 영숫자 코드가 배정된다(`0218L0`, `0156T0` 등, 실측 57건).

**금지 패턴**
```
✗ /^\d{6}$/                검증에서 영숫자를 위반으로 오탐
✗ code.replace(/\D/g, '')  0218L0 → 02180 (파괴)
✗ parseInt(ticker)         선행 0 소실
```

정규화는 `normalizeTicker` 단일 창구로만. 길이 보정(zfill)만 하고 문자 제거는 하지 않는다.

---

## 판정 신호는 두 개를 쓰되 하나만 판정에 쓴다

SPAC 제외는 **회사명으로만** 판정한다(`스팩|기업인수목적`).
업종(`spacSectorHint`)은 교차 집계용이며 판정에 쓰지 않는다.

실측: `nameHitSectorMiss 0` / `nameMissSectorHit 123`.
업종으로 걸렀다면 LG·CJ·롯데지주·대신증권이 통째로 사라졌다.
**두 번째 신호는 필터의 과부족을 재는 자이지 필터가 아니다.**

---

## 로컬 실행

```bash
pip install pandas requests lxml html5lib pyarrow    # node는 20 이상
export DART_API_KEY='...'      # 셸 세션 export, 또는 .env(gitignore 대상)
```

DART_API_KEY를 `.env`에 쓰는 것도 2026-08-27부터 허용이다(사용자 지시).
옛 "파일에 쓰지 말 것"은 GH Actions Secrets에 이미 있어 로컬 `.env` 기록이
노출 범위를 실질적으로 늘리지 않는다는 재검토로 바뀌었다 - 다른 로컬
전용 시크릿(API 키 전반)과 동일하게 `.env`(gitignore) 규칙을 따른다
(절대 규칙 2). 여러 서비스 키를 한 번에 넣을 땐 `scripts/setup-keys-
interactive.py`(또는 `setup-keys.bat` 더블클릭)를 쓴다 - 서비스당 값을
클립보드로 하나씩만 받는다. **파일을 통째로 자동 파싱하는 방식은 쓰지
않는다** - 2026-08-27에 그 방식(옛 `scripts/setup-all-keys.py`, 삭제됨)이
실제로 키 값을 대화 로그에 노출시키는 사고를 냈다(base64 패딩 "="을
구분자로 착각). 세부: `세션인수인계-2026-08-27-b.md`.

**회귀는 `scripts/test-*.{py,js}` 다. `ls`로 찾아 전부 돌린다** — 변경 위험과
무관하게, 전체 7.8초다(위 '검증 강도'). npm이 아니라 자동 발견이 없으므로(규칙 8)
돌리지 않으면 아무도 대신 돌려주지 않는다.

수집·분석 스크립트의 사용법은 각 파일 docstring에 있다. `--dry-run`·`--selftest`·
`--report`가 붙은 것은 네트워크 없이 돈다.

게이트 검증은 `*_FAIL_INJECTION=gate-test`로 인수 조건을 강제 실패시킨다.
이 훅은 **실패만 만들 수 있고 통과는 만들 수 없다** — 한 방향이라 남겨둬도 나쁜
데이터를 밀어 넣는 통로가 되지 않는다. 새 단계에도 같은 형태로 붙인다.

**로컬 실행 후 반드시 `git checkout -- data/`.** 로컬 실행은 진단 전용이다.

---

## 절대 공유 금지

`config.yaml` · `.token_cache*.json` · `deploy.conf` · `ssh-key-*.key` ·
DART/KIS/네이버 API 키 · 텔레그램·슬랙 토큰 · 대시보드 `?key=` 포함 URL

워크플로에서는 `${{ secrets.NAME }}` 플레이스홀더로만 쓴다.

---

---

## 교훈 — 도메인 무관하게 반복 발화하는 일곱

**전문 51개는 `docs/LESSONS.md`에 있다.** 번호는 발견 순서 그대로다 — 다시 매기면
커밋 메시지와 코드 주석의 참조가 끊긴다.

여기 남긴 일곱은 도메인을 가리지 않고 계속 발화하는 것들이다. 실측: A3 재무에서
나온 57·72·73이 분봉 수집의 결함을 잡았다(2026-08-10). 그래서 교훈을 도메인별로
쪼개지 않았다 — 교훈의 가치는 대부분 전이(transfer)에 있다.

```
43. manifest는 '파일이 안 바뀌었다'만 증명하지 '검사를 통과했다'는 증명하지 않는다.
    인수 조건 실패 시 산출물을 쓰면 하류가 깨진 데이터로 정상 통과한다.
50. 잴 수 없는 계약은 계약이 아니다.
    A3가 고른 fnlttSinglAcntAll에는 thstrm_dt가 없어(실측 0/240) 회계기간말을 못 읽는다.
    계약 1을 잴 수단이 없으니 수집기가 전건을 버린다 — 3일 수집 후에 드러났을 실패다.
    소스를 고를 때 '값이 있는가'만 보지 말고 '계약을 잴 필드가 있는가'를 함께 본다.
57. 모르는 것은 0이 아니다.
    분모가 없는 상태를 0으로 읽어 '남음 -1381'이 나왔다. 거짓 수치는 게이트도 오탐시킨다.
    잴 수 없는 것과 틀린 것을 구분하고, 잴 수 없으면 판정을 부정한다.
72. 유도한 값으로 그 값을 낳은 식을 검사하면 항상 통과한다.
    conservationOk는 remaining을 assigned-done-hard로 만든 뒤 그 등식을 다시 봤다.
    구성상 참이라 영원히 빈 배열이었다 — 통과가 정보를 주는지 먼저 묻는다(교훈61).
    그리고 그런 필드는 주석을 달지 말고 지운다. 남아 있으면 true가 건강으로 읽힌다.
73. 검사를 추가하기 전에 그 검사가 어느 범위에서 잴 수 있는지 먼저 정한다.
    T 전이(두 상태) · S 상태(하나) · M 병합(전 샤드). 무리마다 사는 자리가 다르다.
    병합에서만 잴 수 있는 것을 샤드 쪽에 두면 각 샤드는 늘 정상으로 보인다.
    같은 무리 안에서도 출처를 갈라 본다 — M2는 상태를, M3는 산출물을 본다.
    가능하면 쓰는 시점에 강제한다(save_progress). 읽는 시점의 발견보다 안전하다.
75. 없는 행은 이유를 말하지 않는다.
    산출물의 공백이 정상 사실인지 손실인지는 응답을 본 수집기만 안다.
    그 자리에서 남기지 않으면 재수집 없이는 영영 얻을 수 없다 — 원시 사실은
    수집 단계에서, 파생 결과(패턴·비율)는 저장하지 말고 계산한다.
    '조회하지 않음'과 '조회했더니 없음'도 다르다. 경계를 함께 남긴다.
81. 성공 코드는 '내 질문에 답했다'를 뜻하지 않는다.
    KIS 분봉은 파싱 안 되는 날짜에 오류 대신 최근 영업일을 rt_cd=0으로 준다.
    하이픈 하나로 전 구간이 "있음"이 되어 보존 기간을 3년으로 읽었다 — 실제는 246영업일.
    응답이 요청의 식별자(일자·종목)를 담고 있는지를 성공 조건에 넣는다.
    같은 이유로 휴장일도 빈 응답이 아니라 직전 영업일로 대체된다.
```

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
