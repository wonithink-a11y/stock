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
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_ACK = "I-ACCEPT-REAL-TRADES"          # 환경변수 AUTOTRADER_ALLOW_LIVE 가 정확히 이 값이어야 실계좌 주문이 열린다

PAPER_KEYS = ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET", "KIS_VTS_ACCOUNT_NO")
LIVE_KEYS = ("KIS_LIVE_APP_KEY", "KIS_LIVE_APP_SECRET", "KIS_LIVE_ACCOUNT_NO")   # 시세용 KIS_APP_KEY 와 이름을 분리했다
ENV_KEYS = PAPER_KEYS + LIVE_KEYS + ("AUTOTRADER_ALLOW_LIVE", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
# 키 묶음 교체: 설정 "key_prefix": "KIS_VTS2" → KIS_VTS2_APP_KEY / _APP_SECRET / _ACCOUNT_NO 를 쓴다.
# 접두사 뒤에 한 마디 이상을 강제한다 — 시세용 KIS_APP_KEY(접두사 "KIS")는 고를 수 없다.
_PREFIX = re.compile(r"^KIS_[A-Z0-9]+(_[A-Z0-9]+)*$")
_KEYSET_ENV = re.compile(r"^KIS_[A-Z0-9_]+_(APP_KEY|APP_SECRET|ACCOUNT_NO)$")
_PROFILE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
AUTO_MODES = ("off", "dry", "execute")
RUN_GRACE_MIN = 20          # 예약 시각에서 이만큼 지나면 그 회차는 건너뛴다(몇 시간 늦게 몰아서 주문하지 않게)

# 보수적 기본값 — 사용자가 설정에서 명시적으로 올려야 커진다. 통화는 시장 기준(KR=원, US=달러).
RISK_DEFAULTS = {
    "KR": {"max_order_value": 300_000, "max_daily_value": 1_000_000, "max_orders_per_run": 5,
           "price_band_pct": 5.0, "max_position_value": 1_000_000, "allow_sell": True},
    "US": {"max_order_value": 300, "max_daily_value": 1_000, "max_orders_per_run": 5,
           "price_band_pct": 5.0, "max_position_value": 1_000, "allow_sell": True},
}


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
        if k in ENV_KEYS or _KEYSET_ENV.match(k):
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
        if v and (k in ENV_KEYS or _KEYSET_ENV.match(k)):
            env[k] = v
    return env


def key_names(cfg: dict) -> tuple:
    """이 설정이 쓰는 키 환경변수 이름 3개(앱키·시크릿·계좌). 기본은 모드별 KIS_VTS_* / KIS_LIVE_*."""
    pre = cfg.get("key_prefix")
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
    if not isinstance(mk, list) or not mk or any(m not in ("KR", "US") for m in mk):
        errs.append("markets 는 [\"KR\"] 또는 [\"US\"] 또는 둘 다")
    al = cfg.get("symbol_allowlist", [])
    if not isinstance(al, list) or any(not isinstance(s, str) for s in al):
        errs.append("symbol_allowlist 는 종목코드 문자열 목록")
    pre = cfg.get("key_prefix")
    if pre is not None and not (isinstance(pre, str) and _PREFIX.match(pre)):
        errs.append("key_prefix 는 KIS_ 로 시작하는 대문자 이름(예: KIS_VTS2). 시세용 KIS 키는 쓸 수 없다")
    if cfg.get("auto", "off") not in AUTO_MODES:
        errs.append("auto 는 off|dry|execute")
    ra = cfg.get("run_at", [])
    if not isinstance(ra, list) or any(not (isinstance(t, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t)) for t in ra):
        errs.append("run_at 은 \"HH:MM\"(KST) 목록")
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
            elif k in ("idle_min", "session_hours", "reauth_min"):
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                    errs.append(f"web.{k} 는 양수")
            else:
                errs.append(f"web.{k} 는 알 수 없는 키")
    for m, r in (cfg.get("risk") or {}).items():
        if m not in ("KR", "US") or not isinstance(r, dict):
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


def due_slots(cfg: dict, now: datetime, done: List[str]) -> List[str]:
    """지금 돌아야 할 예약 회차("YYYY-MM-DD HH:MM"). 예약 시각 ≤ 지금 < 예약 + RUN_GRACE_MIN, 아직 안 돈 것만."""
    if cfg.get("auto", "off") == "off":
        return []
    if cfg.get("days", "weekdays") == "weekdays" and now.weekday() >= 5:
        return []
    out = []
    for t in cfg.get("run_at", []):
        h, m = map(int, t.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        slot = at.strftime("%Y-%m-%d %H:%M")
        if at <= now < at + timedelta(minutes=RUN_GRACE_MIN) and slot not in done:
            out.append(slot)
    return out
