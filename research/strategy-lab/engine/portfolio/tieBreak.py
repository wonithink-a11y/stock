"""Name -> ordering function registry. A strategy's policy.json names a tie-break
by string; portfolio.py never knows which strategy asked for it.
"""


def ticker_ascending(candidates):
    """candidates: [(order, entry_fill)]. Sorted by symbol ascending."""
    return sorted(candidates, key=lambda pair: pair[0].symbol)


def cci_recovery_desc(candidates):
    """Sorted by CCI recovery magnitude (t - t-1) descending, ticker ascending on
    ties. Requires the order to carry a 'cciRecovery' value in its risk_spec's
    companion metadata - wired up when 5DC-v1A-RANK is implemented (Phase 3).
    Registered now so Primary's tie-break and RANK's tie-break are selected the
    same way (a name in policy.json), not by branching in portfolio.py.
    """
    def key(pair):
        order = pair[0]
        recovery = getattr(order, "metadata", {}).get("cciRecovery", 0.0)
        return (-recovery, order.symbol)
    return sorted(candidates, key=key)


_REGISTRY = {
    "ticker_ascending": ticker_ascending,
    "cci_recovery_desc": cci_recovery_desc,
}


def get_tie_break(name):
    if name not in _REGISTRY:
        raise ValueError(f"unknown tie-break: {name}")
    return _REGISTRY[name]
