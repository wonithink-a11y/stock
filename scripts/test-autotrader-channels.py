"""텔레그램 채널 소식(autotrader/channels.py + 웹 /channels) 회귀 — 네트워크 없음."""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autotrader import channels, web                                          # noqa: E402
from autotrader import web_auth as A                                          # noqa: E402
from autotrader.config import normalize_config                                # noqa: E402
from autotrader.engine import KST                                             # noqa: E402

COUNT, FAILS = [0], []


def ck(name, cond):
    COUNT[0] += 1
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def page(ch, posts):
    out = []
    for pid, at, inner in posts:
        out.append(f'<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="{ch}/{pid}">'
                   f'<div class="tgme_widget_message_bubble">{inner}'
                   f'<div class="tgme_widget_message_footer"><a class="tgme_widget_message_date" href="https://t.me/{ch}/{pid}"><time datetime="{at}" class="time">11:28</time></a></div></div></div></div>')
    return "<html><body>" + "".join(out) + "</body></html>"


def main():
    html = page("mk_giant", [
        (1, "2026-09-22T02:00:22+00:00", '<div class="tgme_widget_message_text js-message_text" dir="auto"><i class="emoji"><b>✅</b></i> 삼성전기 : +6.0%<br/><br/>현재주가 : 1,514,000원 &amp; <a href="https://x">링크</a></div><a class="tgme_widget_message_link_preview"><div class="x">미리보기 제목</div></a>'),
        (2, "2026-09-22T03:00:00+00:00", '<div class="tgme_widget_message_photo_wrap"></div>'),
    ])
    ps = channels.parse(html)
    ck("글 2건·번호·시각", [p["id"] for p in ps] == ["mk_giant/1", "mk_giant/2"] and ps[0]["at"].startswith("2026-09-22T02"))
    ck("본문: <br> 은 줄바꿈, 태그는 글자만, 엔티티 풀림", ps[0]["text"] == "✅ 삼성전기 : +6.0%\n\n현재주가 : 1,514,000원 & 링크")
    ck("본문 div 밖(링크 미리보기)은 안 섞인다", "미리보기 제목" not in ps[0]["text"])
    ck("사진만 있는 글은 빈 본문", ps[1]["text"] == "" and ps[1]["channel"] == "mk_giant")

    m = channels.merge([{"id": "a/1", "at": "1", "text": "옛"}], [{"id": "a/1", "at": "1", "text": "새"}, {"id": "a/2", "at": "2", "text": "x"}], keep=5)
    ck("합치기: 중복 없이 최신순, 같은 글은 새 것으로", [p["id"] for p in m] == ["a/2", "a/1"] and m[1]["text"] == "새")
    ck("보관 상한", len(channels.merge([], [{"id": f"a/{i}", "at": str(i), "text": ""} for i in range(10)], keep=3)) == 3)

    now = datetime(2026, 9, 22, 21, 0, tzinfo=KST)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "state" / "channels.json"

        def get_ok(url):
            ch = url.rsplit("/", 1)[1]
            if ch == "wcforumxyz":
                raise OSError("timeout")
            return page(ch, [(9, "2026-09-22T05:00:00+00:00", '<div class="tgme_widget_message_text">안녕</div>')])
        ck("한 채널 실패는 기록만, 종료코드 0", channels.fetch_all(p, now, get_ok) == 0)
        d = json.loads(p.read_text(encoding="utf-8"))
        ck("읽은 채널 글 저장·실패 채널 기록", len(d["posts"]) == 2 and "wcforumxyz" in d["errors"])
        ck("형식이 바뀌어 전부 0건이면 종료코드 1(실패 알림)", channels.fetch_all(p, now, lambda u: "<html></html>") == 1)
        ck("실패해도 옛 글은 남는다", len(json.loads(p.read_text(encoding="utf-8"))["posts"]) == 2)

        # ---- 증권사 목표가 기록(tp-history.jsonl)
        NL = chr(10)
        daily = {"id": "mk_giant/9", "channel": "mk_giant", "at": "2026-10-06T23:49:00+00:00", "text": NL.join([
            "신한지주 : 당일 발간리포트 - 2건", "", "Buy : 2건", "목표가 평균 : 136,500원 | 최대 : 139,000원", "", "- 서술 문장은 저장하지 않는다", "",
            "(증권사 : 투자의견 / 목표가)", "NH / Buy(유지) / 139,000원(유지)", "SK / Buy(신규) / 134,000원(신규)"])}
        feat = {"id": "mk_giant/10", "channel": "mk_giant", "at": "2026-10-07T00:15:00+00:00", "text": NL.join([
            "✅️ 제이앤티씨 : +15.2% 상승 중", "", "현재주가 : 26,400원", "", "* 최근 1개월 발간리포트 - 2건", "Buy : 1건 ", "목표가 : 26,000원", "업사이드 : +1.5%"])}
        other = {"id": "wcforumxyz/1", "channel": "wcforumxyz", "at": "2026-10-07T00:15:00+00:00", "text": "NH / Buy(유지) / 1,000원(유지)"}
        rows = channels.extract_tp([daily, feat, other])
        ck("목표가: 증권사 2행 + 특징주 1건, 다른 채널은 무시", [r["kind"] for r in rows] == ["daily", "daily", "month"])
        ck("목표가: 필드(증권사·의견·목표가·변동)", rows[0]["broker"] == "NH" and rows[0]["opinion"] == "Buy" and rows[0]["tp"] == 139000 and rows[1]["tpChg"] == "신규")
        ck("목표가: 특징주 요약(건수·목표가·업사이드·현재가)", rows[2]["n"] == 2 and rows[2]["tp"] == 26000 and rows[2]["upside"] == 1.5 and rows[2]["price"] == 26400)
        ck("목표가: 종목명은 이모지·꼬리 제거, 서술 문장은 저장 안 함", rows[0]["name"] == "신한지주" and rows[2]["name"] == "제이앤티씨" and "서술" not in json.dumps(rows, ensure_ascii=False))
        tpf = Path(td) / "tp.jsonl"
        ck("목표가: 처음엔 3건 추가", channels.append_tp(tpf, [daily, feat]) == 3)
        ck("목표가: 같은 글을 다시 읽어도 중복 없음", channels.append_tp(tpf, [daily, feat]) == 0 and len(tpf.read_text(encoding="utf-8").splitlines()) == 3)

        # ---- 웹: 로그인 뒤에만, 이스케이프, 채널 목록만
        sdir = Path(td) / "state"
        (sdir / "channels.json").write_text(json.dumps({"updatedAt": "2026-09-22T21:00:00+09:00", "errors": {}, "posts": [
            {"id": "mk_giant/5", "channel": "mk_giant", "at": "2026-09-22T12:00:00+00:00", "text": "<script>alert(1)</script>\n둘째 줄"},
            {"id": "mkglobalinvest/7", "channel": "mkglobalinvest", "at": "2026-09-22T11:00:00+00:00", "text": "월가 " + "가" * 400}]}), encoding="utf-8")
        store = A.AuthStore(sdir / "web_auth.json")
        store.save({"password": A.hash_password("pw-long-enough-1"), "totpSecret": A.new_totp_secret()})
        app = web.WebApp(normalize_config({"strategy": "target_weights", "mode": "paper", "markets": ["KR"], "symbol_allowlist": ["005930"], "state_dir": str(sdir)}), sdir, store,
                         A.Sessions(), A.Lockout(), secure_cookie=False)
        ck("로그인 없으면 404", app.handle("GET", "/channels", {}, b"", "1.1.1.1")[0] == 404)
        tok = app.sessions.create()
        h = {"Cookie": f"at_sess={tok}"}
        st, _, b = app.handle("GET", "/channels", h, b"", "1.1.1.1")
        b = b.decode()
        ck("본문은 이스케이프(XSS 없음)·줄바꿈 표시", st == 200 and "<script>alert" not in b and "&lt;script&gt;" in b and "<br>둘째 줄" in b)
        ck("원문은 t.me 링크, 시각은 KST", 'href="https://t.me/mk_giant/5"' in b and "09-22 21:00" in b)
        ck("긴 글은 더 보기로 접힌다", "<details>" in b)
        b2 = app.handle("GET", "/channels?c=mkglobalinvest", h, b"", "1.1.1.1")[2].decode()
        ck("채널 거르기", "월가" in b2 and "&lt;script&gt;" not in b2)
        b3 = app.handle("GET", "/channels?c=../../etc", h, b"", "1.1.1.1")[2].decode()
        ck("모르는 채널 값은 전체로", "&lt;script&gt;" in b3 and "월가" in b3)
        ck("요약 화면에 채널 소식 링크", "/channels" in app.handle("GET", "/", h, b"", "1.1.1.1")[2].decode())

    print(f"\ntest-autotrader-channels {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
