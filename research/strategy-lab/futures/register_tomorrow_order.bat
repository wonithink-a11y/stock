@echo off
rem 더블클릭하면 내일(2026-09-14) 09:10에 RV20 선물 모의주문을 1회 자동 실행하도록
rem Windows 작업 스케줄러에 등록한다. 이 파일을 실행하는 건 사용자다 - Claude가
rem 이 파일을 대신 실행하지 않는다(등록 자체는 사람이 눌러야 하는 행위).
rem
rem 등록만 한다 - 지금 당장 주문을 내지 않는다. 실제 주문은 내일 09:10에
rem run_rv20_paper_order_once.bat 가 혼자 실행되면서 나간다.
rem
rem 필요조건: 내일 09:10에 이 컴퓨터가 켜져 있고 로그인돼 있어야 한다(잠자기/
rem 종료 상태면 안 돈다).

schtasks /create /tn "RV20FuturesPaperOrder_20260914" ^
  /tr "C:\Users\User\projects\stock\research\strategy-lab\futures\run_rv20_paper_order_once.bat" ^
  /sc once /sd 2026/09/14 /st 09:10 /rl highest /f

echo.
echo 등록 완료. 확인하려면: schtasks /query /tn "RV20FuturesPaperOrder_20260914" /v /fo list
echo 취소하려면:            schtasks /delete /tn "RV20FuturesPaperOrder_20260914" /f
pause
