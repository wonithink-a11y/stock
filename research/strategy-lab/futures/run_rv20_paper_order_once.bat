@echo off
rem RV20 sizing 규칙(동결, futures-rv20-sizing-rule-freeze-2026-09-13.md, Rule B)
rem 첫 실주문(모의) 1회용 실행기 - Windows 작업 스케줄러가 2026-09-14 09:10에 호출한다.
rem 사람이 없어도 도는 유일한 자동 실행이라, 실행 후 반드시 로그를 확인한다.
cd /d C:\Users\User\projects\stock
set PYTHONIOENCODING=utf-8
if not exist research\strategy-lab\data\paper-futures mkdir research\strategy-lab\data\paper-futures

echo ===== %date% %time% - 캐시 갱신 ===== >> research\strategy-lab\data\paper-futures\rv20_paper_order.log
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" research\strategy-lab\collect_kospi200_daily_krx.py >> research\strategy-lab\data\paper-futures\rv20_paper_order.log 2>&1

echo ===== %date% %time% - 주문 실행(--confirm-live) ===== >> research\strategy-lab\data\paper-futures\rv20_paper_order.log
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" research\strategy-lab\futures\rv20_paper_order.py --capital 250000000 --confirm-live >> research\strategy-lab\data\paper-futures\rv20_paper_order.log 2>&1

echo ===== %date% %time% - 완료 ===== >> research\strategy-lab\data\paper-futures\rv20_paper_order.log
