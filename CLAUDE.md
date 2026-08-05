# CLAUDE.md — 주식 스코어링·모니터링 프로젝트

이 파일은 Claude Code가 매 세션 자동으로 읽는다. 길어지면 매 요청의 토큰 비용이 된다.
상세 설계는 `docs/BF-1.1-백필계약.md`에 있고, 여기에는 **매번 지켜야 할 규칙만** 둔다.

```
Validated against
  정책     UN-1.2 · PR-1.0 · REG-1.3
  구현     46b2031   ← 이 문서가 검증된 마지막 구현 커밋
  완료     A0.5 · A0.7 · A1a · A1b (실행) · A2a (구현, 첫 수집 대기)
  다음     A2a 첫 수집 → A2b 커버리지 정찰
```

`git log --oneline 46b2031..HEAD -- lib scripts config .github`가 비어 있지 않으면
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

진단 계약은 `scripts/verify-diagnostics.js`의 단계별 표 하나가 단일 출처다.
워크플로에 검사를 인라인하지 않는다 — 계약이 워크플로 수만큼 복사되면 필드를 늘릴 때
한 곳만 고치는 경로가 생긴다. 새 단계를 추가하면 이 표에 `required`·`trueFlags`를 등록한다.

**정책 버전을 올리면 그 정책을 읽는 단계를 상류부터 순서대로 재실행한다.**
`verifyUpstream()`은 데이터 해시만 보므로 상류 manifest의 옛 `policyHash`는 그냥 통과한다.
재실행은 무해한 연산이 아니다 — A1a는 KIND를 다시 읽으므로 산출물이 바뀔 수 있고,
바뀌면 하류 수치도 따라 바뀐다. 정상이며, 재실행 후 행 수 확인이 절차의 일부다.

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
pip install pandas requests lxml html5lib
node --version   # 20 이상

# 시크릿 (셸 세션에만. 파일에 쓰지 말 것)
export DART_API_KEY='...'

# 테스트 (외부 네트워크 불필요)
node scripts/test-policies.js
node scripts/test-engine-v2.js
node scripts/test-classifier.js
node scripts/test-state-infrastructure.js
node scripts/test-universe-a1b.js       # A1b 산출물이 있어야 한다

# 수집 스크립트 (외부 네트워크 필요)
python scripts/build-dart-corpcode.py   # A0.7 — DART_API_KEY 필요
python scripts/build-universe-a1a.py    # A1a — KIND

# A1b는 네트워크를 쓰지 않는다 (입력 3개가 모두 커밋된 산출물)
python scripts/build-universe-a1b.py
node scripts/verify-diagnostics.js A1b

# 게이트 검증 — 인수 조건을 강제 실패시킨다
A1A_FAIL_INJECTION=gate-test python scripts/build-universe-a1a.py; echo "exit=$?"
A1B_FAIL_INJECTION=gate-test python scripts/build-universe-a1b.py; echo "exit=$?"

# 로컬 실행 후 반드시
git checkout -- data/
```

`*_FAIL_INJECTION` 훅은 **실패만 만들 수 있고 통과는 만들 수 없다.** 한 방향 훅이라
남겨둬도 나쁜 데이터를 밀어 넣는 통로가 되지 않는다. 새 단계에도 같은 형태로 붙인다.

---

## 데이터 소스 가용성 (실측 확정, 재론 금지)

| 소스 | 결과 |
|---|---|
| KRX 개별종목 일봉 | 가용 |
| KRX 전종목 스냅샷 | **영구 차단** — 세션 시드 후에도 `400 LOGOUT`. 코드로 우회 불가 |
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
```
