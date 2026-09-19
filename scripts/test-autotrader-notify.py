#!/usr/bin/env python3
"""autotrader 로그인 알림 회귀 — 텔레그램은 가짜 함수로 대체한다. 키·네트워크 없음.

    python scripts/test-autotrader-notify.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import notify                                               # noqa: E402

FAILS = []
COUNT = [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def line(ev, ip="1.2.3.4", ts="2026-09-21T10:00:00+09:00"):
    return f"{ts} {ip} {ev}\n"


def main():
    with tempfile.TemporaryDirectory() as td:
        log, off = Path(td) / "web_login.log", Path(td) / "off.txt"
        sent = []
        clk = Clock()
        n = notify.LoginNotifier(log, off, sent.append, clock=clk, max_per_hour=50)

        log.write_text(line("login-ok", "9.9.9.9"), encoding="utf-8")
        ck("첫 실행은 과거 기록을 재전송하지 않는다(파일 끝부터)", n.poll() == 0 and sent == [] and off.read_text() == str(log.stat().st_size))

        with log.open("a", encoding="utf-8") as f:
            f.write(line("login-ok", "5.5.5.5"))
        ck("새 로그인 성공은 한 통", n.poll() == 1 and "로그인 성공" in sent[-1] and "5.5.5.5" in sent[-1])
        ck("같은 줄을 다시 보내지 않는다(오프셋 저장)", n.poll() == 0)

        sent.clear()
        with log.open("a", encoding="utf-8") as f:
            f.write(line("login-fail", "6.6.6.6") * 4 + line("login-fail", "7.7.7.7") + line("locked", "6.6.6.6"))
        ck("실패 여러 건은 한 통으로 묶는다(IP별 횟수)", n.poll() == 1 and "6회" in sent[0] and "6.6.6.6(5)" in sent[0] and "7.7.7.7(1)" in sent[0])

        sent.clear()
        with log.open("a", encoding="utf-8") as f:
            f.write(line("reauth-ok", "5.5.5.5") + line("logout", "5.5.5.5"))
        ck("재인증 성공은 알리고 로그아웃은 알리지 않는다", n.poll() == 1 and "재인증 성공" in sent[0])

        # 줄이 덜 써진 상태
        sent.clear()
        with log.open("a", encoding="utf-8") as f:
            f.write("2026-09-21T10:00:00+09:00 8.8.8.8 login-o")            # 개행 없음
        ck("아직 다 안 써진 줄은 보내지 않고 기다린다", n.poll() == 0 and sent == [])
        with log.open("a", encoding="utf-8") as f:
            f.write("k\n")
        ck("줄이 완성되면 보낸다", n.poll() == 1 and "8.8.8.8" in sent[0])

        # 시간당 상한 (별도 알림기)
        log3, off3 = Path(td) / "l3.log", Path(td) / "o3.txt"
        log3.write_text("", encoding="utf-8")
        sent3 = []
        clk3 = Clock(100.0)
        n3 = notify.LoginNotifier(log3, off3, sent3.append, clock=clk3, max_per_hour=3)
        n3.poll()
        with log3.open("a", encoding="utf-8") as f:
            for i in range(6):
                f.write(line("login-ok", f"4.4.4.{i}"))
        n3.poll()
        ck("시간당 상한(3통)을 넘으면 '요약 중' 한 통만 보내고 나머지는 삼킨다",
           len(sent3) == 4 and sum("요약" in m for m in sent3) == 1 and sum("로그인 성공" in m for m in sent3) == 3)
        with log3.open("a", encoding="utf-8") as f:
            f.write(line("login-ok", "3.3.3.3"))
        n3.poll()
        ck("상한 안에서는 '요약 중'을 시간당 한 번만(추가 발송 없음)", len(sent3) == 4)
        clk3.t += 3700
        with log3.open("a", encoding="utf-8") as f:
            f.write(line("login-ok", "2.2.2.2"))
        n3.poll()
        ck("한 시간이 지나면 다시 정상 발송", len(sent3) == 5 and "2.2.2.2" in sent3[-1])

        # 로그 교체
        sent.clear()
        clk.t = 10000.0
        log.write_text(line("login-ok", "2.2.2.2"), encoding="utf-8")       # 크기가 오프셋보다 작다 -> 처음부터
        ck("로그가 잘리면 처음부터 다시 읽는다", n.poll() == 1 and "2.2.2.2" in sent[0])

        # 전송 실패 -> 오프셋 유지 -> 재시도
        boom = {"n": 0}

        def flaky(msg):
            boom["n"] += 1
            if boom["n"] == 1:
                raise RuntimeError("telegram 전송 실패(URLError)")
        log2, off2 = Path(td) / "l2.log", Path(td) / "o2.txt"
        log2.write_text("", encoding="utf-8")
        n2 = notify.LoginNotifier(log2, off2, flaky, clock=Clock(5.0))
        n2.poll()
        with log2.open("a", encoding="utf-8") as f:
            f.write(line("login-ok", "1.1.1.1"))
        try:
            n2.poll()
            failed = False
        except RuntimeError:
            failed = True
        ck("전송이 실패하면 예외를 올리고 오프셋을 올리지 않는다", failed and int(off2.read_text()) < log2.stat().st_size)
        ck("다음 주기에 다시 보낸다(유실 없음)", n2.poll() == 1 and int(off2.read_text()) == log2.stat().st_size)

    # 메시지 내용
    msgs = notify.build_messages([line("login-ok", "1.1.1.1")])
    ck("성공 메시지에 대응 방법(재설정 안내)이 들어간다", "web-setup --reset" in msgs[0])
    ck("모르는 형식의 줄은 무시한다", notify.build_messages(["garbage", "a b", ""]) == [])

    # 토큰이 메시지·예외·소스에 새지 않는다
    tok = "123456:SECRET-TOKEN-VALUE"
    try:
        notify.send_telegram(tok, "1", "x", timeout=0.01)     # 도달할 수 없는 곳/타임아웃 -> 실패
    except RuntimeError as e:
        ck("전송 예외 문구에 토큰이 들어 있지 않다", tok not in str(e) and "SECRET" not in str(e))
    except Exception as e:                                     # noqa: BLE001
        ck("전송 예외 문구에 토큰이 들어 있지 않다", tok not in str(e))
    else:
        ck("전송 예외 문구에 토큰이 들어 있지 않다", True)
    src = (ROOT / "autotrader" / "notify.py").read_text(encoding="utf-8")
    ck("알림 소스에 토큰 리터럴이 없다", "123456:" not in src and "bot" + "token=" not in src)

    total = COUNT[0]
    print(f"\ntest-autotrader-notify {total - len(FAILS)}/{total}" + ("" if not FAILS else f"  FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
