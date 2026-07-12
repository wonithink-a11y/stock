# stock-scoring-app

한국 주식 통합 스코어링(v2 엔진)을 GitHub Actions + GitHub Pages로 자동화한 웹앱.

- **매일 자동**: 평일 장 마감 후 시세·수급 수집 → 스코어링 → 대시보드 갱신 → 텔레그램/슬랙 알림
- **매주 자동**: 누적 이력으로 실데이터 백테스트 리포트 (모델 성적표)
- **대시보드**: 종목 스코어 / 시장 국면·포트폴리오 신호 / 추천 이력 / 백테스트 4개 탭

설치·운영 방법은 [SETUP.md](SETUP.md) 참고.

```
├── .github/workflows/   # daily-analysis(평일), weekly-backtest(일요일)
├── lib/                 # 스코어링 엔진 (stock-scoring 프로젝트 v2와 동일)
├── scripts/             # collect(수집) → analyze(분석) → notify(알림), backtest-report
├── config/              # watchlist·holdings·fundamentals·macro·criteria (여기만 편집하면 됨)
└── docs/                # GitHub Pages 대시보드 + 결과 JSON (Actions가 자동 커밋)
```

⚠️ 정보 참고용 도구이며 투자 자문이 아닙니다. 실시간 알림·자동매매는 이 저장소 범위 밖입니다 (SETUP.md 참고).
