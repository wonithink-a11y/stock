"""설정 로드·검증과 모드 게이트.

★ 실계좌 모드는 여러 겹의 스위치 뒤에 잠겨 있다(`gate_problems`). 하나라도 빠지면 실행을 거부한다 —
   조용히 모의나 dry-run 으로 강등하지 않는다(강등하면 사용자가 "돌고 있다"고 착각한다).
★ 키는 이 파일 어디에도 없다. 환경변수 또는 저장소 루트 `.env`(gitignore)에서만 읽는다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_ACK = "I-ACCEPT-REAL-TRADES"          # 환경변수 AUTOTRADER_ALLOW_LIVE 가 정확히 이 값이어야 실계좌 주문이 열린다

PAPER_KEYS = ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET", "KIS_VTS_ACCOUNT_NO")
LIVE_KEYS = ("KIS_LIVE_APP_KEY", "KIS_LIVE_APP_SECRET", "KIS_LIVE_ACCOUNT_NO")   # 시세용 KIS_APP_KEY 와 이름을 분리했다
# TELEGRAM_TRADE_CHAT_ID 가 여기 없어서 09-22~09-28 매매·보안 알림이 전부 1:1 콘텐츠 방으로 갔다(trade_chat 대체 경로)
ENV_KEYS = PAPER_KEYS + LIVE_KEYS + ("AUTOTRADER_ALLOW_LIVE", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                                     "TELEGRAM_TRADE_CHAT_ID")
# 키 묶음 교체: 설정 "key_prefix": "KIS_VTS2" → KIS_VTS2_APP_KEY / _APP_SECRET / _ACCOUNT_NO 를 쓴다.
# 접두사 뒤에 한 마디 이상을 강제한다 — 시세용 KIS_APP_KEY(접두사 "KIS")는 고를 수 없다.
_PREFIX = re.compile(r"^KIS_[A-Z0-9]+(_[A-Z0-9]+)*$")
_KEYSET_ENV = re.compile(r"^KIS_[A-Z0-9_]+_(APP_KEY|APP_SECRET|ACCOUNT_NO)$")
# 업비트(broker "upbit"): "key_prefix": "UPBIT_TRADE" → UPBIT_TRADE_ACCESS_KEY / UPBIT_TRADE_SECRET_KEY.
# 접두사 뒤 한 마디를 강제한다 — 잔고 조회용 UPBIT_ACCESS_KEY(crypto-real-holdings)는 고를 수 없다(주문 키와 분리).
_UPBIT_PREFIX = re.compile(r"^UPBIT_[A-Z0-9]+(_[A-Z0-9]+)*$")
_UPBIT_KEYSET_ENV = re.compile(r"^UPBIT_[A-Z0-9_]+_(ACCESS_KEY|SECRET_KEY)$")
# 빗썸(broker "bithumb"): "key_prefix": "BITHUMB_TRADE" → BITHUMB_TRADE_ACCESS_KEY / BITHUMB_TRADE_SECRET_KEY (조회용 BITHUMB_ACCESS_KEY 는 못 고른다).
_BITHUMB_PREFIX = re.compile(r"^BITHUMB_[A-Z0-9]+(_[A-Z0-9]+)*$")
_BITHUMB_KEYSET_ENV = re.compile(r"^BITHUMB_[A-Z0-9_]+_(ACCESS_KEY|SECRET_KEY)$")
BROKERS = ("kis", "upbit", "bithumb")
CRYPTO_BROKERS = {"upbit": "UPBIT", "bithumb": "BITHUMB"}        # broker → 시장 이름


def crypto_market(cfg: dict) -> Optional[str]:
    """프로필의 거래소 시장 이름(UPBIT|BITHUMB), 크립토가 아니면 None."""
    return CRYPTO_BROKERS.get(cfg.get("broker"))
_PROFILE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_HM = r"([01]\d|2[0-3]):[0-5]\d"
_RUN_AT = re.compile(rf"{_HM}(-{_HM}/([5-9]|[1-5]\d|60))?")       # "09:10" 또는 "09:05-15:15/5"(5~60분 간격)
AUTO_MODES = ("off", "dry", "execute")
RUN_GRACE_MIN = 20          # 예약 시각에서 이만큼 지나면 그 회차는 건너뛴다(몇 시간 늦게 몰아서 주문하지 않게)

# 보수적 기본값 — 사용자가 설정에서 명시적으로 올려야 커진다. 통화는 시장 기준(KR=원, US=달러).
RISK_DEFAULTS = {
    "KR": {"max_order_value": 300_000, "max_daily_value": 1_000_000, "max_orders_per_run": 5,
           "price_band_pct": 5.0, "max_position_value": 1_000_000, "allow_sell": True},
    "US": {"max_order_value": 300, "max_daily_value": 1_000, "max_orders_per_run": 5,
           "price_band_pct": 5.0, "max_position_value": 1_000, "allow_sell": True},
    # 업비트 원화 마켓. max_position_value 는 그 코인의 **계좌 전체** 보유 평가금액(수동 보유 포함)에 걸린다.
    "UPBIT": {"max_order_value": 100_000, "max_daily_value": 300_000, "max_orders_per_run": 1,
              "price_band_pct": 5.0, "max_position_value": 150_000, "allow_sell": True, "min_order_value": 5_000},
}
RISK_DEFAULTS["BITHUMB"] = dict(RISK_DEFAULTS["UPBIT"])           # 빗썸 원화 마켓도 같은 모양(최소 주문 5,000원)


class ConfigError(ValueError):
    pass


class GateError(RuntimeError):
    """실행 조건이 안 맞는다 — 사유 목록을 들고 있다."""

    def __init__(self, problems: List[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _read_env_file(p: Path, env: Dict[str, str]) -> None:
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        k = k.strip()
        if k in ENV_KEYS or _KEYSET_ENV.match(k) or _UPBIT_KEYSET_ENV.match(k) or _BITHUMB_KEYSET_ENV.match(k):
            env[k] = v.strip().strip('"').strip("'")


def load_env(repo_root: Path = REPO_ROOT, environ: Optional[dict] = None) -> Dict[str, str]:
    """`.env` 와 환경변수에서 우리가 쓰는 키만 읽는다(환경변수가 이긴다). 다른 값은 읽지도 않는다.

    키 파일이 저장소 밖에 있으면(VM: ~/collector-venv/.env) 환경변수 `AUTOTRADER_ENV_FILE` 로 위치를 알려 준다.
    (systemd 유닛은 EnvironmentFile 로 같은 효과를 낸다 — 이 옵션은 손으로 시험할 때를 위한 것이다.)
    """
    src = os.environ if environ is None else environ
    env: Dict[str, str] = {}
    _read_env_file(repo_root / ".env", env)
    if src.get("AUTOTRADER_ENV_FILE"):
        _read_env_file(Path(src["AUTOTRADER_ENV_FILE"]).expanduser(), env)
    for k, v in src.items():
        if v and (k in ENV_KEYS or _KEYSET_ENV.match(k) or _UPBIT_KEYSET_ENV.match(k) or _BITHUMB_KEYSET_ENV.match(k)):
            env[k] = v
    return env


def key_names(cfg: dict) -> tuple:
    """이 설정이 쓰는 키 환경변수 이름 3개(앱키·시크릿·계좌). 기본은 모드별 KIS_VTS_* / KIS_LIVE_*."""
    pre = cfg.get("key_prefix")
    if cfg.get("broker") in CRYPTO_BROKERS:
        return (f"{pre}_ACCESS_KEY", f"{pre}_SECRET_KEY")
    if not pre:
        return PAPER_KEYS if cfg.get("mode") == "paper" else LIVE_KEYS
    return (f"{pre}_APP_KEY", f"{pre}_APP_SECRET", f"{pre}_ACCOUNT_NO")


def load_config(path) -> dict:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"설정 파일이 없다: {p} (config.example.json 을 복사해서 만든다)")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    return normalize_config(cfg)


def normalize_config(cfg: dict) -> dict:
    """기본값을 채우고 형식을 검증한다. 사용자 값이 기본값을 덮는다."""
    errs = validate_config(cfg)
    if errs:
        raise ConfigError("설정 오류: " + " / ".join(errs))
    out = dict(cfg)
    out.setdefault("broker", "kis")
    out.setdefault("params", {})
    out.setdefault("symbol_allowlist", [])
    out.setdefault("web", {})
    out.setdefault("live", {})
    out["live"] = {"enabled": False, "tr_ids_reviewed": False, **out["live"]}
    out.setdefault("state_dir", "autotrader/state")
    risk = {}
    for m in out["markets"]:
        risk[m] = {**RISK_DEFAULTS[m], **(out.get("risk", {}).get(m, {}))}
    out["risk"] = risk
    return out


def validate_config(cfg: dict) -> List[str]:
    errs = []
    if not isinstance(cfg, dict):
        return ["설정이 객체가 아니다"]
    if not isinstance(cfg.get("strategy"), str) or not cfg["strategy"]:
        errs.append("strategy(전략 이름)가 필요하다")
    if cfg.get("mode") not in ("paper", "live"):
        errs.append("mode 는 paper|live")
    mk = cfg.get("markets")
    br = cfg.get("broker", "kis")
    if br not in BROKERS:
        errs.append("broker 는 kis|upbit|bithumb")
    if br == "upbit":
        if mk != ["UPBIT"]:
            errs.append("broker upbit 는 markets [\"UPBIT\"] 만")
        if cfg.get("mode") != "live":
            errs.append("broker upbit 는 mode live 만(업비트에는 모의투자가 없다 — 주문 없이 보려면 dry-run)")
    elif br == "bithumb":
        if mk != ["BITHUMB"]:
            errs.append("broker bithumb 는 markets [\"BITHUMB\"] 만")
        if cfg.get("mode") != "live":
            errs.append("broker bithumb 는 mode live 만(빗썸에는 모의투자가 없다 — 주문 없이 보려면 dry-run)")
    elif not isinstance(mk, list) or not mk or any(m not in ("KR", "US") for m in mk):
        errs.append("markets 는 [\"KR\"] 또는 [\"US\"] 또는 둘 다")
    al = cfg.get("symbol_allowlist", [])
    if not isinstance(al, list) or any(not isinstance(s, str) for s in al):
        errs.append("symbol_allowlist 는 종목코드 문자열 목록")
    pre = cfg.get("key_prefix")
    if br == "upbit":
        if not (isinstance(pre, str) and _UPBIT_PREFIX.match(pre)):
            errs.append("broker upbit 는 key_prefix 가 필요하다 — UPBIT_ 로 시작하는 대문자 이름(예: UPBIT_TRADE). 조회용 UPBIT 키는 쓸 수 없다")
    elif br == "bithumb":
        if not (isinstance(pre, str) and _BITHUMB_PREFIX.match(pre)):
            errs.append("broker bithumb 는 key_prefix 가 필요하다 — BITHUMB_ 로 시작하는 대문자 이름(예: BITHUMB_TRADE). 조회용 BITHUMB 키는 쓸 수 없다")
    elif pre is not None and not (isinstance(pre, str) and _PREFIX.match(pre)):
        errs.append("key_prefix 는 KIS_ 로 시작하는 대문자 이름(예: KIS_VTS2). 시세용 KIS 키는 쓸 수 없다")
    if cfg.get("auto", "off") not in AUTO_MODES:
        errs.append("auto 는 off|dry|execute")
    ra = cfg.get("run_at", [])
    if not isinstance(ra, list) or any(not (isinstance(t, str) and _RUN_AT.fullmatch(t)) for t in ra):
        errs.append("run_at 은 \"HH:MM\" 또는 \"HH:MM-HH:MM/분\"(KST) 목록")
    if not isinstance(cfg.get("web_live_allowed", False), bool):
        errs.append("web_live_allowed 는 true|false")
    if cfg.get("days", "weekdays") not in ("weekdays", "daily"):
        errs.append("days 는 weekdays|daily")
    w = cfg.get("web", {})
    if not isinstance(w, dict):
        errs.append("web 은 객체")
    else:
        for k, v in w.items():
            if k == "require_reauth_for_details":
                if not isinstance(v, bool):
                    errs.append("web.require_reauth_for_details 는 true|false")
            elif k in ("rp_id", "origin"):              # 패스키: 도메인(rp_id)·출처(origin, https://도메인)
                if not isinstance(v, str) or (k == "origin" and v and not v.startswith("https://")):
                    errs.append(f"web.{k} 는 문자열(origin 은 https:// 로 시작)")
            elif k in ("idle_min", "session_hours", "reauth_min"):
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                    errs.append(f"web.{k} 는 양수")
            else:
                errs.append(f"web.{k} 는 알 수 없는 키")
    for m, r in (cfg.get("risk") or {}).items():
        if m not in RISK_DEFAULTS or not isinstance(r, dict):
            errs.append(f"risk.{m} 형식 오류")
            continue
        for k, v in r.items():
            if k not in RISK_DEFAULTS[m]:
                errs.append(f"risk.{m}.{k} 는 알 수 없는 키")
            elif k != "allow_sell" and (not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0):
                errs.append(f"risk.{m}.{k} 는 양수여야 한다")
    return errs


def state_dir(cfg: dict, repo_root: Path = REPO_ROOT) -> Path:
    p = Path(cfg["state_dir"])
    return p if p.is_absolute() else repo_root / p


def kill_file(cfg: dict, repo_root: Path = REPO_ROOT) -> Path:
    return state_dir(cfg, repo_root) / "KILL"


def gate_problems(cfg: dict, env: Dict[str, str], execute: bool,
                  repo_root: Path = REPO_ROOT) -> List[str]:
    """이 실행이 지금 가능한가 — 못 하는 이유 목록(비면 통과).

    - 읽기 전용 실행(dry-run): 해당 모드의 키만 필요하다(실전 키로도 잔고 조회만 하는 첫 단계가 가능).
    - 주문 실행(--execute): 모의는 키 + 종목 허용목록, **실전은 아래 전부**.
    """
    p: List[str] = []
    mode = cfg.get("mode")
    if mode in ("paper", "live"):
        kind = "모의투자 키" if mode == "paper" else "실전 키"
        p += [f"환경변수 {k} 가 없다({kind})" for k in key_names(cfg) if not env.get(k)]
    else:
        p.append("mode 는 paper|live")
    if not execute:
        return p
    if kill_file(cfg, repo_root).exists():
        p.append(f"킬 스위치가 켜져 있다({kill_file(cfg, repo_root)}) — `python -m autotrader resume` 로 해제")
    if not cfg.get("symbol_allowlist"):
        p.append("symbol_allowlist 가 비어 있다(허용 종목이 없으면 주문을 내지 않는다)")
    if mode == "live":
        live = cfg.get("live", {})
        if not live.get("enabled"):
            p.append("설정 live.enabled 가 true 가 아니다")
        if not live.get("tr_ids_reviewed"):
            if cfg.get("broker") == "upbit":
                p.append("설정 live.tr_ids_reviewed 가 true 가 아니다(업비트 주문 경로를 upbit-probe 로 확인했다는 표시 — README §11)")
            elif cfg.get("broker") == "bithumb":
                p.append("설정 live.tr_ids_reviewed 가 true 가 아니다(빗썸은 주문 테스트가 없다 — 소액 실검증 주문을 사용자가 직접 해 보고 켠다, 설계 §3 P2)")
            else:
                p.append("설정 live.tr_ids_reviewed 가 true 가 아니다(실전 TR_ID 를 공식 문서와 대조했다는 표시 — README §실전 전환)")
        if env.get("AUTOTRADER_ALLOW_LIVE") != LIVE_ACK:
            p.append(f"환경변수 AUTOTRADER_ALLOW_LIVE={LIVE_ACK} 가 없다(설정 파일만으로는 실계좌를 못 켠다)")
    return p


def mask(value: str, keep: int = 2) -> str:
    """로그·리포트에 남길 때 계좌번호 등을 가린다."""
    if not value:
        return ""
    return value[:keep] + "*" * max(0, len(value) - keep)


# ------------------------------------------------------------------ 프로필(키 묶음 + 전략 + 한도 + 일정)
def profiles_dir(config_path) -> Path:
    """프로필은 기본 설정 파일 옆 profiles/ 폴더의 <이름>.json 이다(VM: ~/collector-venv/autotrader/profiles/)."""
    return Path(config_path).resolve().parent / "profiles"


def load_profile(config_path, name: str, main_cfg: Optional[dict] = None) -> dict:
    """프로필 하나를 읽는다. 상태 폴더는 강제로 <기본 상태>/profiles/<이름> — 원장·토큰·킬 스위치가 프로필끼리 안 섞인다."""
    if not _PROFILE.match(name or ""):
        raise ConfigError(f"프로필 이름은 소문자·숫자·-·_ 만(32자 이내): {name!r}")
    p = profiles_dir(config_path) / f"{name}.json"
    if not p.exists():
        raise ConfigError(f"프로필이 없다: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if "state_dir" in raw:
        raise ConfigError(f"프로필 {name}: state_dir 는 쓰지 않는다(자동으로 정해진다)")
    main_cfg = main_cfg or load_config(config_path)
    cfg = normalize_config({**raw, "state_dir": str(state_dir(main_cfg) / "profiles" / name)})
    cfg["profile"] = name
    cfg["auto_file"] = cfg.get("auto", "off")
    cfg["auto"] = effective_auto(cfg, read_control(cfg).get("auto"))
    return cfg


# ------------------------------------------------------------------ 웹 제어(요청 파일)
# 웹 화면은 키를 못 읽는다. 대신 프로필 상태 폴더에 **요청 파일**만 쓴다 — control.json(자동 여부)·run_request.json(지금 실행).
# 실제 실행은 키를 가진 run-due 가 한다. 웹이 바꿀 수 있는 것은 자동 여부·지금 실행·킬 스위치뿐이다
# (전략·키·한도·종목·모드는 프로필 파일 = SSH 에서만).
_AUTO_RANK = {"off": 0, "dry": 1, "execute": 2}
RUN_REQUEST_MAX_MIN = 15      # 이보다 오래된 실행 요청은 버린다(몇 시간 뒤 뜬금없이 주문하지 않게)


def control_path(cfg: dict) -> Path:
    return state_dir(cfg) / "control.json"


def read_control(cfg: dict) -> dict:
    try:
        d = json.loads(control_path(cfg).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def effective_auto(cfg: dict, web_auto: Optional[str]) -> str:
    """웹 값이 있으면 그것을 쓴다. 단 **실전(live)은 서버가 프로필 파일에 web_live_allowed: true 를 적어 둔 경우에만**
    웹이 파일 값보다 올릴 수 있다. 한도·종목·키는 여전히 파일(서버)이 정한다 — 웹이 뚫려도 손실 상한은 서버 한도다."""
    file_auto = cfg.get("auto", "off")
    if web_auto not in _AUTO_RANK:
        return file_auto
    if cfg.get("mode") == "live" and not cfg.get("web_live_allowed") and _AUTO_RANK[web_auto] > _AUTO_RANK[file_auto]:
        return file_auto
    return web_auto


def web_set_auto(cfg: dict, auto: str, now: datetime) -> Optional[str]:
    """웹에서 자동 여부를 바꾼다. 거부 사유 문자열(None=성공)."""
    if auto not in _AUTO_RANK:
        return "알 수 없는 값"
    if cfg.get("mode") == "live" and not cfg.get("web_live_allowed")             and _AUTO_RANK[auto] > _AUTO_RANK[cfg.get("auto_file", "off")]:
        return "이 실전 프로필은 서버가 웹 켜기를 허락하지 않았다(프로필 파일 web_live_allowed)"
    p = control_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"auto": auto, "at": now.isoformat()}), encoding="utf-8")
    os.replace(tmp, p)
    return None


def run_request_path(cfg: dict) -> Path:
    return state_dir(cfg) / "run_request.json"


def web_request_run(cfg: dict, now: datetime) -> None:
    p = run_request_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"at": now.isoformat()}), encoding="utf-8")


# ---- 웹에서 바꾸는 1회 매수 금액(설계 docs/control/업비트-매수금액-웹설정-설계-2026-11-01.md)
# 웹은 '희망 금액'만 쓴다. 서버 프로필의 한도(risk)가 최종 상한이고 웹은 그것을 올리지 못한다.
NOTIONAL_MIN, NOTIONAL_MAX = 5_000, 10_000_000      # 업비트 최소 주문 ~ 웹 상한
NOTIONAL_BIG_RAISE = 10                              # 현재 값의 이 배수를 넘기는 증액은 확인 문구를 요구한다


def notional_path(cfg: dict) -> Path:
    return state_dir(cfg) / "notional_override.json"


def parse_notional(text) -> Tuple[Optional[int], str]:
    """입력 문자열 → (정수, "") 또는 (None, 사유). 숫자만 받는다 — 쉼표·소수·부호·공백 안쪽 문자는 거부."""
    s = str(text).strip()
    if not s.isascii() or not s.isdigit():
        return None, "금액은 숫자만 입력합니다(쉼표·소수·부호 불가)"
    n = int(s)
    if not NOTIONAL_MIN <= n <= NOTIONAL_MAX:
        return None, f"금액은 {NOTIONAL_MIN:,}원 이상 {NOTIONAL_MAX:,}원 이하여야 합니다"
    return n, ""


def read_notional(cfg: dict) -> Optional[int]:
    """웹이 둔 희망 금액. 파일이 없거나 깨졌거나 범위 밖이면 None(= 프로필 값). 읽는 쪽도 범위를 다시 본다."""
    try:
        d = json.loads(notional_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    n = d.get("notional_krw") if isinstance(d, dict) else None
    return n if type(n) is int and NOTIONAL_MIN <= n <= NOTIONAL_MAX else None


def effective_params(cfg: dict) -> dict:
    """전략에 넘길 params. 프로필이 params.web_notional: true 로 허락한 경우에만 웹 금액이 notional_krw 를 덮고,
    params.web_weights: true 인 경우에만 웹 비율(weights_override.json)이 weights·other_weight 를 덮는다."""
    p = dict(cfg.get("params") or {})
    if p.get("web_notional"):
        n = read_notional(cfg)
        if n is not None:
            p[amount_key(cfg)] = n
    if p.get("web_weights"):
        w = read_weights(cfg)
        if w is not None:
            p["weights"], p["other_weight"] = w
    return p


# ---- 웹에서 바꾸는 크립토 비율(crypto_weights) — 설계 docs/control/크립토-목표비중-전략-설계-2026-11-01.md §7
def weights_path(cfg: dict) -> Path:
    return state_dir(cfg) / "weights_override.json"


def weight_names(cfg: dict) -> List[str]:
    """웹 입력 칸 순서 — 프로필 params.weights 의 코인들, 마지막이 '기타'."""
    return list((cfg.get("params") or {}).get("weights") or {})


def parse_weights(cfg: dict, text) -> Tuple[Optional[List[int]], str]:
    """'50,20,30'(코인 칸들 + 기타, 정수 %) → ([50,20,30], "") 또는 (None, 사유). 합 ≤ 100."""
    parts = [x.strip() for x in str(text).split(",")]
    n = len(weight_names(cfg)) + 1
    if len(parts) != n or any((not x.isascii()) or (not x.isdigit()) for x in parts):
        return None, f"비율은 정수 {n}개(%)를 쉼표로 — 코인 {n - 1}개 + 기타"
    v = [int(x) for x in parts]
    if any(x > 100 for x in v) or sum(v) > 100:
        return None, f"각 비율은 0~100, 합은 100 이하(지금 {sum(v)})"
    return v, ""


def read_weights(cfg: dict):
    """웹이 둔 비율 → ({코인: 0~1}, 기타 0~1) 또는 None(없음·깨짐·범위 밖 = 프로필 값). 읽는 쪽도 다시 검사한다."""
    try:
        d = json.loads(weights_path(cfg).read_text(encoding="utf-8"))
        names = weight_names(cfg)
        pct = d["pct"]
        if not (isinstance(pct, list) and len(pct) == len(names) + 1 and all(type(x) is int and 0 <= x <= 100 for x in pct)
                and sum(pct) <= 100):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {s: pct[i] / 100 for i, s in enumerate(names) if pct[i] > 0}, pct[-1] / 100


def current_weights(cfg: dict) -> Tuple[Dict[str, float], float]:
    p = effective_params(cfg)
    return dict(p.get("weights") or {}), float(p.get("other_weight") or 0)


def check_weights(cfg: dict, pct: List[int]) -> Optional[str]:
    """웹 비율을 서버 한도와 맞춰 본다(코인 하나가 자본 × 비율만큼 보유해도 종목당 보유 한도 안인지). 거부 사유(None=통과)."""
    p = cfg.get("params") or {}
    if not p.get("web_weights"):
        return "이 프로필은 서버가 웹 비율 설정을 허락하지 않았다(프로필 params.web_weights)"
    names = weight_names(cfg)
    if len(pct) != len(names) + 1 or sum(pct) > 100:
        return "비율 형식이 맞지 않는다"
    if pct[-1] > 0 and not p.get("other_candidates"):
        return "서버에 '기타' 후보 코인(params.other_candidates)이 없어 기타 비율을 못 둔다"
    cap = float(p.get("capital_krw") or 0)
    top_n = max(1, int(p.get("other_top_n", 5)))
    lim = float(((cfg.get("risk") or {}).get(crypto_market(cfg) or "UPBIT") or {}).get("max_position_value") or 0)
    worst = max([x for x in pct[:-1]] + [pct[-1] / top_n]) / 100 * cap
    if worst > lim:
        return f"코인 하나의 목표 금액 {worst:,.0f}원이 서버 종목당 보유 한도 {lim:,.0f}원을 넘습니다 — 서버 프로필(SSH)에서 한도를 올려야 저장됩니다"
    return None


def web_set_weights(cfg: dict, pct: List[int], now: datetime) -> Optional[str]:
    err = check_weights(cfg, pct)
    if err:
        return err
    p = weights_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pct": pct, "at": now.isoformat()}), encoding="utf-8")
    os.replace(tmp, p)
    with (p.parent / "weights_history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now.isoformat(), "pct": pct}) + chr(10))
    return None


def amount_key(cfg: dict) -> str:
    """웹이 바꾸는 금액이 가리키는 전략 값 — 한 바구니(crypto_weights)는 자본(capital_krw), 그 밖은 1회 매수 금액(notional_krw)."""
    return "capital_krw" if cfg.get("strategy") == "crypto_weights" else "notional_krw"


def amount_label(cfg: dict) -> str:
    return "자본" if cfg.get("strategy") == "crypto_weights" else "1회 매수 금액"


def current_notional(cfg: dict) -> Optional[float]:
    v = effective_params(cfg).get(amount_key(cfg))
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def check_notional(cfg: dict, n: int) -> Optional[str]:
    """웹 금액 n 을 서버 한도와 맞춰 본다. 거부 사유 문자열(None=통과). 한도를 깎아 맞추지 않는다."""
    if not (cfg.get("params") or {}).get("web_notional"):
        return "이 프로필은 서버가 웹 금액 설정을 허락하지 않았다(프로필 params.web_notional)"
    if not NOTIONAL_MIN <= n <= NOTIONAL_MAX:
        return f"금액은 {NOTIONAL_MIN:,}원 이상 {NOTIONAL_MAX:,}원 이하여야 합니다"
    r = (cfg.get("risk") or {}).get(crypto_market(cfg) or "UPBIT") or {}
    if cfg.get("strategy") == "crypto_weights":                       # 자본: 한 주문(max_order_krw)·하루(자본의 2배)·코인 하나의 목표 금액이 한도 안인지
        pr = cfg.get("params") or {}
        order = float(pr.get("max_order_krw") or n * 0.2)
        share = max([float(pr.get("other_max_share", 1.0)) if float(pr.get("other_weight") or 0) > 0 else 0.0]
                    + [float(v) for v in (pr.get("weights") or {}).values()] + [0.0])
        need = (("max_order_value", order, "주문당 한도(한 주문 상한 max_order_krw 이상)"),
                ("max_daily_value", n * 2, "하루 한도(매수+매도, 자본의 2배)"),
                ("max_position_value", n * share, "종목당 보유 한도(자본 × 한 코인 최대 비중)"))
    else:
        need = (("max_order_value", n * 3 / 2, "주문당 한도(매도 포함, 1회 금액의 1.5배)"),
                ("max_daily_value", n * 2, "하루 한도(매수+매도, 1회 금액의 2배)"),
                ("max_position_value", n, "종목당 보유 한도(개인 보유 BTC 평가액은 별도로 더해서 잡는다)"))
    for key, lo, label in need:
        if float(r.get(key) or 0) < lo:
            return f"서버 {label} {int(r.get(key) or 0):,}원이 모자랍니다 — {int(lo):,}원 이상으로 서버 프로필(SSH)에서 올려야 저장됩니다"
    return None


def needs_big_raise_phrase(cfg: dict, n: int) -> bool:
    cur = current_notional(cfg)
    return bool(cur) and n > cur * NOTIONAL_BIG_RAISE


def web_set_notional(cfg: dict, n: int, now: datetime) -> Optional[str]:
    """웹에서 1회 매수 금액을 바꾼다(다음 매수부터). 거부 사유 문자열(None=성공)."""
    err = check_notional(cfg, n)
    if err:
        return err
    prev = current_notional(cfg)
    p = notional_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"notional_krw": n, "at": now.isoformat(), "prev": prev}), encoding="utf-8")
    os.replace(tmp, p)
    with (p.parent / "notional_history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now.isoformat(), "prev": prev, "notional_krw": n}) + "\n")
    return None


def notional_history(cfg: dict, limit: int = 5) -> List[dict]:
    try:
        rows = [json.loads(x) for x in (state_dir(cfg) / "notional_history.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []
    return rows[-limit:][::-1]


def take_run_request(cfg: dict, now: datetime) -> Optional[str]:
    """실행 요청을 **소비**한다(먼저 지운다 — 두 번 실행하지 않게). 유효하면 요청 시각, 아니면 None."""
    p = run_request_path(cfg)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    try:
        p.unlink()
    except OSError:
        pass
    if not d:
        return None
    try:
        at = datetime.fromisoformat(d["at"])
    except (KeyError, ValueError, TypeError):
        return None
    return d["at"] if timedelta(0) <= now - at <= timedelta(minutes=RUN_REQUEST_MAX_MIN) else None


def list_profiles(config_path) -> List[str]:
    d = profiles_dir(config_path)
    return sorted(p.stem for p in d.glob("*.json") if _PROFILE.match(p.stem)) if d.exists() else []


def expand_run_at(items: List[str]) -> List[str]:
    """"09:05-15:15/5" → ["09:05", "09:10", …, "15:15"]. 단일 시각은 그대로."""
    out = []
    for t in items:
        if "-" not in t:
            out.append(t)
            continue
        span, step = t.split("/")
        a, b = (int(x[:2]) * 60 + int(x[3:]) for x in span.split("-"))
        out += [f"{m // 60:02d}:{m % 60:02d}" for m in range(a, b + 1, int(step))]
    return out


def due_slots(cfg: dict, now: datetime, done: List[str]) -> List[str]:
    """지금 돌아야 할 예약 회차("YYYY-MM-DD HH:MM"). 예약 시각 ≤ 지금 < 예약 + RUN_GRACE_MIN, 아직 안 돈 것만."""
    if cfg.get("auto", "off") == "off":
        return []
    if cfg.get("days", "weekdays") == "weekdays" and now.weekday() >= 5:
        return []
    out = []
    for t in expand_run_at(cfg.get("run_at", [])):
        h, m = map(int, t.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        slot = at.strftime("%Y-%m-%d %H:%M")
        if at <= now < at + timedelta(minutes=RUN_GRACE_MIN) and slot not in done:
            out.append(slot)
    return out
