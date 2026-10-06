[작업] DART 정기보고서 '사업의 내용' 원문에서 정해진 항목만 뽑아 JSON 하나로 저장한다.

[입력] {INPUT} (이 파일만 읽는다)
[출력] {OUTPUT} (이 파일 하나만 쓴다)

[제약]
- 이 지시 파일과 입력 파일 외에는 열지 않는다. 저장소를 검색하지 않는다. 스크립트를 실행하지 않는다. 서브에이전트를 쓰지 않는다.
- git commit / push 하지 않는다.
- 원문에 없는 내용은 쓰지 않는다. 못 찾으면 null. 추정·계산·외부 지식 금지(표에 합계가 없으면 합계를 만들지 않는다).
- "quote" 는 원문 한 줄(문장 또는 표 한 행)을 글자 그대로 복사한다. 떨어진 여러 줄을 하나로 붙이지 않는다. 요약·의역 금지.
- 숫자는 원문 단위 그대로 옮기고 unit 에 단위를 적는다.
- 출력은 아래 형식의 JSON 하나. 주석·설명 문장 금지. 첫 필드 "model" 에 실행 모델 이름을 적는다.

[형식]
{
  "model": "...",
  "ticker": "{TICKER}",
  "segments": [ {"name": "사업부문 또는 제품군", "period": "원문 기간 표기", "revenue": 숫자|null, "unit": "원문 단위", "share_pct": 숫자|null, "quote": "..."} ],
  "export": {"domestic_pct": 숫자|null, "overseas_pct": 숫자|null, "period": "...", "quote": "..."},
  "top_customer": {"max_single_share_pct": 숫자|null, "names_disclosed": true|false|null, "period": "...", "quote": "..."},
  "capacity": [ {"period": "...", "utilization_pct": 숫자|null, "quote": "..."} ],
  "order_backlog": {"exists": true|false|null, "amount": 숫자|null, "unit": "...", "quote": "..."},
  "rnd": {"ratio_pct": 숫자|null, "headcount": 숫자|null, "quote": "..."},
  "patents_registered": {"count": 숫자|null, "quote": "..."},
  "growth_drivers": [ {"name": "...", "evidence": "원문 근거 한 줄 요약", "stage_candidate": 1~5|null, "quote": "..."} ]
}

[정의]
- segments: 사업부문·제품군별 매출 표의 **표에 나온 모든 기간**을 한 줄씩(기간 × 부문). 비율 칸이 있으면 share_pct 도 채운다.
- export: 가장 최근 기간의 내수(국내)·수출(해외) 비중. 비율이 원문에 없으면 null.
- top_customer: 가장 최근 기간 공시된 단일 매출처 최대 비중(%). 사명이 'A사'처럼 가려져 있으면 names_disclosed=false.
- capacity: 가동률이 적힌 기간마다 한 줄.
- order_backlog: 수주잔고가 있다고 적혀 있으면 true(금액이 있으면 amount), '해당사항 없음'·'수주 현황 없음'이면 false.
- rnd: 가장 최근 기간 연구개발비의 매출 대비 비율, 연구개발 인력 합계.
- patents_registered: 등록 특허 수. 표에 합계 행이 있으면 그 값, 없으면 null 로 두고 근거 행을 quote 로.
- growth_drivers: 원문이 성장·신사업·신제품·해외 확대로 서술한 것. 판매 전략·시장 일반론은 넣지 않는다. stage_candidate 는 원문 근거만으로
  1=기술 확보(개발·특허) 2=고객·수주 3=생산·양산 4=매출 발생(그 사업의 매출 수치가 원문에 있음) 5=이익·현금(그 사업의 이익이 원문에 있음).
  그 사업 자체의 매출 수치가 원문에 없으면 4 이상을 주지 않는다.
