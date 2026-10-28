# 공급망 지도 수집·확장 스크립트 (2026-10-28 세션에서 쓴 것)

정본 데이터는 `config/supplyChain.json`, 빌더는 `scripts/build-supply-chain.py`(`--selftest`), 화면은 대시보드 시장·섹터 > 공급망.
여기 스크립트는 **연결 후보를 찾는 1회성 수집기**다. 결과는 사람이 읽고 확인한 것만 정본에 넣는다(공시 접수번호·원문 인용 필수).
저장소 밖 작업 폴더를 쓴다 — 아래 `SP`(스크래치 경로)·`ROOT`는 스크립트 맨 위에서 자기 환경에 맞게 고친다.

| 파일 | 하는 일 |
|---|---|
| `contract_year.py` | DART 단일판매·공급계약 공시 목록(3개월씩 끊어 1년) + 원문 저장. 이미 받은 원문은 건너뜀. DART 동시 2개 이하 |
| `contract_parse.py` | 저장한 계약 공시 원문에서 계약상대·금액·매출액대비(%) 추출 → `contract_parsed.json` |
| `add_contracts.py` | 계약상대 이름을 기준 기업과 맞춰 `config/supplyChain.json` 에 연결 추가(모회사·자회사 중복, 이름 비슷한 오매칭 제외) |
| `enrich_items.py` | 계약 연결의 품목명을 원문(계약 구분/내용·체결계약명 두 양식)에서 채움 |
| `sec_wide.py` | S&P500·나스닥100 10-K + EDGAR 전문검색(허브 이름) 문서에서 허브 기업 언급 문장 추출 |
| `sec_8k.py` | 허브 이름으로 8-K 검색 → 문서 읽기. 공급 관계가 분명한 것만 정본에 넣는다 |

- SEC 호출은 연락처가 들어간 User-Agent 가 필요하다(`SEC_USER_AGENT`, VM `.env` 에만 있음). 스크립트는 `ua.raw` 파일을 읽고 바로 지운다 — 값을 저장소에 남기지 않는다.
- 해석(파싱)은 저장본으로 한다. 원문은 저장소 밖(`C:\Users\User\supply-chain-cache`)에 둔다.
