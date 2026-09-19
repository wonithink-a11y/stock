"""설정 로드·검증과 모드 게이트.

★ 실계좌 모드는 여러 겹의 스위치 뒤에 잠겨 있다(`gate_problems`). 하나라도 빠지면 실행을 거부한다 —
   조용히 모의나 dry-run 으로 강등하지 않는다(강등하면 사용자가 "돌고 있다"고 착각한다).
★ 키는 이 파일 어디에도 없다. 환경변수 또는 저장소 루트 `.env`(gitignore)에서만 읽는다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_ACK = "I-ACCEPT-REAL-TRADES"          # 환경변수 AUTOTRADER_ALLOW_LIVE 가 정확히 이 값이어야 실계좌 주문이 열린다

PAPER_KEYS = ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET", "KIS_VTS_ACCOUNT_NO")
LIVE_KEYS = ("KIS_LIVE_APP_KEY", "KIS_LIVE_APP_SECRET", "KIS_LIVE_ACCOUNT_NO")   # 시세용 KIS_APP_KEY 와 이름을 분리했다
ENV_KEYS = PAPER_KEYS + LIVE_KEYS + ("AUTOTRADER_ALLOW_LIVE",)

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
        if k in ENV_KEYS:
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
    for k in ENV_KEYS:
        if src.get(k):
            env[k] = src[k]
    return env


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
    if mode == "paper":
        p += [f"환경변수 {k} 가 없다(모의투자 키)" for k in PAPER_KEYS if not env.get(k)]
    elif mode == "live":
        p += [f"환경변수 {k} 가 없다(실전 키)" for k in LIVE_KEYS if not env.get(k)]
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
