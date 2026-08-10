# 로컬 실행·테스트 명령

`CLAUDE.md`에서 분리했다(2026-08-10). **삭제가 아니라 이동이며 원문 그대로다.**

매 세션 읽을 필요가 없어서 옮겼다. `CLAUDE.md`에는 찾는 법만 남겼다 —
"회귀는 `scripts/test-*.{py,js}` 다. `ls`로 찾아 변경 영역의 것만 돌린다."

이 목록은 낡을 수 있다. **`ls scripts/test-*`가 정본이고 여기는 주석이다.**
새 테스트를 추가했는데 여기 없다고 해서 안 돌려도 되는 것이 아니다.

---

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
python scripts/test-run-minute-daily.py    # 상시 러너의 날짜 선택·재시도 경계
python scripts/test-minute-universe.py     # 분봉 유니버스 스냅샷 PIT (합성 픽스처)
python scripts/test-alive-monitor.py       # 수집 감시기 (합성 픽스처)
python scripts/test-probe-t1-minute.py     # T1 정찰 — 미측정을 미측정으로 적는가
python scripts/smoke-minute-kis.py --selftest  # smoke 러너 자체 검증 (네트워크 불필요)

# 분봉 상시 수집 — 무엇을 돌지 확인 (네트워크 불필요)
python scripts/run-minute-daily.py --dry-run --days 3

# T1 정찰 — 표본과 대상 확인 / 누적 요약 (네트워크 불필요)
python scripts/probe-t1-minute.py --dry-run
python scripts/probe-t1-minute.py --report

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
