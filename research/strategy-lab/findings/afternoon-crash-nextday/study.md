---
track: kr
factor: afternoon-crash-nextday
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["thr>=3/5/7", "marketCrashDay(kospi<=-1%)", "idioDay", "volHi(rv>=2)", "volLo(rv<1)", "closedAtLow(<=1%)", "offLow(>3%)", "calmOpen(range<=2%)", "wildOpen(range>=4%)"]
reason: "오후 급락(≥3/5/7%) 다음날 반등 전향적 표 - thr=3% 하락 후 marketCrashDay/volLo/calmOpen에서 다음날종가 +1.1~1.6%로 유의(t=+4.8~+11.4)하나 기간·전략 판정은 없는 조사 표"
---
# 오후 급락 -> 다음날 반등? (step 11)

rows=601,359

| 조건 | n | 다음시가 | +10:35까지 | +10:30까지 | 다음날종가 |
|---|---|---:|---:|---:|---:|
| **thr=3%** | 8,520 | +0.60% | +1.08% | +0.98% | +0.62% |
| · marketCrashDay(kospi<=-1%) | 3,385 | | | | +1.13% (t=+8.9) |
| · idioDay(kospi>-1%) | 5,082 | | | | +0.27% (t=+2.1) |
| · volHi(rv>=2) | 3,709 | | | | -0.04% (t=-0.2) |
| · volLo(rv<1) | 3,053 | | | | +1.30% (t=+11.4) |
| · closedAtLow(<=1%) | 3,471 | | | | +0.89% (t=+8.1) |
| · offLow(>3%) | 2,967 | | | | +0.19% (t=+0.9) |
| · calmOpen(range<=2%) | 546 | | | | +1.14% (t=+4.8) |
| · wildOpen(range>=4%) | 6,178 | | | | +0.51% (t=+4.2) |
| **thr=5%** | 2,233 | +0.73% | +1.23% | +1.14% | +0.29% |
| · marketCrashDay(kospi<=-1%) | 751 | | | | +1.67% (t=+4.4) |
| · idioDay(kospi>-1%) | 1,463 | | | | -0.42% (t=-1.7) |
| · volHi(rv>=2) | 1,562 | | | | -0.34% (t=-1.4) |
| · volLo(rv<1) | 331 | | | | +2.63% (t=+4.9) |
| · closedAtLow(<=1%) | 635 | | | | +0.92% (t=+2.6) |
| · offLow(>3%) | 1,120 | | | | -0.16% (t=-0.5) |
| · calmOpen(range<=2%) | 150 | | | | +1.62% (t=+2.9) |
| · wildOpen(range>=4%) | 1,746 | | | | +0.13% (t=+0.5) |
| **thr=7%** | 1,014 | +0.72% | +1.40% | +1.40% | +0.21% |
| · marketCrashDay(kospi<=-1%) | 294 | | | | +2.22% (t=+2.9) |
| · idioDay(kospi>-1%) | 713 | | | | -0.62% (t=-1.6) |
| · volHi(rv>=2) | 839 | | | | +0.00% (t=+0.0) |
| · volLo(rv<1) | 74 | | | | +3.58% (t=+1.8) |
| · closedAtLow(<=1%) | 224 | | | | +0.08% (t=+0.1) |
| · offLow(>3%) | 585 | | | | +0.14% (t=+0.3) |
| · calmOpen(range<=2%) | 69 | | | | +1.61% (t=+1.6) |
| · wildOpen(range>=4%) | 801 | | | | +0.01% (t=+0.0) |