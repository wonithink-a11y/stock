# CLAUDE.md — 주식 스코어링·모니터링 프로젝트

이 파일은 Claude Code가 매 세션 자동으로 읽는다. 길어지면 매 요청의 토큰 비용이 된다.
상세 설계는 `docs/BF-1.1-백필계약.md`에 있고, 여기에는 **매번 지켜야 할 규칙만** 둔다.

```
Validated against
  정책     UN-1.2 · PR-1.4 · FN-1.3 · REG-1.5
  구현     55c72a0   ← 이 문서가 검증된 마지막 구현 커밋
  완료     A0.5 · A0.7 · A1a · A1b · A2a · **A3** 실행 완료
           A3 종료 2026-08-08 — 태그 a3-complete → d605297
             법인 3801/3801 · 레코드 24750 · 2015~2025
             coverageRate 0.9604 · periodEndParsedRate 1.0
             인수 조건 acceptancePassed true · FAIL 0 · WARN 0
             docs/A3-완료기록.md · docs/A3-회고-재사용패턴.md
           A2b 구현 완료(PR-1.4) — 수집 미실행
           A4 가용성 확인 완료 (KRX bld 차단 · naver 축 확인, 계약 미정)
           A5 프레임워크 구현 완료 (lib/a5 — PIT·레지스트리·리졸버, 회귀 45건)
           A 분봉 T0 정찰 완료 2026-08-09 — MN-1.0 §6 빈칸 9/11 실측
             보존 246영업일 · 120건/호출 · 시각커서 · 수정주가축(A2a와 동일)
             캔들 시작시각 기준 · cntg_vol은 구간 · 휴장일은 직전영업일 대체
             scripts/probe-minute-kis.py · data/backfill/_probe-minute-kis.json
           A 커버리지 정찰·유니버스 정책 확정 2026-08-09 — MN-1.0 §6.2 · §6.3
             절벽은 20억. 100억↑ 커버리지 1.000·최장결측 2분. 결측은 중반에 몰린다
             Core 200억↑ · Extended 50~200 · Conditional 20~50 · Broad 전체
             수집 대상과 분석 대상을 분리한다 — 유니버스로 Raw를 거르지 않는다
           A 실행환경 확정 2026-08-09 — MN-1.0 §1.1. 문서에 TBD가 없다
             상시 VM(Oracle Always Free) · 블록 볼륨(주) + Object Storage(사본)
             ★ 유휴 회수 조항: 7일간 CPU p95 20% 미만이면 인스턴스가 회수된다
               우리 워크로드가 정확히 걸린다. PAYG 업그레이드 여부는 사람의 결정
           A Collector v1 + 유니버스 스냅샷 완료 2026-08-09 — 회귀 48+20건
             parquet 왕복 실증 · 결정적 쓰기 · 저장 실측 행당 10.95B
             scripts/collect-minute-kis.py · config/policies/minute.v1.json
             요청일자 게이트(P0) · EGW00201 재시도·backoff · resume · manifest
             gapReason(왜 데이터가 없나)과 failureClass(왜 수집이 실패했나)를 가른다
             T1이 정할 것은 policy.pendingT1에 격리 — 기본값을 확정으로 읽지 않는다
             scripts/build-minute-universe.py — selectedAt 스냅샷. 미래참조 차단
             Core 182 · Extended 208 · Conditional 233 (2026-08-03 기준)
           A VM 준비 완료 2026-08-10 — 기존 stock-MonitorAlways 사용
             readiness PASS: pyarrow·zstd·결정적 쓰기·parquet 왕복
             MemTotal 952MB · MemAvailable 539MB · 조각 피크 RSS 167MB
             ~/collector (코드) · ~/collector-venv (venv·.env·토큰캐시)
             기존 /home/ubuntu/stock 은 건드리지 않는다. 앱키도 다른 계좌다
           A Alive Monitor + smoke 러너 완료 2026-08-10 — 회귀 19+7건
             scripts/alive-monitor.py   OK/PENDING/STALE · 상태 무저장 · fail-soft
             scripts/smoke-minute-kis.py  GO/NO-GO 15항목 자동 판정
           A 10종목 smoke GO 2026-08-10 — 15항목 전부 PASS
             3,810행 = 381 x 10 (결측 0) · 50호출 = 5 x 10 (T0 예측과 일치)
             9.4초 · 피크 VmHWM 116.5MB / 한도 261.6MB · shaMatch true
             EGW00201 0건 · 기존 모니터 생존 · OOM 없음
             → Broad 2,559종목 환산 약 40분/일
  다음     A 분봉이 주선이다. B·C·D는 여전히 독립이며 급하지 않다
           A1 Broad 수집 실행 ← 여기. MN-1.0 부록 5번부터
              추가 검증 단계를 만들지 않는다. smoke가 관문이었다
           A2 Broad 당일 증분 상시화 (systemd timer 또는 cron)
              미루면 손실이 하루씩 누적된다. 오늘 안 받은 하루는 못 받는다
           A3' T1 정찰 7일 (§6.1) — Broad와 병행. 재현성이 핵심
              pendingT1 블록만 승격하면 된다. 코드는 안 고친다
           A4' Core 182종목 246일 백필은 T1 결과 뒤 (≈224,000호출)
           B FN-1.4 승격    measured가 생겼다. docs/FN-1.4-measured승격절차.md
                            A3 재수집 불필요 — 임계는 collectionContract에 없다
           C A3b 결정       사람의 판단. docs/A3b-결정브리프.md
                            alotMatter만으로 availableWeight 0.4475→0.68 (임계 0.6)
           D A2b 수집 실행  (PR-1.4는 A2a 재실행 사유가 아니다)
  분봉     MN-1.0에 TBD가 없다. 남은 미결은 약관 Q1/Q2(§7)와 T1 정책뿐이다
           소스 KIS 단일 · naver는 알림 유지 · Raw는 저장소 밖(parquet zstd)
           parquet 쓰기는 결정적이다(실측) — sha256으로 재빌드 동일성을 증명한다
           저장 규모 실측 행당 10.95B · Broad 연 1.52GB · Core 백필 0.18GB
```

`git log --oneline 44972a4..HEAD -- lib scripts config .github`가 비어 있지 않으면
이 문서가 구현보다 오래됐을 수 있다. 단계를 완료하거나 정책 버전을 올릴 때 이 블록을 갱신한다.

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
# 의존성
pip install pandas requests lxml html5lib pyarrow
node --version   # 20 이상

# 시크릿 (셸 세션에만. 파일에 쓰지 말 것)
export DART_API_KEY='...'

# 테스트 (외부 네트워크 불필요)
node scripts/test-policies.js
node scripts/test-engine-v2.js
node scripts/test-classifier.js
node scripts/test-state-infrastructure.js
node scripts/test-universe-a1b.js       # A1b 산출물이 있어야 한다
python scripts/test-price-a2a.py        # A2a 품질 판별 (합성 픽스처, 산출물 불필요)
python scripts/test-price-a2b.py        # A2b 상장기간 한정·exitAt 출처 (합성 픽스처)
python scripts/test-fundamentals-a3.py  # A3 PIT 계약·계정 매칭·resume 무결성 (합성 픽스처)
python scripts/test-analyze-a3.py       # A3 품질 분석기·QR-1.0 리포트 (합성 픽스처)
python scripts/test-pick-artifacts.py   # 샤드 아티팩트 선택 (재실행 시 어느 시도가 사는가)
node scripts/test-a5-framework.js       # A5 PIT 선택·피처 레지스트리·리졸버
python scripts/test-collect-minute-kis.py  # 분봉 Collector v1 (합성 픽스처, 네트워크 불필요)
python scripts/test-minute-universe.py     # 분봉 유니버스 스냅샷 PIT (합성 픽스처)
python scripts/test-alive-monitor.py       # 수집 감시기 (합성 픽스처)
python scripts/smoke-minute-kis.py --selftest  # smoke 러너 자체 검증 (네트워크 불필요)

# A3 수집 진행 확인 — A3 종료로 쓸 일이 없다 (_shards/가 finalize에서 삭제됨).
# 다음 수집기가 같은 형태를 쓰므로 명령 형태만 남긴다.
# python scripts/build-fundamentals-a3.py --summary

# A3 품질 분석 (읽기 전용. 산출물이 있으면 그것을, 없으면 수집 중간물을 읽는다)
python scripts/analyze-fundamentals-a3.py
python scripts/analyze-fundamentals-a3.py --holes   # 내부 구멍 법인 전체
python scripts/generate-quality-report.py           # QR-1.0 리포트 → stdout
python scripts/generate-quality-report.py --check   # 스키마 검사만

# 수집 스크립트 (외부 네트워크 필요)
python scripts/build-dart-corpcode.py   # A0.7 — DART_API_KEY 필요
python scripts/build-universe-a1a.py    # A1a — KIND
python scripts/probe-fundamentals-a3.py # A3 정찰 — DART_API_KEY 필요. 수집 아님

# A1b는 네트워크를 쓰지 않는다 (입력 3개가 모두 커밋된 산출물)
python scripts/build-universe-a1b.py
node scripts/verify-diagnostics.js A1b

# 게이트 검증 — 인수 조건을 강제 실패시킨다
A1A_FAIL_INJECTION=gate-test python scripts/build-universe-a1a.py; echo "exit=$?"
A1B_FAIL_INJECTION=gate-test python scripts/build-universe-a1b.py; echo "exit=$?"
A2B_FAIL_INJECTION=gate-test python scripts/build-price-a2b.py --finalize; echo "exit=$?"
A3_FAIL_INJECTION=gate-test python scripts/build-fundamentals-a3.py --finalize; echo "exit=$?"

# 로컬 실행 후 반드시
git checkout -- data/
```

`*_FAIL_INJECTION` 훅은 **실패만 만들 수 있고 통과는 만들 수 없다.** 한 방향 훅이라
남겨둬도 나쁜 데이터를 밀어 넣는 통로가 되지 않는다. 새 단계에도 같은 형태로 붙인다.

---

## 데이터 소스 가용성 (실측 확정, 재론 금지)

| 소스 | 결과 |
|---|---|
| 개별종목 일봉 | 가용 — 단 **naver 경로다**(pykrx `adjusted:true`). KRX 아님 |
| KRX bld 전체 (`getJsonData.cmd`) | **차단** — 전종목 스냅샷·개별종목 일봉·종목별 수급 전부 `400 LOGOUT`. 세션 시드·UA 무관 |
| naver 종목별 수급 | HTML 2005-01까지(20행/페이지) · JSON 최근 60거래일. 기관 '합계'만 |
| KRX 지수 | 차단 |
| KIND 상장법인목록 | 가용 (`corpList.do?method=download&searchType=13`, 2,802행, euc-kr) |
| KIND 상장폐지목록 | **경로 없음** — 파라미터 미반영 셸 페이지 |
| DART corpCode.xml | 가용 (법인 118,583 / stock_code 3,981) |
| DART list.json | 가용 (폐지 사유 복원 경로) |

`pykrx 1.0.51`에는 로그인 진입점이 없다. `KRX_ID`/`KRX_PW`는 위 경로들과 무관하다.

---

## 절대 공유 금지

`config.yaml` · `.token_cache*.json` · `deploy.conf` · `ssh-key-*.key` ·
DART/KIS/네이버 API 키 · 텔레그램·슬랙 토큰 · 대시보드 `?key=` 포함 URL

워크플로에서는 `${{ secrets.NAME }}` 플레이스홀더로만 쓴다.

---

## 교훈 (반복 방지)

```
16. EngineError의 코드 속성명은 errorCode다 (code 아님)
17. diff(+/- 마커)를 파일에 붙여넣으면 깨진다. 전체 파일 내용으로 전달한다
38. 재시도가 붙어 있다는 사실이 재시도가 도는 것을 뜻하지 않는다.
    _retry가 HTTP status를 안 보면 403/503에서 0회 돈다.
    requests.Response는 비어 있지도 예외도 아니라 '성공'으로 반환된다.
39. 중단 경로에도 진단 산출을 남긴다. 정찰의 산출물은 데이터가 아니라 패턴이다.
40. 판정 신호는 두 개를 쓰되 하나만 판정에 쓴다.
41. 증상 메시지가 원인을 지목하지 않는다.
    "KRX 로그인 실패"를 보고 시크릿을 넣었으나 실제 원인은 bulk 엔드포인트 차단이었다.
42. 파싱 성공은 전건 확보가 아니다.
    목록형 소스는 행 수와 기간 커버리지를 반드시 함께 본다.
43. manifest는 '파일이 안 바뀌었다'만 증명하지 '검사를 통과했다'는 증명하지 않는다.
    인수 조건 실패 시 산출물을 쓰면 하류가 깨진 데이터로 정상 통과한다.
44. 계약을 산출하는 쪽이 계약도 들고 있으면 둘이 같이 틀린다.
    같은 검사를 워크플로마다 복사하면 필드를 늘릴 때 한 곳만 고치는 경로가 생긴다.
    계약은 표 하나로, 검사자 쪽에 둔다.
45. 임계는 상류 게이트가 허용하는 구간보다 좁을 때만 정보가 된다.
    상류를 되풀이하는 임계는 통과율만 떨어뜨리고 새로 잡는 실패 모드가 없다.
46. 분할 축을 잘못 고르면 분할의 목적이 사라진다.
    A2를 수집/검증으로 나누면 병렬화도 못 얻고 미검증 산출물에 manifest를 찍게 된다.
    유니버스 축(A2a/A2b)이 두 목적을 다 만족한다.
47. 소스가 3개 연도를 한 번에 준다고 3개 연도를 그때 안 것은 아니다.
    DART 주요계정의 전기·전전기 열은 '그 보고서 접수일'에 알려진 값이다.
    호출량 이점이 시점(PIT)을 사면 안 된다 — 과거를 실제보다 늦게 안 것으로 기록한다.
48. 결측처럼 보이는 것이 양식일 수 있다.
    금융업 재무제표에는 유동자산·유동부채가 없다. 커버리지 분자에 넣으면
    업종 구성이 데이터 품질로 둔갑한다. 결측률을 재기 전에 분자가 무엇인지 먼저 정한다.
49. 조용히 무너지는 축은 게이트를 두 겹으로 건다.
    PIT가 뒤집혀도 점수·등급은 정상으로 보이고 백테스트만 좋아진다.
    그래서 인수 조건(FAIL)과 합성 픽스처 회귀를 둘 다 두고, 회귀는 수집 전에 돌린다.
50. 잴 수 없는 계약은 계약이 아니다.
    A3가 고른 fnlttSinglAcntAll에는 thstrm_dt가 없어(실측 0/240) 회계기간말을 못 읽는다.
    계약 1을 잴 수단이 없으니 수집기가 전건을 버린다 — 3일 수집 후에 드러났을 실패다.
    소스를 고를 때 '값이 있는가'만 보지 말고 '계약을 잴 필드가 있는가'를 함께 본다.
51. 정찰은 답을 확인하는 절차가 아니라 전제를 뒤집는 절차다.
    A3 정찰의 성과는 계획 검증이 아니라 엔드포인트 선택을 뒤집은 것이다.
    뒤집힐 수 없게 설계된 정찰은 돌릴 이유가 없다.
53. 실패의 정의는 단계마다 다르다. 상류에서 빌려온 서킷은 정상을 실패로 읽는다.
    A2a의 '연속 빈 응답 20건 → 중단'을 A2b에 복사하면 정상 수집이 죽는다 —
    A2b에서 빈 응답은 후보의 48%가 내는 기대 응답이다. 서킷은 예외만 세고,
    빈 응답의 과다는 즉시 중단이 아니라 인수 조건이 사후에 판정한다.
52. 대조군이 같은 경로인지 먼저 확인한다.
    "A2a 일봉은 되는데 수급만 막혔다"로 읽었으나 pykrx는 adjusted=true면 naver로 간다.
    대조군이 다른 호스트였다 — KRX bld는 처음부터 죽어 있었고 A2a가 그것을 안 썼을 뿐이다.
54. 완료를 저장하면 승인이 바뀌는 순간 낡는다.
    상태는 사실만 단조하게 축적하고 판정은 매번 계산한다.
    complete를 상태에 두면 그것을 맞추려고 상태를 다시 쓰게 되고, 그때 사실이 흔들린다.
    완료는 done의 개수가 아니라 '담당분이 남김없이 분해되는가'로 정의한다.
55. 재개 판정을 정책 version으로 하면 임계 하나가 며칠치 수집을 버린다.
    resume 호환의 기준은 '이 값이 달랐다면 어제 다른 레코드가 나왔는가'뿐이다.
    version 문자열은 그 질문의 거친 대리 지표이고, 거친 쪽으로 틀리면 손실이 조용하다.
56. 실패 분류의 기본값이 계약이다.
    모르는 실패를 '수집 불가'로 두면 새 오류 코드가 나올 때마다 공백이 조용히 넓어진다.
    모르는 것은 '아직 모른다'이지 '못 한다'가 아니다 — 기본값은 재시도 가능이다.
57. 모르는 것은 0이 아니다.
    분모가 없는 상태를 0으로 읽어 '남음 -1381'이 나왔다. 거짓 수치는 게이트도 오탐시킨다.
    잴 수 없는 것과 틀린 것을 구분하고, 잴 수 없으면 판정을 부정한다.
58. 부재의 증거가 부재가 아닐 수 있다.
    호출부에 timeout= 인자가 없다는 것으로 'timeout 없음'을 결론하고 그 위에 설계를 얹었다.
    실제로는 HTTPAdapter.send 몽키패치가 전역 기본값을 넣고 있었다.
    호출부만 보고 전역 설정을 확인하지 않으면 없는 결함을 고치게 된다.
59. 범위는 개수가 아니라 목록이 정한다.
    '9개 필드'로 적으면 나중에 하나를 빼거나 넣어도 여전히 참으로 읽힌다.
    계약의 범위는 리터럴 목록으로 못 박고, 바꾸려면 그 단언을 함께 고치게 한다.
60. 재개 가능성의 기준은 '결과에 영향을 주는가'가 아니라 '이미 모은 것을 다시 쓸 수 있는가'다.
    두 질문은 대개 같은 답을 주지만 갈릴 때가 있다.
    failureClassification은 그럴듯한 첫 질문으로는 계약이었고, 옳은 두 번째 질문으로는
    아니었다 — retryable은 어떤 게이트도 가르지 않고 다음 재시도에서 다시 계산된다.
61. 기록할 자리와 검사할 자리는 다르다.
    manifest에 계약 해시를 남기는 것은 산출물이 지워진 뒤의 유일한 증거라 가치가 있다.
    그러나 그 값이 나온 상태와 대조하는 것은 구성상 항상 참이라 아무것도 잡지 못한다.
62. 계약은 '병합이 올바르다'가 아니라 '병합 대상이 자기 것뿐이다'로 고정한다.
    샤드 아티팩트가 _shards/ 전체를 올려 남의 전날 상태로 오늘치를 덮을 수 있었다.
    첫 실행이 무사했던 것은 그때 그 디렉터리가 비어 있었기 때문이다 —
    우연한 안전은 설계가 아니다. 범위를 좁히고 그 범위를 테스트로 못 박는다.
63. 관측이 내구성을 막아서는 안 된다.
    사람이 읽는 요약 스텝이 죽자 다음 커밋 스텝이 스킵돼 7샤드의 하루치가 날아갔다.
    앞 단계 게이트를 완화해 막으려던 실패가 한 층 아래에서 그대로 재발했다.
64. 미커밋 수정을 git checkout으로 되돌리지 않는다.
    변이 테스트 후 원복하려다 아직 커밋하지 않은 수정까지 날렸다.
    되돌릴 것이 있으면 먼저 복사본을 만든다.
65. 규율은 예외 경로를 막지 못한다.
    "crtfc_key는 params로만 넘긴다"고 적어뒀지만 requests 예외가 URL을 통째로 싣고
    그것을 진단에 저장했다. 시크릿은 규율이 아니라 문자열이 나가는 지점에서 지운다.
    자르기 전에 지운다 — 순서가 반대면 잘린 조각이 남는다.
66. 보존해야 하는 것은 집합이 아니라 상태다.
    hardSkipped를 old ⊆ new로 걸면 '실패하던 법인이 성공하는' 정상 전이를 거부한다.
    옳은 식은 old.hard ⊆ new.hard ∪ new.done — 여전히 실패 중이거나 해결됐거나다.
67. 개수는 원인을 지목하지 못한다. 세는 자리에서 갈라 둔다.
    hardErrors 하나로는 전송 장애·게이트웨이 오류·DART 업무 오류가 한 칸에 들어간다.
    셋은 대응이 전부 다르다 — 기다린다 / 키를 본다 / 승인한다.
    사후에 문자열을 파싱해 가르려 하지 말고 원인을 아는 자리에서 라벨을 붙인다.
68. 분해를 합칠 때는 분모를 먼저 본다.
    시도 단위 실패와 법인-연도 단위 실패를 한 표에 넣으면 재시도 횟수가 실패율이 된다.
    두 표로 두면 그 차이가 '재시도가 실제로 돌았는가'를 말해준다(교훈38의 관측면).
69. 되돌리지 않는 몽키패치는 뒤따르는 테스트를 조용히 무력화한다.
    fake_run이 남긴 가짜 dart_call을 새 테스트가 검사하고 있었다.
    실물을 대상으로 하는 테스트는 import 직후의 참조를 잡아 쓴다.
70. 관측 경로는 자기 자신 때문에도 죽는다.
    --summary가 cp949 콘솔에서 em-dash 하나로 UnicodeEncodeError를 냈다.
    사람이 읽는 출력은 errors='replace'로 열어둔다 — 읽기 어려운 것이 못 읽는 것보다 낫다.
71. 전이 검사는 실행된 것만 본다.
    예산 소진으로 즉시 끝난 샤드·잡이 죽어 안 돌아간 샤드는 전이가 아예 보지 않는다.
    실행 여부와 무관한 성질(집합의 배타성·계약의 존재)은 읽는 쪽에서 다시 잰다.
    "지금 코드로는 그럴 수 없다"는 상태가 지켜주는 것이 아니라 코드의 현재 모양이
    지켜주는 것이다 — 리팩터링 한 번이면 사라진다.
72. 유도한 값으로 그 값을 낳은 식을 검사하면 항상 통과한다.
    conservationOk는 remaining을 assigned-done-hard로 만든 뒤 그 등식을 다시 봤다.
    구성상 참이라 영원히 빈 배열이었다 — 통과가 정보를 주는지 먼저 묻는다(교훈61).
    그리고 그런 필드는 주석을 달지 말고 지운다. 남아 있으면 true가 건강으로 읽힌다.
73. 검사를 추가하기 전에 그 검사가 어느 범위에서 잴 수 있는지 먼저 정한다.
    T 전이(두 상태) · S 상태(하나) · M 병합(전 샤드). 무리마다 사는 자리가 다르다.
    병합에서만 잴 수 있는 것을 샤드 쪽에 두면 각 샤드는 늘 정상으로 보인다.
    같은 무리 안에서도 출처를 갈라 본다 — M2는 상태를, M3는 산출물을 본다.
    가능하면 쓰는 시점에 강제한다(save_progress). 읽는 시점의 발견보다 안전하다.
74. 계약은 위반을 말하고 복구를 말하지 않는다.
    "collect를 한 번 더 돌리면 채워진다"를 게이트 메시지에 넣으면 위반이
    '아직 안 한 일'로 읽힌다. 유효하지 않은 상태는 사유와 무관하게 유효하지 않다.
75. 없는 행은 이유를 말하지 않는다.
    산출물의 공백이 정상 사실인지 손실인지는 응답을 본 수집기만 안다.
    그 자리에서 남기지 않으면 재수집 없이는 영영 얻을 수 없다 — 원시 사실은
    수집 단계에서, 파생 결과(패턴·비율)는 저장하지 말고 계산한다.
    '조회하지 않음'과 '조회했더니 없음'도 다르다. 경계를 함께 남긴다.
78. 재실행은 그 실행이 시작된 커밋을 다시 돈다.
    main을 고쳐도 옛 실행을 Re-run하면 옛 코드가 돌아 같은 오류가 영원히 난다.
    이미 고친 결함을 다시 고치러 가기 전에 로그의 SHA부터 본다 — 그래서 찍는다.
79. 덮어쓰기는 '나중 것이 더 낫다'를 전제한다. 그 전제부터 확인한다.
    재실행은 커밋된 상태에서 다시 시작하고 앞 시도의 아티팩트를 보지 않는다.
    일 한도를 앞 시도가 태웠으면 재실행이 덜 진행하고 끝날 수 있다 —
    이름을 겹치지 않게 두고 병합에서 '더 나아간 것'을 고른다.
76. 소비자의 입력 계약을 생산자가 닫히기 전에 읽는다.
    A3 수집을 마친 뒤 A5에 착수했다면 EPS·배당·주식수 부재를 그때 알았고,
    그때는 재수집 말고는 길이 없었다. 다음 단계가 무엇을 먹는지 먼저 본다.
80. '네트워크를 쓰지 않는다'와 '그 라이브러리가 없어도 된다'는 다른 말이다.
    지연 import는 앞엣것을 위한 장치이지 뒤엣것을 보장하지 않는다.
    finalize 잡에 requests를 안 깔았는데 회귀가 run_shard를 밟아 게이트가 죽었다.
    합성 픽스처라 호출은 안 나가지만 모듈은 있어야 한다.
    잡의 의존성을 스텝의 실제 필요가 아니라 잡 이름의 성격으로 정하면 갈린다.
82. 문법 호환은 API 호환이 아니다.
    ast.parse(feature_version=(3,8))로 8개 스크립트를 전수 통과시켜 놓고
    Path.write_text(newline=)에서 죽었다 - 그 인자는 3.10부터다.
    파서는 구문만 본다. 런타임 API 차이는 그 검사가 구조적으로 못 잡는다.
81. 성공 코드는 '내 질문에 답했다'를 뜻하지 않는다.
    KIS 분봉은 파싱 안 되는 날짜에 오류 대신 최근 영업일을 rt_cd=0으로 준다.
    하이픈 하나로 전 구간이 "있음"이 되어 보존 기간을 3년으로 읽었다 — 실제는 246영업일.
    응답이 요청의 식별자(일자·종목)를 담고 있는지를 성공 조건에 넣는다.
    같은 이유로 휴장일도 빈 응답이 아니라 직전 영업일로 대체된다.
77. 없는 것이 스펙의 누락인지 소스의 부재인지 먼저 가른다.
    A3의 계정 일곱은 주요계정에 있는 것을 다 가져온 것이 맞았다.
    빠진 EPS는 다른 엔드포인트(alotMatter)에 있었다 — 고칠 자리가 전혀 다르다.
    스펙을 늘리려다 수집 계약 해시를 바꾸면 이미 모은 것을 버린다.
```
