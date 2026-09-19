"""로그인 알림 — 웹 화면의 로그인 기록(state/web_login.log)을 읽어 텔레그램으로 보낸다.

★ **웹 프로세스와 별개의 프로세스**다. 텔레그램 토큰은 이 프로세스만 가진다(웹 화면이 뚫려도 토큰은 안전하다).
   웹 프로세스는 로그 파일에 한 줄씩 남길 뿐 아무것도 보내지 않는다.
★ 알림이 폭주하지 않게: 실패는 한 번의 확인(poll)마다 묶어서 한 통, 시간당 상한을 넘으면 요약 한 통만 보내고 나머지는 삼킨다
   (원본은 로그에 남아 있다). 봇의 스캔이 텔레그램을 도배하지 못하게 하는 장치다.
★ 처음 시작할 때는 과거 기록을 재전송하지 않는다(파일 끝부터 본다).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Callable, List, Optional

OK_EVENTS = {"login-ok": "✅ 로그인 성공", "reauth-ok": "✅ 재인증 성공"}
FAIL_EVENTS = {"login-fail": "로그인 실패", "reauth-fail": "재인증 실패", "csrf-fail": "요청 검증 실패", "locked": "잠금 상태에서 시도"}


def send_telegram(token: str, chat_id: str, text: str, timeout: float = 10.0) -> None:
    """텔레그램 sendMessage. 실패해도 예외 문구에 토큰(URL)이 새지 않게 형식만 다시 던진다."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                raise RuntimeError(f"telegram HTTP {r.status}")
    except Exception as e:                       # noqa: BLE001 — URL(토큰)이 든 원문 메시지를 버린다
        raise RuntimeError(f"telegram 전송 실패({type(e).__name__})") from None


def parse_line(line: str):
    """'2026-09-21T10:00:00+09:00 1.2.3.4 login-ok' -> (ts, ip, event). 형식이 다르면 None."""
    parts = line.strip().split(" ")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def build_messages(lines: List[str]) -> List[str]:
    msgs: List[str] = []
    fails: Counter = Counter()
    fail_kinds: Counter = Counter()
    for ln in lines:
        p = parse_line(ln)
        if not p:
            continue
        ts, ip, ev = p
        when = ts[5:16].replace("T", " ")
        if ev in OK_EVENTS:
            msgs.append(f"{OK_EVENTS[ev]}\nautotrader · {when} · IP {ip}\n본인이 아니면 즉시 비밀번호·인증앱 재설정(web-setup --reset)")
        elif ev in FAIL_EVENTS:
            fails[ip] += 1
            fail_kinds[FAIL_EVENTS[ev]] += 1
    if fails:
        ips = ", ".join(f"{ip}({n})" for ip, n in fails.most_common(5))
        kinds = ", ".join(f"{k} {n}" for k, n in fail_kinds.most_common())
        msgs.append(f"⚠️ autotrader 로그인 시도 실패 {sum(fails.values())}회\n{kinds}\nIP: {ips}")
    return msgs


class LoginNotifier:
    def __init__(self, log_path: Path, offset_path: Path, send: Callable[[str], None],
                 clock: Callable[[], float] = time.time, max_per_hour: int = 12):
        self.log, self.offset_path, self.send, self.clock = Path(log_path), Path(offset_path), send, clock
        self.max_per_hour = max_per_hour
        self._sent: List[float] = []
        self._capped_at: Optional[float] = None

    def _offset(self) -> Optional[int]:
        try:
            return int(self.offset_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _save(self, n: int) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self.offset_path.write_text(str(n), encoding="utf-8")

    def _read_new(self) -> (List[str], int):
        size = self.log.stat().st_size if self.log.exists() else 0
        off = self._offset()
        if off is None:                                   # 첫 실행: 과거는 재전송하지 않는다
            self._save(size)
            return [], size
        if size < off:                                    # 로그가 잘렸다/교체됐다
            off = 0
        if size == off:
            return [], off
        with self.log.open("rb") as f:
            f.seek(off)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end < 0:                                       # 아직 줄이 덜 써졌다
            return [], off
        text = chunk[:end + 1].decode("utf-8", "replace")
        return text.splitlines(), off + end + 1

    def poll(self) -> int:
        """새 로그 줄을 읽어 알림을 보낸다. 보낸 통 수를 돌려준다. 전송에 실패하면 오프셋을 올리지 않아 다음에 다시 시도한다."""
        lines, new_off = self._read_new()
        if not lines:
            return 0
        now = self.clock()
        self._sent = [t for t in self._sent if now - t < 3600]
        sent = 0
        for m in build_messages(lines):
            if len(self._sent) >= self.max_per_hour:
                if self._capped_at is None or now - self._capped_at >= 3600:   # 시간당 한 번만 "억제 중"을 알린다
                    self.send("🔕 autotrader 알림이 너무 많아 잠시 요약합니다(원본은 서버 로그에 있습니다).")
                    self._capped_at = now
                    sent += 1
                break
            self.send(m)
            self._sent.append(now)
            sent += 1
        self._save(new_off)
        return sent


def run_loop(notifier: LoginNotifier, interval: float = 5.0, sleep: Callable[[float], None] = time.sleep) -> None:
    print("autotrader login notifier 시작", flush=True)
    while True:
        try:
            notifier.poll()
        except Exception as e:                            # noqa: BLE001 — 전송 실패 등은 다음 주기에 재시도
            print(f"알림 처리 오류: {type(e).__name__}", file=sys.stderr, flush=True)
        sleep(interval)
