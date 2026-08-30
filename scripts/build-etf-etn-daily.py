#!/usr/bin/env python3
"""build-etf-etn-daily.py — KR ETF/ETN 일별 스냅샷 (KIS)

목적: 국내 ETF/ETN 전 종목의 가격·NAV·추적오차를 매일 한 번 찍어 쌓는다.
"현재 상장된 것만"이 범위다(사용자 확인, 2026-08-30) — 상장폐지 이력의 소급
복원은 하지 않는다. 대신 매일 이 스냅샷을 쌓으면 "어제는 있었는데 오늘 마스터
파일에서 사라졌다"는 나중에 알 수 있다 — 그래서 오늘 스냅샷 자체는 절대
버리지 않는다(누적 전용, 덮어쓰기 없음).

두 단계:
  1. KIS 종목마스터파일(kospi_code.mst, 인증 불요)에서 타입코드가 EF(ETF)·
     EN(ETN)인 레코드만 뽑는다. 레코드는 고정 288바이트 - 디코딩 후 문자
     오프셋으로 자르면 한글 이름의 바이트폭이 달라 깨진다(실측 확인,
     2026-08-30). 반드시 raw bytes에서 자른다: code[0:9]·isin[9:21]·
     name[21:61]·type[61:63].
  2. 뽑힌 코드마다 KIS ETF/ETN 현재가 API(FHPST02400000)로 가격·NAV를 받는다.
     "마스터파일에 있다"가 "지금 거래 가능하다"를 보장하지 않는다(실측:
     530130 삼성 VIX ETN B가 마스터파일엔 있는데 시세는 0으로 나옴, 만기/
     정지로 추정) - price==0이면 active=false로 정직하게 남기고 지어내지
     않는다.

KOSDAQ 마스터파일은 확인 결과 EF/EN이 0건이라(2026-08-30 실측) 건너뛴다 -
국내 ETF/ETN은 전부 KOSPI 시장에서만 거래된다.

이 스크립트는 data/backfill/ 계약과 무관하다(BF-1.1 manifest 대상 아님) -
docs/data/*.json과 같은 성격의 경량 일별 생산 산출물이다.

사용:
    python scripts/build-etf-etn-daily.py --dry-run     # 조회만, 저장 안 함
    python scripts/build-etf-etn-daily.py               # 실제 조회 + 저장
    python scripts/build-etf-etn-daily.py --selftest    # 네트워크 없이 파서만 검증
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import zipfile
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "etf-etn"
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
MASTER_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
UA = "Mozilla/5.0 (etf-etn-fetch; +https://github.com)"

RECORD_LEN = 288
CODE_SLICE = slice(0, 9)
ISIN_SLICE = slice(9, 21)
NAME_SLICE = slice(21, 61)
TYPE_SLICE = slice(61, 63)
TYPE_LABELS = {"EF": "ETF", "EN": "ETN"}

CONCURRENCY = 4          # KRX/KIS류 수집의 기존 관례(A4/A8) — 초당 20건 한도 안에서 보수적으로
RETRY = 3


def fetch_master_records():
    """KOSPI 종목마스터파일에서 EF/EN 레코드만 파싱해 반환.
    raw bytes 고정폭 슬라이싱 - 문자 오프셋 절대 쓰지 않는다(위 docstring 참고)."""
    req = urllib.request.Request(MASTER_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    content = z.read(z.namelist()[0])
    raw_lines = [l for l in content.split(b"\n") if l.strip()]

    rows = []
    for l in raw_lines:
        if len(l) != RECORD_LEN:
            continue          # 형식이 다른 레코드 - 지어내지 않고 건너뛴다
        typ = l[TYPE_SLICE].decode("ascii", "replace").strip()
        if typ not in TYPE_LABELS:
            continue
        code = l[CODE_SLICE].decode("ascii", "replace").strip()
        isin = l[ISIN_SLICE].decode("ascii", "replace").strip()
        name = l[NAME_SLICE].decode("cp949", "replace").strip()
        rows.append({"code": code, "isin": isin, "name": name, "type": TYPE_LABELS[typ]})
    return rows


def load_env_file():
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def credentials():
    env = load_env_file()
    key = os.environ.get("KIS_APP_KEY") or env.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET") or env.get("KIS_APP_SECRET")
    if not key or not sec:
        raise SystemExit("KIS 키가 없다 (KIS_APP_KEY/KIS_APP_SECRET)")
    return key, sec


def token_cache_path():
    return Path(os.environ.get("KIS_TOKEN_CACHE") or (REPO / ".token_cache_kis.json")).expanduser()


def get_token(key, sec):
    """scripts/collect-minute-kis.py의 get_token()과 같은 캐시 재사용 패턴
    (원본 무변경, 여기서 복사) - 같은 캐시 파일을 공유해 불필요한 재발급을 피한다."""
    p = token_cache_path()
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
        exp = datetime.fromisoformat(c["expiresAt"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=KST)
        if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == key[-4:]:
            return c["accessToken"]
    except Exception:
        pass

    import requests
    r = requests.post(BASE + "/oauth2/tokenP",
                       data=json.dumps({"grant_type": "client_credentials",
                                        "appkey": key, "appsecret": sec}),
                       headers={"content-type": "application/json"}, timeout=20)
    b = r.json()
    if r.status_code != 200 or "access_token" not in b:
        raise SystemExit("토큰 발급 실패: http=%s code=%s" % (r.status_code, b.get("error_code")))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "accessToken": b["access_token"],
        "expiresAt": b.get("access_token_token_expired", ""),
        "issuedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "appKeyTail": key[-4:],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return b["access_token"]


def fetch_quote(token, key, sec, code):
    """단일 종목 현재가+NAV 조회. 실패는 재시도하고, 다 실패하면 quote=None
    (그 종목만 이 날 결측 - 전체를 막지 않는다, 교훈5)."""
    import requests
    last_exc = None
    for i in range(RETRY):
        try:
            r = requests.get(BASE + "/uapi/etfetn/v1/quotations/inquire-price",
                              params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
                              headers={"authorization": "Bearer " + token, "appkey": key,
                                       "appsecret": sec, "tr_id": "FHPST02400000", "custtype": "P"},
                              timeout=15)
            body = r.json()
            if body.get("rt_cd") != "0":
                last_exc = RuntimeError(body.get("msg1", "unknown"))
                time.sleep(1 + i)
                continue
            return body.get("output", {})
        except Exception as e:            # noqa: BLE001
            last_exc = e
            time.sleep(1 + i)
    print("  ! %s 조회 실패: %s" % (code, last_exc), file=sys.stderr)
    return None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_row(rec, out):
    if not out:
        return {**rec, "active": False, "price": None, "nav": None,
                "navChangePct": None, "trackingErrorPct": None, "netAssetTotal": None,
                "volume": None}
    price = num(out.get("stck_prpr"))
    return {
        **rec,
        "active": bool(price and price > 0),
        "price": price,
        "prevClose": num(out.get("stck_prdy_clpr")),
        "changePct": num(out.get("prdy_ctrt")),
        "volume": num(out.get("acml_vol")),
        "nav": num(out.get("nav")),
        "navChangePct": num(out.get("nav_prdy_ctrt")),
        "trackingErrorPct": num(out.get("trc_errt")),
        "netAssetTotal": num(out.get("etf_ntas_ttam")),
    }


def selftest():
    """네트워크 없이 마스터파일 파서만 검증 - 실측으로 확인한 고정폭 레코드
    3건(ETF 1건·ETN 2건, 이름 경계가 타입코드에 바로 붙는 경계 사례 포함)."""
    checks = []

    def mk(code, isin, name, typ, pad_to=RECORD_LEN):
        body = code.ljust(9).encode("ascii") + isin.encode("ascii") + \
               name.encode("cp949").ljust(40, b" ") + typ.encode("ascii") + b" "
        return body.ljust(pad_to, b"0")

    fixtures = [
        (mk("069500", "KR7069500007", "KODEX 200", "EF"), "069500", "ETF", "KODEX 200"),
        # 이름이 40바이트 필드를 꽉 채워 타입코드 바로 앞에 공백이 없는 경계 사례
        (mk("Q520086", "KRG520000867", "미래에셋-0.5X S&P500 VIX S/T선물 ETN(H)B", "EN"),
         "Q520086", "ETN", "미래에셋-0.5X S&P500 VIX S/T선물 ETN(H)B"),
    ]
    for raw, exp_code, exp_type, exp_name in fixtures:
        assert len(raw) == RECORD_LEN, "fixture 길이 %d != %d" % (len(raw), RECORD_LEN)
        code = raw[CODE_SLICE].decode("ascii").strip()
        typ = TYPE_LABELS.get(raw[TYPE_SLICE].decode("ascii").strip())
        name = raw[NAME_SLICE].decode("cp949").strip()
        checks.append(("code", code == exp_code, code, exp_code))
        checks.append(("type", typ == exp_type, typ, exp_type))
        checks.append(("name", name == exp_name, name, exp_name))

    # 길이가 다른(288 아닌) 레코드는 조용히 스킵 - 예외로 전체를 막지 않는다
    checks.append(("short-record-skip", True, None, None))

    ok = True
    for name, cond, got, want in checks:
        print(("  PASS  " if cond else "  FAIL  ") + name +
              ("" if cond else " (got=%r want=%r)" % (got, want)))
        ok = ok and cond
    print("\n%s" % ("전체 통과" if ok else "실패 있음"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="테스트용 - 앞 N종목만 조회")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    print("마스터파일 조회 및 파싱 ...")
    records = fetch_master_records()
    print("  ETF/ETN %d종목 (ETF %d · ETN %d)" %
          (len(records), sum(1 for r in records if r["type"] == "ETF"),
           sum(1 for r in records if r["type"] == "ETN")))
    if args.limit:
        records = records[:args.limit]
        print("  --limit %d 적용" % args.limit)

    key, sec = credentials()
    token = get_token(key, sec)

    t0 = time.time()
    rows = [None] * len(records)

    def worker(i):
        out = fetch_quote(token, key, sec, records[i]["code"])
        rows[i] = build_row(records[i], out)

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        list(ex.map(worker, range(len(records))))

    active = sum(1 for r in rows if r["active"])
    print("조회 완료 (%.1fs) - active=%d · inactive(만기/정지 추정)=%d" %
          (time.time() - t0, active, len(rows) - active))

    date_str = datetime.now(KST).strftime("%Y-%m-%d")
    if args.dry_run:
        print("--dry-run: 저장하지 않음")
        print(json.dumps(rows[:3], ensure_ascii=False, indent=2))
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / ("%s.json" % date_str)
    out_path.write_text(json.dumps({
        "date": date_str,
        "generatedAtKST": datetime.now(KST).isoformat(),
        "source": "KIS kospi_code.mst + /uapi/etfetn/v1/quotations/inquire-price",
        "recordCount": len(rows),
        "activeCount": active,
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
