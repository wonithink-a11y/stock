# CLAUDE.md — 주식 스코어링·모니터링 프로젝트

Claude Code가 매 세션 자동으로 읽는다. **길어지면 매 요청의 토큰 비용이 된다.**
여기에는 매번 지켜야 할 규칙과 현재 트랙만 둔다. 나머지는 아래 지도에서 찾아 읽는다.

```
Validated against
  정책      UN-1.2 · PR-1.6 · FN-1.8 · REG-1.8 · MN-1.3 · SB-1.1 · SD-1.1
            PF-1.2는 registry 미등록 = 미발효(자리가 없다 — 완료-이력.md 참고)
            criteria  KR-2.4(2026-09-04 승격) · US-2.2
  다음      ★★ 2026-09-21 **진행 중 3건**(세션인수인계-2026-09-21.md). (1) **A3e 확장 재무 — 수집 완료·계정 매핑 감사 완료**(연구 전용) —
            패널 24,749행(`data/fundamentals-ext/`, gitignore), 매핑 `research/strategy-lab/a3e_account_map.py`(**a3e-map-1.1 동결**),
            감사 docs/control/A3e-계정매핑감사-2026-09-21.md. 다음은 **가치 계열(EV/EBIT·EV/FCF·EV/매출총이익, PBR 잔차화 후 추가 정보)
            사전등록**(6b9c2b52) → **결과 세 셀 전부 REJECT**(11_ev_value_family_oos.py, findings/a3e-ev-value-family-results-2026-09.md).
            **EV/EBITDA 는 감가상각비 커버리지 19% 라 전면 불가.** 고부채 쏠림 통제도 **REJECT**(기전 NOT SUPPORTED — 쏠림을 없앴는데 하락장 격차 그대로, 가치 결합 라인 종결). **품질 계열(GP/A·발생액·자산성장)도 1단계 단독에서 세 축 REJECT** — A3e 회계 축 탐색 라인 종결(PBR 이 유일한 생존 축).
            (2) **모의 동시호가 1주 시험** — 09-21 매수 **PASS**(체결가=공식 종가 274,000, 차이 0.0bp). 09-22 08:45 매도 → 09:05 대조가 남았다
            (VM cron 일회성, 로그 `~/collector-venv/logs/auction-probe.log`). 통과해야 O2b·O3u 모의 실행(설계 동결
            docs/control/단기규칙-모의실행-설계-2026-09-20.md, 슬리브당 4천만원)이 이어진다 — **실패하면 그 실험 중단**.
            (3) **미국 S&P500 스냅샷 타이머**(화~토 07:30, 첫 자동 실행 09-22 — 로그·`_status.json` 확인). 생존편향 경계는 `_meta.json`.
            ETF 횡단면(국내 주식형 152/263)은 **데이터 수집 승인 대기**(시험 결과 뒤).
            ★ **09-21 09:05 RV20·크립토 유닛이 ExecStartPre `git pull --ff-only` 실패로 실행 못 했다**(`Cannot fast-forward to multiple
            branches`, 원격에 새 브랜치가 생긴 시점 — 원인 미확정·재현 불가). 5개 유닛을 `pull --ff-only origin main` 으로 고쳐 VM 에 설치 완료
            (b61f5882). 09-18 RV20 도 KIS 모의 서버 ReadTimeout 으로 실패했다. **09-22 09:05 실행이 정상인지 VM 에서 확인** — 크립토 슬리브는
            09-21 청산 판정이 빠져 AVAX·INJ 보유가 약 48시간이 된다(사후 해석 때 편차로 기록).
            **애널리스트 목표가·투자의견**은 KIS 오픈API `invest-opinion`(FHKST663300C0)으로 2010년부터 받을 수 있음을 확인(무료, 100행/호출).
            **다음 세션 착수: ① KIS 목표가 수집 설계 ② ~~유상증자 회피 필터~~ **종결**(PBR 슬리브 노출 0.1% — 시험 대상 없음, findings/overissue-filter-exposure-check-2026-09.md) ③ 애널리스트 추정치(EPS·영업이익 리비전) 소스 조사** — 상세는 세션인수인계-2026-09-21.md §6.
  다음      ★★ 크립토 상승충격 모의 슬리브 — **2026-09-20 사용자 GO, 같은 날 첫
            관측 시작**(KRW-AVAX 7.26개·KRW-INJ 9.18개, 각 명목 10만원).
            사전등록 `findings/crypto-upshock-paper-sleeve-preregistration-2026-09.md`,
            규칙 `strategies/crypto_upshock_v1/`, 실행 `run_crypto_upshock_paper.py`.
            동결: 2σ · 30일 rolling std(shift 1) · 24시간 보유 · 업비트 KRW 24종
            (연구 28종과의 교집합). **새로 정한 건 크기뿐** — 포지션당 10만원 고정,
            최대 5종. 연구의 MDD −87%는 '그날 급등 1~2종에 전액' 구조에서 나왔다.
            **판정은 신호일 60일 도달 후 1회**, KEEP 조건에 '24종 균등보유 대비
            Sharpe 우위'가 들어간다(연구가 죽은 자리가 정확히 거기다 — 수익은
            났으나 그냥 들고 있는 것과 같았다). 그 전엔 중간 숫자로 판정 안 함.
            ★ **타이머 설치 완료**(2026-09-20 사용자 설치, `systemctl list-timers` 로
            확인 — 다음 실행 09-21 09:05:05 KST, 첫 청산 판정). `deploy/crypto-upshock-paper.
            {service,timer}` (주 7일 09:05 KST, 크립토는 휴장이 없어 RV20의
            Mon..Fri와 다르다). 마지막 실행 09-20 09:47 은 수동 실행 추정 — 09-21
            로그에서 중복 매수 없음·09-20 진입 2종 처리를 확인한다. 상태는
            `data/paper/`(gitignore)라 **도는 기계에만** 남는다.
            ★ 모의 전용 — UpbitPaperBroker(로컬 시뮬레이션, 인증 메서드 미호출),
            실주문 경로가 코드에 없다. 빗썸은 캔들 엔드포인트가 없어 제외.
            ★ 선결로 **페이퍼 엔진의 소수 수량 버그**를 고쳤다(완료-이력.md 참고).
  다음      ★ 부분 익절 그림자 관측 — **2026-09-20 사용자 GO·동결**(7f845b7).
            사전등록 `docs/control/부분익절-그림자-설계-2026-09-20.md`, 실행
            `research/strategy-lab/run_partial_exit_shadow.py`. **반사실 계산 — 실주문 불변.**
            pbr_value_v1_combined 의 forward 창(신호일 ≥ 2026-08-15)에서 +20%/70% 규칙 vs
            전량 보유. **판정은 이 규칙 하나뿐**(12코호트·300건에서 1회, INCONCLUSIVE 면
            24코호트까지 1회 연장). 나머지 4칸(+15/70·+30/70·+20/50·+40/50)·능선 비율·
            트리거 이후 잔여수익률(C)은 **기록 전용** — 결과 보고 고르면 다중검정.
            ★ +20/70 은 "방향"만 검증됐다(12칸 능선의 Sharpe 최선, 최적 근거 아님).
            +40% 는 세그먼트 스윕의 다른 질문이라 경쟁 후보가 아니다. C in-sample 점검:
            트리거 이후 잔여 경로는 시장과 구분 안 됨(+0.7%±1.8%) — **알파가 아니라 분산
            도구**로 읽는다. 현실적 기대는 INCONCLUSIVE, 실질 가치는 REJECT 를 싸게 잡는 것.
            **실행은 수동 월 1회**: A2a 월간 증분(10월 1~5일) 뒤
            `python research/strategy-lab/run_partial_exit_shadow.py` — 첫 코호트(09-01)가
            9월 말~10월 초 청산이라 그 전엔 "닫힌 거래 없음"이 정상. 로그는
            `reports/2026-09-partial-exit-shadow/observations.jsonl`(추적됨, 커밋한다).
            KEEP 후보가 나와도 채택 아님 — portfolio.v1.json 반영은 🔴 별도 GO.
  다음      ★★ RV20 선물 sizing 규칙 모의투자 자동화 — **2026-09-14 09:05 KST
            첫 실주문 성공**(사용자가 VM 로그 직접 확인: 신호일 09-11·
            percentile 0.492→1.0x·F 202612 BUY 1계약·주문번호 0000001627,
            세션인수인계-2026-09-14.md §①). 이후는 평일 09:05 상시 가동 —
            점검은 VM(`stock`)의 `~/collector-venv/logs/rv20-futures-paper-order.log`
            (Claude는 VM 접근 권한이 없어 사용자가 tail해서 넘긴다).
            배경: futures Stage 6-1(OpenCode) 독립검증에서
            "Strict Holdout OOS"가 실은 discovery 표본 재게시였음을 발견 →
            규칙을 2026-09-13 시점으로 동결(`futures-rv20-sizing-rule-freeze-
            2026-09-13.md`, Rule B: RV20 rolling252 percentile Q5(0.8)→0x) →
            KIS 모의투자 국내선물 계좌(자본 50%)에 실제 적용. kill switch
            (`research/strategy-lab/futures/rv20_automation_enabled.json`,
            GitHub Actions "RV20 futures automation on/off switch"로만
            켜고 끔)는 2026-09-14 00:55 사용자가 직접 켰다(enabled: true).
            VM 배선 중 실측 버그 2건 수정(REPO 하드코딩 절대경로·`.env`
            로딩이 systemd EnvironmentFile을 안 읽던 것) — 둘 다
            `collect_kospi200_daily_krx.py`/`stage5_1_volatility_event_study.py`.
            세부: docs/control/세션인수인계-2026-09-14.md.
  다음      ★ 모의투자 월간 자동화 — 시한이 있는 항목 중 하나. A2a(월 1~5일) →
            refresh-selections(workflow_run) → VM pull(06:30) → 페이퍼 엔진
            (10분). CI 8회차 완주·자동 커밋까지 확인했지만 **2026-10-01이 첫
            실물 검증이다** — workflow_run 물림은 그날 처음 돈다(여태
            workflow_dispatch 로만 태웠다). 실패하면 notify-failure.yml 이
            텔레그램(@wonistock_bot)으로 알린다 — 대상 12개(09-21 에 6개 추가 — notify-failure.yml 주석에 제외 사유), '성공→실패'
            전이에만(페이퍼 엔진이 10분 주기라 매번 보내면 하루 144통).
            2026-09-11 에 promote-minute-manifest 가 5번째로 들어갔다 —
            그 단계가 승격 실패만이 아니라 **저장소 구멍**(최근 거래일 중
            manifest 없는 날, lookback 10 · grace 1)에도 붉어진다. 워크플로
            녹색과 데이터 존재는 다르다 — VM 실패는 Actions 에 안 나타난다.
            세부·함정: docs/control/세션인수인계-2026-09-09-b.md. 단 그
            인수인계의 "남은 것" 중 4건은 2026-09-10 실측으로 이미 닫혔다
            (완료-이력.md 참고) — 그 목록을 그대로 착수 목록으로 삼지 않는다.
            ★ **같은 점검에 부분 익절 그림자 첫 관측을 건다** — A2a·refresh-selections 가
            녹색이고 가격이 갱신된 것을 확인한 **뒤에**
            `python research/strategy-lab/run_partial_exit_shadow.py` 를 돌리고 생성된
            `reports/2026-09-partial-exit-shadow/observations.jsonl` 을 커밋한다.
            첫 코호트(09-01 진입 09-02)의 21세션 청산이 추석 연휴(09-24~26)로 10월 초로
            밀릴 수 있어 "닫힌 거래 없음"이면 오류가 아니다 — A2a 창(1~5일) 안에 다시 본다.
            ★ **같은 점검에 O2b 그림자도 돌린다**: `python research/strategy-lab/futures/run_close_open_shadow.py`
            (같은 신호일은 중복 기록 안 함) 후 observations.jsonl 커밋.
  다음      ★ 무한매수법 해외 슬리브 — 09-14 잔존 주문 확인 **완료**(미체결 0건,
            2026-09-12). 두 주문이 확인 시점에 이미 전량체결이라 "당일물인지"
            자체는 아직 미확정 — 부분체결 남는 날 재확인. **취소·재접수 로직은
            2026-09-19 구현**(c605be5 — 취소→확인→계좌조회→재접수, 취소 미확인 시
            그 종목 그날 주문 안 냄, 가짜 브로커 회귀) + systemd 유닛 배포(3ecedc4,
            **dry-run 상태**, 평일 21:30 KST). **2026-09-20 VM 배선 완료** —
            `_rules.local.json`·vts 상태 2개를 ~/collector-venv/infbuy/ 로 복사
            (sha256 일치 확인, 규칙 파일은 600) · yfinance 설치 · 유닛+타이머 설치·
            **타이머 활성**(평일 21:30, 다음 09-21) · dry-run 1회 성공.
            이월 확인: **T 가 0 이 아니다**(TQQQ 0.86 · SOXL 0.79, lastDate 09-11) —
            상태 파일을 빼먹으면 여기가 0 이 된다. 실패 알림도 붙였다.
            **남은 건 주문 스위치 하나뿐이고 그건 사용자 몫이다**:
            `sudo systemctl edit infinite-buying-vts.service` 로 ExecStart 를 비우고
            --execute 를 붙여 다시 쓴다. Claude 는 이 스위치를 켜지 않는다.
            ★★ 같은 날 버전 선택 연구 완주 — V2.0~V4.0 백테스트 → 하이브리드
            (후반전 매도확대, NOT SUPPORTED로 기각) → 위기episode 자동탐지
            (TQQQ 16·SOXL 12, 3A) → 저점현금비중 가설(NOT SUPPORTED, 3C) →
            TQQQ·SOXL 단일종목 V2.1/V3.0/V4.0 episode 전체회복 최종비교.
            **결론(사용자 확정): V4.0 유지.** 근거 — 28개 episode 전체에서
            V4.0은 "가격은 회복했는데 계좌는 손실"인 완결 실패가 0건인 반면
            V2.1/V3.0은 중간 규모 조정(TQQQ 2012년 둘·SOXL 2015년 하나)에서
            반등 참여 부족으로 실패했다. V4.0의 위험은 영구손실이 아니라 버티는
            동안의 흔들림(MDD 최대 TQQQ 50.8%·SOXL 69.3%)이라는 성격으로 재정의됨.
            ★ V4.0 관련 수치는 전부 리버스모드 T전이식 해석 하나(후보A)에 걸린
            **잠정치**다 — bottomup32 원문 스펙 §14가 이 해석을 스스로 "언이
            변형판"이라 표시하고, 원저작물 대조는 없다. 하이브리드·파라미터
            튜닝 라인은 **종료, 재론 안 함**. 그 별도 연구 3갈래(경로별 구조분해·B&H대비 분해·LOC체결 현실성)는
            **같은 날(09-12) 이미 완주**했다 — 세션인수인계-2026-09-12-d.md.
            V4.0 비교 기준선은 이상적 체결이 아니라 **실현10bp**(realistic_fill_model.py).
            ★ 모드가 둘이다 — `paper`(규칙대로 LOC, 전략 판정용 정본)와
            `vts`(모의계좌 실주문). **KIS 모의투자는 지정가만 받고 LOC(34)는 실전
            전용**이라 둘이 갈라진다(실측: 사이클 45%↓·MDD 6~9%p↑). 모의투자
            숫자를 전략 판정에 쓰지 않는다. 상태 파일이 모드별로 분리돼 있다.
            ★ 규칙 값은 **로컬 전용**이다(원작자가 재배포 금지, 저장소는 PUBLIC) —
            `data/leveraged-etf/_rules*.json` · `findings/infinite-buying-rule-spec-*.md`
            둘 다 gitignore. 코드(기전)는 커밋돼 있고 매직넘버가 없다.
            세부: docs/control/세션인수인계-2026-09-12.md ·
            -2026-09-12-b.md · -2026-09-12-c.md(최신, 버전선택 연구 전체)
  안 한다   ★ 2026-09-02 팩터 조합 실험(54축 전수·빔서치·난수 귀무분포) — **채택 0개, 라인 종료·재론 안 함**.
            업종중립 PBR 계열도 09-03 전체 53축·top-30 바닥선 재측정으로 REJECT(1,431조합 중 76위, t=2.11 <
            바닥선 3.52). 인프라는 남아 있다: `build_factor_panel.py`·`sweep_combos.py`·`simulate_exits.py`·
            `build_sweep_dashboard.py`. ★ 함정 6가지는 세션인수인계-2026-09-02-e.md §3 — 난수 팩터로도 최고 t=3.21 ·
            빔서치 바닥선이 전수보다 높음 · 바닥선 통과는 필요조건일 뿐 · t 는 EW 대비 초과로 재야 함 ·
            실현손익 누적 회계 재발 · simulate_exits 는 회전율을 곱해야 함. 공개범위 PUBLIC 유지 —
            트리거: KEEP 전략이 처음 생기면 그것만 private 분리. 원문: 완료-이력.md 이월 ②.
  다음      PBR 연구 라인 — **production 🔴 결정(2026-09-18 사용자 확정): `pbr_value_v1_combined` GO,
            `factor_earnings_yield_v1`(EY) 보류.** EY 는 세 경로(단독·raw 50:50 결합·잔차화 결합) 전부 막혔고
            모의투자 관측용으로만 둔다(findings/earnings-yield-final-robustness · pbr-ey-composite-oos ·
            pbr-ey-resid-composite-oos). **실계좌 배분 실행(계좌·이체·실주문)은 Claude 가 하지 않는다** —
            그 다음은 사용자 몫. combined = dropout+MAX제외, **nDrop=3/pct=0.8(2026-09-08 확정,
            tests/test_paper_sleeve_policy.py 가 pin)**, OOS 12격자·3구간 Sharpe 양·부호반전 0. 단 초과수익의
            74% 가 2022+2024 두 해 — 미국 장기금리 상승기 가치주 노출이라는 **조건부 성격**, 안정 알파로
            과장 안 함. 이 축을 타이밍/사이징 필터로 쓰는 시도는 전부 기각(상관관계 ≠ 타이밍가치). PEAD·DD252 최종 기각,
            LOWMOM60+기관수급은 연구 후보(후보 C만 구현). 재현성 사슬은 09-08 해소 — 패널은
            `node scripts/build-a5-valuation-panel.js` 한 줄, baseline 정본 **CAGR 5.49%**(패널 sha256 e55330bf2115,
            findings/pbr-reproducibility-anchor-2026-09.md). 전체 경위·원문: 완료-이력.md 이월 ②.
  안 한다   ★ minute.v1.json의 pendingT1 승격 — **승격할 근거가 없다**(2026-09-11
            실측으로 닫음. 🔴이라 승격 자체는 사용자 GO 대상이지만, GO 를 요청할
            근거가 없다). 두 가지가 나왔다.
            (1) **네 손잡이 중 어느 것도 코드가 안 읽는다** — `emptyResponseRetries`
            는 테스트가 '블록이 존재하는가'만 보고, `recollectHaltedSymbols`·
            `versionRetention`·`correctionHandling` 은 아예 참조가 없다(수집기의
            언급은 전부 주석이다). PF-1.2의 '자리가 없다'와 같은 모양 — 값을
            바꿔도 데이터도 실험도 안 바뀐다. 그리고 `pendingT1` 주석("기본값을
            '확정'으로 읽지 않는다")은 지금 **참이고 유용하다**. 승격은 그걸
            거짓으로 만드는 일이다.
            (2) 옛 전제 **"emptyResponseRetries는 관측 기회 0건"이 틀렸다** —
            그건 T1 표본(6종목×7일) 얘기지 운영이 아니다. production 은 하루
            EMPTY 40~54건이다. 그래서 실제로 쟀다: `EMPTY` 는 KIS 가 rt_cd
            정상으로 답했는데 0행인 경우인데, **일봉 거래량 0 종목 수와 대조하니
            165거래일 전부 `EMPTY+HALT ≈ 거래량0`**(잔차 +3~7, 표준편차 0.64,
            설명 안 되는 날 **0건**). 즉 EMPTY 는 손실이 아니라 "그날 거래가
            없었다"다 — 재시도해도 얻을 봉이 없다.
            재현: `python scripts/probe-minute-empty-accounting.py`(네트워크 없음).
            재개 조건: 그 손잡이를 **읽는 코드가 생길 때**. 그때 값부터 정한다.
            (A2b 종료로 풀렸던 나머지 4항목 — priceSource.js·043090 처리·
            Strategy Lab PRIMARY 승격·분봉 전체 백필·A5-3 valuation 연결 —
            전부 완료됨. docs/control/완료-이력.md 참고)
  언제든    perRelative(업종 PER 횡단면) — A5-3 부분 재개(아래) 이후에도 여전히
            미착수. 날짜별·업종별 PIT 중앙값 인프라가 새로 필요해 resolver.js의
            종목 단위 인터페이스에 안 맞는다. 🔴급 설계 결정, 백테스트 eligible
            표본이 3건뿐이라(LAB-4) 지금 열어도 검증할 데가 없어 급하지 않다
            LAB-2(FY2015 EPS 라벨링) 방향 보류 — 서두를 이유 없음(2026-08-12)
            BF-1.1(10년 Historical Backfill) — 원재료 완료, A5 스코어 계산
            (1,254,759행)은 이미 완료(완료-이력.md 참고). **A6 Primary 결론은
            무기한 HOLD 최종 확정**(2026-08-30) — GATE-EP-1(A1b exitReason
            UNKNOWN 비율)이 이 방법론으로 구조적으로 5% 임계 통과 불가능함을
            확정했고(Tier A+B로도 UNKNOWN 79.7%, 재정의는 survivorship bias
            재도입 위험 확인), Tier C 설계도 산수상 기여 없어 포기. 재개
            조건: A6 Primary 결론이 필요한 구체적 이유가 새로 생길 때(현재
            없음). Strategy Lab(PBR·5DC 등)은 이 GATE와 무관한 별도 시스템
            이라 계속 유효. 전체 경위(Tier A/B 분류·GATE-EP-2 PASS·2026-09-02
            후속 — earnings_yield PASS·TreasuryRatio REJECT·크립토 REJECT·
            MA크로스 반전 PASS[KR-2.3/2.4로 이미 production 반영, 아래 완료
            참고]): docs/control/완료-이력.md 참고.
  안 한다   LAB-1 16종목(13개 신규상장+2개 신탁업+1개 기존확인) 재수집 —
            사용자 결정(2026-08-12). 데이터 없는 종목은 이미 절대 규칙 1대로
            정직하게 '유보'로 뜬다. 13개 전용 스캔 범위 로직을 새로 짜는 비용이
            개인 프로젝트에서 안 맞는다 — 나중에 특정 종목이 실제로 필요해지면
            그때 1회성으로 처리한다(docs/verification/LAB-1-조기종료-결과.md)
  완료      상세 이력은 docs/control/완료-이력.md 참고(2026-09-06, CLAUDE.md가
            2,720줄까지 커져 절반 이상이던 "완료" 전체를 분리 — 내용 손실
            없음, 원본 그대로 이동). 최신 항목:
            · 09-21 **A3e 품질 계열(GP/A·발생액·자산성장) — 1단계(단독 vs EW) 세 축 전부 REJECT, 2단계 미실행**(findings/a3e-quality-family-results-2026-09.md).
              TEST 에서 셋 다 EW 보다 월 34~41bp 나쁨 · 하락장 단독 방어 9번 중 1번 · AGR 만 TRAIN 바닥선 통과 후 TEST 붕괴. GP/A 는 ROE·op_margin 과 상관 0.5(기존 REJECT 계열과 겹침).
            · 09-21 **고부채 쏠림 통제(부채/EV 상위 1/3 제외) — 4셀(EV 3+EY) 전부 REJECT · 기전 NOT SUPPORTED**(사후 가설, findings/leverage-control-results-2026-09.md).
              결합 상위 10분위 부채/EV 0.42~0.57 → 0.03~0.05 로 쏠림을 없앴는데도 하락장 격차 그대로(무작위 동수 제외 p95 +30bp 미달) → **PBR 에 가치 계열을 섞는 라인 종결**.
              단 하락장 36개월이라 ~30bp 미만 효과는 탐지 못 함. 기록 전용: 제한 표본에서 PBR 단독 TRAIN Sharpe 가 절반(고부채 종목이 TRAIN 성과 일부) — 새 가설, 미검증.
            · 09-21 **EV 가치 계열(EBIT/EV·FCF/EV·GP/EV) × PBR 잔차화 결합 — 세 셀 전부 REJECT**(가족 난수 바닥선 p95 0.104,
              TRAIN ΔSharpe −0.200/+0.011/−0.054 · TEST 전부 PBR 단독보다 나쁨 · 하락장 2018·2022 세 셀 모두 PBR 보다 나쁨 — EY 잔차화 결합과 같은 패턴).
              결합 상위 10분위 부채/EV 0.42~0.46(유니버스 0.22) 고부채 쏠림. A3e 매핑 감사·v1.1 동결(docs/control/A3e-계정매핑감사-2026-09-21.md).
            · 09-21 미국 ETF 30주선 기울기 **REJECT**(VALID/TEST 부호 반전) · 분기 순이익 가속 ACC2 **REJECT**(TRAIN 바닥선 미달) ·
              기업행사 공시(무상증자·유상증자) 이벤트 3셀 **REJECT**(TRAIN 바닥선 미달이나 부호·OOS t 일관 — 검출력 문제 가능, E1 은 권리락
              수정주가 점검 필요) · 비용 축 조사(국내 주식형 ETF 는 거래세·매매차익 과세 모두 비대상 — 원문 확인, 지수형 수단은 gross 가
              한 자릿수라 비용 축만으로 경제성 없음) · notify-failure 대상 12개.
            · 09-20 구조형 단기 35셀·종가→익일 시가 14셀 — **ECONOMIC 0**. 실제 KR 왕복 비용은 연속 시장
              ≈33.5bp(세금 20+스프레드 12.6), 종가·시가 단일가 체결은 23.54bp. O2b 그림자는 위 "다음" 참고.
            · 09-20 **VM 유닛 실패 알림** — 서비스 7개+타이머 7개에 OnFailure, 알림은 장애 전용 그룹 `주식 알림`
              (`TELEGRAM_ALERT_CHAT_ID`, 없으면 콘텐츠 방으로 안 보내고 실패). 알림 이름이 `*.timer` 면
              유닛 파일 깨짐(로드 실패)이다. 그룹에 뭐가 뜨면 무조건 고장.
            · 09-21 **미국 S&P500 스냅샷 수집기**(us_universe_snapshot.py, 503종목) — yfinance 는 상장폐지 종목의 과거를
              지우므로 명단·가격을 매일 쌓아 앞으로의 공백을 막는다. **첫 스냅샷(2026-09-20) 이전 가격은 생존자 표본** —
              그 날짜 이후만 PIT (`_meta.json`). VM 타이머 `deploy/us-universe-snapshot.{service,timer}` 화~토 07:30,
              데이터는 VM `~/collector-venv/us-universe`(저장소 밖). 설치는 사용자 몫. 방식 A(미국 ETF 30주선 기울기)는 REJECT.
              과거 26년 PIT 는 못 채운다(Sharadar/MarketParquet 조사: docs/control/미국종목-유니버스-PIT-데이터-조사-2026-09-21.md).
            · 09-20 **갭하락 후 종가 회복(O5) → 익일 시가: REJECT**(사전등록 356b95c, findings/close-open-gap-recovery-results-2026-09.md).
              신호 없음(정보 t 0.36, 가족 백분위 1.0) · 손익분기 −1.1bp. 기록 전용 R3(같은 종목의 익일 시가→종가) 롱 gross −57bp
              [−80,−35] — 기존 "익일 장중 롱은 손실"과 같은 방향이다(초판이 TRAIN 부호를 곱해 숏 +57 로 뒤집어 표시한 것을 정정, 발견 아님).
            · 09-20 **페이퍼 엔진 소수 수량 버그**(14b53ec) — `remaining < 1` 이 소수 수량 매수를 "이미 다 샀다"로
              읽어 장부가 거짓이 됐다. `<= 0` 으로 수정, 정수 수량 전략(KIS 실주문 포함)은 불변. 되돌리려면 revert.
            · 09-20 밤샘 단기·크립토 실험 9건 — KEEP 0. 09-19 autotrader 신설(기본 dry-run, 실계좌 7겹 게이트,
              Claude 는 실계좌 안 켬) · 폰용 읽기 전용 웹 화면. 09-19 KOSPI200 선물 장중 신호 10셀 REJECT.
            · 09-14 RV20 선물 sizing 모의투자 상시 자동화 구축 · 09-13 연구 4갈래 종료(funding carry·무한매수 1a·
              반도체 사이클·목표변동성 sizing) · 09-11 shares-snapshot 타임아웃 닫힘(실험은 09-20 취소)·
              페이퍼 엔진 주문 만료 정산·LW3 종결 · 09-10 분봉 2일 실종 복구+MN-1.3 · 모의투자 월간 자동화 5링크 ·
              인수인계 "남은 것" 4건 실측 종결 · KR-2.4 승격+A5 재백필(09-04) · PF-1.2 소비경로 배선(발효는 registry 미등록).
            ★ 함정 모음(cron KST 시각은 예정일 뿐·intraday-alert 드롭·타임존 감사·asof_join_kr 의도된 PIT 등)은
              이력 파일 맨 위 이월분에 원문이 있다.
```

### 문서 지도

```
계약      docs/MN-1.0-분봉Raw저장계약.md        분봉 (현재 트랙)
          docs/BF-1.1-백필계약.md               manifest·인수 조건의 원 계약
          docs/A3b-1.0-배당EPS계약.md           A3b (구현 완료·실행 대기)
          docs/A5-1.0-입출력계약.md
완료기록   docs/control/완료-이력.md             프로젝트 전체 완료 로그(2026-09-06 분리)
          docs/A3-완료기록.md · docs/A3-회고-재사용패턴.md
          docs/operations/minute-실측기록.md    VM·smoke·첫 Broad 수집 실측치
교훈      docs/LESSONS.md                       51개 전문. 아래에는 일곱만 둔다
운영      docs/operations/test-guide.md         테스트·수집·게이트 검증 명령 전문
          docs/operations/data-source-availability.md   막힌 소스 (재론 금지)
결정 기록  **셋 다 닫혔다 — 대기 중인 🔴은 없다**(2026-09-11 확인). 셋을 지우지 않고
          기록으로 남기는 이유는 '무엇을 왜 그렇게 정했나'가 재론을 막기 때문이다
          docs/A3b-결정브리프.md            안 A 채택(2026-08-10) · 실행 08-11~12 완료
                                          "이후 판단은 계약 문서가 갖는다"(§6)
          docs/FN-1.4-measured승격절차.md   승격 실행 2026-08-10 · 절차 문서지 브리프가
                                          아니다. 값·근거의 단일 출처는 정책의
                                          `promotion` 블록(현 파일은 이미 FN-1.8)
          docs/A2a-증분화-결정브리프.md      STOP 종결(2026-09-11) — 완료-이력.md 참고
협업      CHATGPT.md                            ChatGPT의 진입 규칙
          docs/AI협업-업무분담.md               업무 경계 · 인계 형식 · 출처 규칙
          docs/control/TASKS.md                 **이력이지 착수 목록이 아니다**.
                                                다음에 할 일은 위 상태 블록이 정한다.
                                                2026-09-20 점검 — 명백히 낡은 행만
                                                고쳤고 나머지는 그대로 믿지 않는다.
                                                안 지우는 이유: A5-1.0 계약이
                                                그 파일의 LAB-* 주석을 인용한다
인수인계   docs/control/세션인수인계-YYYY-MM-DD[-b].md   ★ 저장소 루트에 쓰지 않는다
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

## 단기·초단기 연구 결과 기록 규칙 (확정 2026-09-21)

신호 실패와 비용 실패를 한 단어(REJECT)로 뭉개지 않는다. 판정 체계(INFORMATION → ECONOMIC → ROBUST)는
그대로이고 **기록 방식만** 두 가지 더한다.

1. **결과 표에 세 값을 표준 열로 낸다** — gross 평균(부트스트랩 신뢰구간) · 실제 비용 후 net · 손익분기 비용.
   시장별 실제 비용(KR 연속 ≈33.5bp · 종가·시가 단일가 23.5bp · 선물 1.4bp · ETF 5bp 등)을 옆에 적는다.
   **어느 시장·비용을 볼지는 사전등록에서 결과 전에 고정한다.** 결과를 보고 손익분기가 낮은 곳을 찾아 다니면 사후 조건 변경이다.
2. **머리말 `reason` 첫머리에 "신호: 있음/없음 · 경제성: 통과/미달"을 쓴다.** UI 목록은 `verdict` 한 단어만 보여준다.
   **기존 파일에 소급해서 붙이지 않는다**(기록 수정) — 이후 새 파일부터.

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
`opencode.cmd run`, 모델은 매 호출 `-m`으로 명시한다 — 생략하면 다른 기본
모델로 조용히 돈다(실측 2026-08-19). **1순위 `opencode/big-pickle`(동시 3개
병렬 가능) · 2순위 `opencode/nemotron-3-ultra-free`**(2026-09-05 사용자 지정).
★ 옛 기본값 `opencode/deepseek-v4-flash-free`는 **더 이상 존재하지 않는다** —
`opencode.cmd models` 실측(2026-09-05) 목록에 없다. 모델 이름은 조용히 사라지므로
쓰기 전에 `opencode.cmd models`로 확인한다. 지시문 서식과 배치 구성은
`docs/control/opencode-지시문-2026-09-05.md`.

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

**★ 등급은 '변경'에만 적용한다. '실행'은 아래 한 기준으로 따로 가른다.**
(push는 🟡에 한해 2026-08-17에 완화됐다 — 커밋하면 그대로 push한다)

**실행 기준 — 되돌릴 수 있고, 틀리면 게이트가 자동으로 잡는가**
(2026-09-04 전면 개정). 수단('수집이냐' · 'Actions냐 VM이냐')으로 가르면
모순이 생긴다 — A4 증분은 매월 무인 스케줄로 도는데 같은 걸 수동으로 돌릴 때만
확인받고 있었다. 소모하는 것과 되돌리는 비용으로 가른다.

```
바로 한다     저장소 데이터만 쓰는 순수 계산 백필·승격 — A5 채점 · exit-overlay ·
              docs/data/ 재빌드류 · deploy-pages · paper-trading-ui · 재배포
              증분 수집 — A4 --start (KRX 무료·한도 없음, 15분)
              정형 VM 운영 — git pull · 이미 등록된 systemd 유닛 재시작/1회 실행
확인받는다    대량 수집 — A2b · A3b/c/d · 분봉 · A4 전량 재수집
                (DART 4만콜·KIS 한도를 소진하면 그날 다른 작업까지 막힌다)
              대량 토큰 — 서브에이전트·OpenCode 위임, 대규모 파일 스캔·재분석
              되돌릴 수 없는 것 — 상태 디렉터리·아티팩트 삭제 · force push
              새 부작용을 여는 것 — 실주문 코드 변경 · 새 VM 유닛·nginx·인증서 ·
                새 외부 데이터 소스 통합
              🔴 정책·기준 변경 (위 등급 표 그대로 — 완화 대상 아니다)
```

**왜 순수 계산 백필이 안전한가**: manifest 계약이 인수 조건 실패 시 산출물 자체를
안 쓰고 커밋을 막는다 — 게이트가 자동으로 잡는 자리다. 반대로 **확인 게이트를
두는 것이 오히려 위험했다**: KR-2.4를 승격해 놓고 A5 재백필이 확인 대기로 밀려
`data/backfill/scores/`가 2.3 채점값으로 남아 있었다(2026-09-04 실측). 확인이
안전을 준 게 아니라 정합성 부채를 만들었다.

**왜 🔴는 완화하지 않는가**: 정책 임계값은 검증 강도 표의 "조용히 틀림 ×
되돌릴 수 없음" 칸 자체다. 느슨한 임계는 게이트를 통과하고, 통과한 데이터를
하류가 정상으로 읽는다 — 발견이 몇 주 뒤고 그때는 그 위에 쌓인 판정까지 무너진다.
실행은 되돌리면 그만이지만 기준은 되돌려도 이미 내린 결론이 남는다.
단 **registry 미등록 초안**(예: PF-1.2)은 어떤 엔진도 안 읽으므로 편집은 🟡이다 —
🔴은 registry에 등록해 발효시키는 순간이다.

판단이 갈리면 확인 쪽이다. **바로 한 것은 한 줄로 보고하고 되돌리는 방법을 같이
적는다** — 확인 게이트를 없앤 대가로 치르는 값싼 보험이다.

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

## 수집 VM 운영 기준 (2026-08-09 고정 · 2026-09-20 환경 정정)

### ★ 기계가 둘이고 ssh 별칭이 hostname과 어긋난다 (2026-09-20 실측)

조용히 틀린다 — 엉뚱한 기계에 붙으면 오류가 아니라 "파일이 없다"로 나온다.

```
ssh stock-new   129.225.145.14   hostname: stock           ← 작업 VM(1 OCPU · 10GB). 전부 여기다
                수집·페이퍼엔진·rv20·autotrader·크립토 슬리브·nginx·~/collector
ssh stock       129.225.177.125  hostname: stock-monitor   ← 옛 개인 감시 대시보드 하나뿐
                stock.service(포트 8000, ~/stock/server.py, git 아님) · 프로젝트 타이머 0개
                ★ 2026-09-20 stock.service disable --now 로 **정지**(폐기 시험 중).
                  ~/stock 앱은 git 에 없어 PC 로 백업해 뒀다(저장소 밖, KIS 키 포함).
                  ~/minute-raw 257일은 전수 대조 결과 저장소에 **전부 승격**돼 있다.
                  2주쯤 아쉬운 게 없으면 VM 삭제. 되살리려면 enable --now.
```

**문서·인수인계가 쓰는 "VM(`stock`)"은 hostname 기준이라 접속은 `ssh stock-new` 다.**

### 아래 제약이 나온 환경과 지금 도는 환경이 다르다 (2026-09-20 정정)

2026-08-09 에 이 절을 쓸 때의 전제는 **1GB 짜리 micro** 였다. 그 뒤 수집이 큰
기계로 옮겨갔는데 이 절은 따라오지 않았다 — 5주 넘게 없는 제약을 기술하고 있었다.

```
지금 도는 곳   ssh stock-new · VM.Standard.A1.Flex · 1 OCPU(Neoverse-N1/ARM) · 10GB
               Ubuntu 24.04 · Python 3.12 · pyarrow 17.0.0 · pandas 2.3.3
               (OCI 메타데이터 실측 2026-09-20. OS 는 9.7Gi 로 보고 - 펌웨어 예약분)
               실사용 717MB/9.7Gi · load avg 0.16 - 지금 사양이 이미 과잉이다
옛 전제        VM.Standard.E2.1.Micro · 1 OCPU · 1GB · Ubuntu 20.04 · Python 3.8
               = 지금은 폐기 시험 중인 stock-monitor(x86) 의 사양이다
무료 한도      A1.Flex 는 월 1,500 OCPU시간 + 9,000 GB시간 = 상시 구동 기준
               **2 OCPU · 12GB 가 상한**(MN-1.0 §확인한 한도, docs.oracle.com).
               널리 인용되는 "4 OCPU/24GB" 는 이 테넌시에 해당하지 않는다.
```

**그래서 아래 9개 제약은 "지금의 물리적 한계"가 아니라 "그때 그렇게 만든 이유"다.**
대부분(4~8)은 환경과 무관하게 여전히 옳다. 메모리에서 나온 것(1·2·3·9)만 지금은
실제보다 보수적이다 — **다만 완화는 별도 결정이다.** 한도가 늘었다는 이유만으로
동시성을 올리면 이번엔 KIS 쪽 한도에 걸린다(그 벽은 메모리가 아니다). 지금 바꿀
이유가 없으므로 그대로 둔다. 바꾸려면 RSS 재측정부터 한다(9번 그대로).

옛 결정의 취지는 유효하다: **새 VM을 전제로 코드를 쓰지 않는다** — 환경이 바뀌면
코드가 아니라 실행 환경만 옮긴다. 실제로 그렇게 옮겨졌다.

아래는 그 1GB 환경에서 실측으로 얻은 규율이다.

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

~~**Python 3.8이라 pyarrow는 구버전으로 고정된다.**~~ **틀렸다(2026-09-20 실측)** —
지금 VM 은 Python 3.12 · pyarrow 17.0.0 이다. 그래도 **뒷문장은 그대로 유효하다**:
결정적 쓰기 같은 성질은 pyarrow 버전의 함수이므로 VM 에서 다시 잰다
(`scripts/check-vm-readiness.py`). 실제로 이 차이에 한 번 물렸다 — 로컬 pyarrow 25 는
상위 `date=` 디렉터리를 hive 파티션으로 되붙이지 않는데 VM 의 17 은 되붙여서,
분봉 이틀이 사라지는 동안 로컬 회귀는 초록이었다(MN-1.3 항목 참고).
**로컬에서 초록이라고 VM 에서 초록이 아니다.**

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
`export PYTHONIOENCODING=utf-8` 를 **먼저** 한다 — 없으면 cp949가 이모지에서
죽어 가짜 실패 3건이 난다.

★ `research/strategy-lab/tests/` 의 `ok()` 헬퍼는 예외를 안 내고 실패를 세기만
한다(`main()`이 `exit(1)`). pytest는 `main()`을 안 부르므로 **9개 파일 212건의
체크가 조용히 안 보였다** — 2026-09-11 에 `tests/conftest.py` 로 닫았다(모듈의
`failed` 증가를 report 단계에서 실패로 바꾼다). **teardown 훅으로 하면 안 된다** —
SetupState가 깨져 다음 테스트까지 ERROR가 번진다(실측).

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
