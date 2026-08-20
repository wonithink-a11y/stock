# other-categories 방향모순 집계 (capitalReductionFree · bonusIssue · capitalReductionPaid · capitalReductionUnknown)

집계 기준:
- capitalReductionFree(무상감자) — splitLike, multiplier < 1 기대 → multiplier >= 1이면 방향모순 의심
- bonusIssue(무상증자) — splitLike, multiplier > 1 기대 → multiplier <= 1이면 방향모순 의심
- capitalReductionPaid(유상감자) · capitalReductionUnknown — multiplier 수치가 없으면 "필드 없음" 처리

## 카테고리별 총 건수 / 방향모순 의심 건수

| category | 총 건수 | 방향모순 의심 건수 | 비고 |
|---|---|---|---|
| capitalReductionFree | 382 | 1 (multiplier >= 1) | multiplier 범위 0.0 ~ 1.0 |
| bonusIssue | 715 | 0 (multiplier <= 1) | multiplier 범위 1.02 ~ 15.0 |
| capitalReductionPaid | 18 | 0 | multiplier 필드 있으나 전부 null — 실수치 0건 |
| capitalReductionUnknown | 267 | 0 | multiplier 필드 있으나 전부 null — 실수치 0건 |

## 방향모순 의심 표본 (처음 10건)

### capitalReductionFree — multiplier >= 1 (1건)

| ticker | disclosureDate | multiplier |
|---|---|---|
| 035430 | 20191002 | 1.0 |

### bonusIssue — multiplier <= 1 (0건)

표본 없음.

### capitalReductionPaid — multiplier 실수치 없음 (18건)

multiplier 필드는 JSON에 존재하나 모든 건에서 null. 방향 판단 가능한 수치 없음.

### capitalReductionUnknown — multiplier 실수치 없음 (267건)

multiplier 필드는 JSON에 존재하나 모든 건에서 null. 방향 판단 가능한 수치 없음.