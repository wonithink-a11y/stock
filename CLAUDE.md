# CLAUDE.md — 주식 스코어링·모니터링 프로젝트

Claude Code가 매 세션 자동으로 읽는다. **길어지면 매 요청의 토큰 비용이 된다.**
여기에는 매번 지켜야 할 규칙과 현재 트랙만 둔다. 나머지는 아래 지도에서 찾아 읽는다.

```
Validated against
  정책      UN-1.2 · PR-1.6 · FN-1.6 · REG-1.6 · MN-1.1 · SB-1.0 · SD-1.0
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
            (ChatGPT A/B/C)은 겹침판정·연속보유 수정이 이제 적용 가능해졌으나
            아직 미착수. A2b 소비 단계(priceSource.js PRIMARY 연결·043090
            처리·Core 백필)도 여전히 미착수(아래 "착수 가능" 참고, 우선순위
            미정)
  착수 가능  A2b 종료로 풀렸다. 순서 없음, 각각의 착수는 별도 사용자 승인이다
            ① lib/a5/priceSource.js · 043090 처리 방향(2026-08-23 재검토 —
              docs/BF-1.1-백필계약.md §5 "운영(A5o)/연구(A5) 분리" 확정에 따르면
              **오늘 유니버스에 없는 폐지종목 가격은 운영 스코어링(A5o)에
              애초에 필요 없다** — A2b는 생존편향 제거용 연구(A5)·백테스트
              입력이다. "A2b를 운영 스코어링 PRIMARY로 연결"이라는 원래
              문구는 이 아키텍처와 안 맞는다. 실제로 A2b가 필요한 곳은
              BF-1.1 10년 역사적 백필(과거 시점 유니버스 재구성)일 가능성이
              높다 — 착수 전에 이 재정의부터 사용자 확인 필요, 그래서 지금은
              "착수 가능"이 아니라 "재정의 필요"로 낮춘다)
            ② Strategy Lab PRIMARY **정식 승격**(2026-08-23 정정 — 재실행 자체는
              이미 2026-08-17에 두 번 독립 검증까지 끝났다. 504종목·508종목
              공식 A2b 버전 둘 다 A1A_A1B_MERGED CAGR -8.1847%로 소수점까지
              완전 일치, A1A_ONLY 대비 +1.62%p 개선. 사용자가 그때 "SMOKE급으로
              충분, 정식 승격은 나중"으로 결정해 미뤄뒀다 — 남은 건 재실행이
              아니라 `config/policies/universe.v1.json` 병합모드 확장 +
              `engine/runner.py`의 A1A_ONLY assert 완화, 둘 다 별도 🔴 결정).
              세션인수인계-2026-08-16.md §5 끝 참고
            ③ Core 182종목 246일 백필(2026-08-23 정정 — 이 항목은 낡았다.
              2026-08-18 확인 결과 `collect-minute-kis.py`에 "Core로 좁힌"
              경로가 없어 **Core 182종목 대신 전체 2,579종목을 249일
              백필하기로 사용자 확인 후 변경**됐고(세션인수인계-
              2026-08-18-c.md), `run-minute-daily.py --days 249`를
              VM에서 상시 루프(`systemd-run` transient unit)로 이미
              실행 시작했다. **완료 여부는 이번 세션에서 확인 안 함** —
              VM 상태 직접 확인 필요. "Core 182종목"이라는 원래 문구
              자체가 지금은 틀렸다)
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
            ★ 분봉(MN-1.0) manifest 승격 파이프라인 설계 — VM → Object Storage →
              Actions 대조 → commit. 「AI 협업 구조」 절이 이미 "아직 미구현"으로
              적어 둔 그 파이프라인이다. 백필 A2(가격) 스테이지와 무관하다 —
              착오로 그쪽을 조사했다가 git blame(822971b)으로 바로잡았다
              (2026-08-12). T1이 끝나 승격 경로를 바꿔도 실험 조건이 흔들리지 않는다
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
            10년 전체 백필은 여전히 미착수, 우선순위 미정
  안 한다   LAB-1 16종목(13개 신규상장+2개 신탁업+1개 기존확인) 재수집 —
            사용자 결정(2026-08-12). 데이터 없는 종목은 이미 절대 규칙 1대로
            정직하게 '유보'로 뜬다. 13개 전용 스캔 범위 로직을 새로 짜는 비용이
            개인 프로젝트에서 안 맞는다 — 나중에 특정 종목이 실제로 필요해지면
            그때 1회성으로 처리한다(docs/verification/LAB-1-조기종료-결과.md)
  완료      ★ Ox Alpha 후속배치 3건 독립검증 + CAND1 미시구조 검증 + 코드리뷰
              커밋 2건 (2026-08-23, 세션인수인계-2026-08-23-b.md) — 오프닝
              페이드 비용반영(T+5 net+29.2bp·T+10 net+23.1bp, 관례비용
              30bp 기준으로도 생존)과 CAND1 국면분해(VALID 약화가 특정
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
  운영 중    VM stock-MonitorAlways (1 OCPU · 1GB · Python 3.8)
            수집 16:10·17:40 · 감시 18:10 · T1 19:10 KST
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
**아직 미구현이다.** 그때까지 분봉 manifest는 VM에만 있고 GitHub에 없다.

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
export DART_API_KEY='...'      # 셸 세션에만. 파일에 쓰지 말 것
```

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
