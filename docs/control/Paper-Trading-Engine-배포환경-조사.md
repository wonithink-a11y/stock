# Paper Trading Engine — 배포 환경(Oracle VM) 타당성 조사

```
발행   2026-08-21 · Claude
배경   Paper Trading Engine 1~2단계(engine/live/*, 커밋 b23de4d) 완료 후
       3단계(KIS 모의투자 연동) 착수 전 사용자 요청 — "현재 Oracle VM
       (1 OCPU/1GB)이 배포 후보로 되는지 실측만, KIS/주문 코드는 만들지 말 것"
상태   조사만. KIS Broker Adapter·주문 코드 미작성
```

## 측정 방법

VM에 직접 접근할 수 없어(로컬 개발 환경) 실제 VM 측정을 대신할 수 없다.
대신 `engine/live/paperEngine.run_once()`를 **실운영 크론 호출 패턴 그대로**
(캐시 미사용 첫 호출, `A2aProvider.load()`가 전체 이력을 스캔) 서브프로세스로
띄우고 `psutil`로 peak RSS·wall time을 쟀다(`measure_paper_engine_resource.py`,
진단 전용). 로컬 Windows 측정이라 VM(Linux, Python 3.8)과 절대값은 다를 수
있으나, 지배적 비용(A2a gzip 전체 스캔 + pandas 프레임 적재)은 플랫폼과
무관해 상대적 크기 비교엔 유효하다.

## 결과

| 유니버스 | peak RSS | wall time |
|---|---|---|
| 5종목 (현재 `dummy_sma20` 스켈레톤) | **103.4 MB** | 31.0초 |
| 전체 2,558종목 (상한 스트레스) | **5,467.7 MB (≈5.3GB)** | 96.3초 |

기존 분봉 수집기(`deploy/minute-collect.service` 주석)의 실측 피크는
"10종목 116.5MB · Broad 청크 제출 144.8MB", `MemoryMax=320M`으로
캡핑돼 있다 — 5종목 스켈레톤(103.4MB)은 이 기존 워크로드와 **같은
자릿수**다.

## 결론

```
소규모 워치리스트(수 종목~수십 종목)   현재 1GB VM으로 충분해 보인다.
                                     기존 분봉 수집기와 자릿수가 같고,
                                     둘 다 상시 데몬이 아니라 하루 1회
                                     짧게 도는 oneshot이라 겹칠 필요도 없다
                                     (systemd 타이머로 시간을 나누면 됨,
                                     minute-collect.service가 이미 쓰는
                                     Nice=10·MemoryMax 패턴 재사용 가능)

전체 시장(2,558종목) 스캔            1GB VM에 절대 안 맞는다(5.3GB, 약 17배
                                     초과). 별도 서버가 필요하거나,
                                     A2aProvider의 "매일 전체 이력 재스캔"
                                     설계 자체를 바꿔야 한다(아래 참고)
```

**지금 당장은 증설도 별도 서버도 필요 없다** — Paper Trading Engine이
현실적으로 다룰 유니버스는 처음부터 "채택된 전략의 워치리스트"(수~수십
종목)이지 전체 시장이 아니다. 현재 VM 그대로 3단계(KIS 연동)를 진행해도
자원 문제는 없어 보인다.

## 별도로 발견한 것 — 설계 비효율 (판단 아님, 기록만)

`run_once()`가 KIS를 안 붙인 지금도 매 호출마다 `A2aProvider.load(...,
start=calendar.days[0], end=as_of)`로 **전체 이력을 처음부터 다시
스캔**한다. `end=as_of`가 매일 달라지므로 A2aProvider의 parquet 캐시가
날짜 키까지 포함해 매일 캐시 미스가 난다 — 5종목 기준으로도 31초가
매일 든다는 뜻이다. 워치리스트가 작으면(1GB 예산 안에서) 문제는 아니지만,
필요한 건 warmup에 필요한 최근 N거래일뿐이라 `start`를 고정 lookback
윈도우로 좁히면 이 비용을 크게 줄일 수 있다 — 3단계 구현 시 함께 고칠지는
별도 판단.

## 관련

- `measure_paper_engine_resource.py` — 이 조사의 측정 스크립트
- `deploy/minute-collect.service`·`deploy/minute-collect.timer` — 기존
  워크로드 실측치·oneshot+timer 패턴(재사용 대상)
- `research/strategy-lab/engine/live/` — 1~2단계 구현(커밋 `b23de4d`)
