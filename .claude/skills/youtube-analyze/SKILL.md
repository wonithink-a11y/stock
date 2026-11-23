---
name: youtube-analyze
description: 유튜브 영상 링크를 Gemini API 로 자세히 분석(요약·주장·언급 종목·숫자)한 뒤 그 분석으로 검증·후속 진행까지 잇는 절차. "이 유튜브 분석해줘", "영상 내용 정리해줘", "유튜브 링크 줄게", "이 방송에서 말한 전략 검증해줘", "유튜브 보고 아이디어 뽑아줘" 같은 말이 나오면 반드시 이 스킬을 쓴다. 영상은 Claude 가 직접 못 본다 — Gemini 가 보고, Claude 는 그 결과를 검증한다.
---

# 유튜브 분석 → 검증 → 후속

이미 있는 `scripts/yt-digest.py`(Gemini 에 영상 URL 을 그대로 넣는다, 공개 영상만)를 한 영상에 쓴다. 새 코드를 만들지 않는다.

## 0. 먼저 — 비용·위치
- 무료: YouTube URL 입력은 문서상 preview·무료, **무료 등급은 하루 8시간 분량까지**(ai.google.dev video-understanding, 2026-11-23 확인). Flash 무료 하루 약 20건(429 나면 flash-lite 폴백).
- 유료 등급($1.50/$7.50 per 1M 토큰, 월 정액 없음)으로 넘어가는 건 사용자 확인 후에만(규칙 9) — 그때마다 "유료, 사용량 비례"를 다시 적는다.
- **실행은 GEMINI_API_KEY 가 있는 곳(PC `.env`)에서만.** 클라우드 세션엔 키가 없다. 키는 코드·로그에 쓰지 않는다(규칙 2).

## 1. 분석 (Gemini) — 기본은 정밀 모드
```bash
python scripts/yt-digest.py --deep <영상ID> [모델] [--once]   # 정밀. 출력만(JSON), 저장·발송 없음
python scripts/yt-digest.py --test <영상ID> [모델]            # 빠른 요약(참고용) — 사용자가 "자세히"를 원하면 쓰지 않는다
```
`--deep` 은 "줄이는 요약"이 아니라 **빠뜨림 없는 보존**이 목표다(`DEEP_PROMPT`). 호출 2번: ① 분석 ② 같은 영상에서 **누락만 다시 찾아** 합친다(`--once` 면 ①만 — 토큰 절반).
출력 필드: timeline(시각·화자·구간별 모든 요점) · claims(fact/opinion/forecast/advice/anecdote + 근거) · entities(종목·티커·인물·도구·명령어·URL 전부) · numbers · rules(매매 규칙 단계별) · missing_conditions(말하지 않은 조건) · claims_performance(성과 주장의 기간·표본·비용) · inconsistencies · qa · unclear · notes_external(영상 밖 정보, 구분 표시).
토큰·시간은 긴 영상일수록 크다(90분 방송 한 번에 수 분). 무료 한도(하루 8시간·Flash 약 20건)를 2호출이 먹는 점을 감안한다.
프롬프트는 결과를 본 뒤 고치지 않는다 — 고치면 이전 분석과 비교가 안 된다. 라이브 중인 영상은 끝난 뒤에.

## 2. 저장 금지
**남의 콘텐츠 요약이라 저장소·공개 대시보드·Actions 로그에 올리지 않는다**(yt-digest 규칙). 그래서 Actions 워크플로로 만들지 않았다 — 공개 저장소의 로그·아티팩트는 공개다. 대화 안에서만 쓰고, 남길 건 **내 판단(검증 결과·REJECT 사유)** 뿐이다.

## 3. 검증 (Claude)
출력을 `inspect-social-post` 절차에 넘긴다(claims·rules·claims_performance 가 그대로 "주장 쪼개기"의 입력이다): 주장 쪼개기 → 출처·설치 명령·수치 확인 → 이미 있는 기능과 겹침. Gemini 요약은 **주장일 뿐 사실이 아니다**(절대 규칙 1: 맥락용, 점수·매매 불사용). 요약이 영상 원문과 다를 수 있음을 caveats 로 같이 말한다.

## 4. 후속
- RP-2.0: 문턱이 모호하거나 사후 분류인 주장은 WATCH 로 멈추지 말고 S 놀이터(`research/sandbox/`)에서 바로 돌려 본다.
- 검증을 통과한 전략·신호 아이디어만 `idea-intake` 장부에 적고 `preregistered-research` 로 넘긴다. 영상의 성과 주장은 근거가 아니다 — 같은 표본 재판정 금지·사전등록 규칙 그대로.
- 종목 언급은 관찰 메모일 뿐 추천이 아니다. 주문·실계좌 연결 금지.

## 보고 형식
결과 한두 줄 + 위험·미확인(요약 오류 가능성, 검증 못 한 수치)만. 영상 전문을 다시 풀어 쓰지 않는다.
