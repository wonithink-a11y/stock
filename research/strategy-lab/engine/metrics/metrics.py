"""Pure functions over an equity curve and a trade list. No strategy knowledge."""
import math
from datetime import date as _date


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def total_return(equity_curve):
    if len(equity_curve) < 2:
        return None
    return equity_curve[-1][1] / equity_curve[0][1] - 1


def cagr(equity_curve):
    if len(equity_curve) < 2:
        return None
    start_date, start_eq = equity_curve[0]
    end_date, end_eq = equity_curve[-1]
    years = (_to_ordinal(end_date) - _to_ordinal(start_date)) / 365.25
    if years <= 0 or start_eq <= 0:
        return None
    return (end_eq / start_eq) ** (1 / years) - 1


def max_drawdown(equity_curve):
    if not equity_curve:
        return None
    peak = equity_curve[0][1]
    mdd = 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        mdd = min(mdd, (eq - peak) / peak)
    return mdd


def _daily_returns(equity_curve):
    rets = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1][1]
        if prev > 0:
            rets.append(equity_curve[i][1] / prev - 1)
    return rets


def sharpe(equity_curve, annualization=252):
    rets = _daily_returns(equity_curve)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    return None if std == 0 else mean / std * math.sqrt(annualization)


def sortino(equity_curve, annualization=252):
    rets = _daily_returns(equity_curve)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    downside = [min(r, 0) ** 2 for r in rets]
    dd_std = math.sqrt(sum(downside) / len(downside))
    return None if dd_std == 0 else mean / dd_std * math.sqrt(annualization)


def calmar(equity_curve):
    c, mdd = cagr(equity_curve), max_drawdown(equity_curve)
    return None if (c is None or not mdd) else c / abs(mdd)


def trade_stats(trades):
    """trades: [{"pnl": float, "holding_sessions": int}, ...]"""
    n = len(trades)
    if n == 0:
        return {k: None for k in (
            "tradeCount", "winRate", "avgWin", "avgLoss", "winLossRatio",
            "profitFactor", "expectancy", "avgHoldingPeriod",
            "maxConsecutiveWins", "maxConsecutiveLosses")} | {"tradeCount": 0}

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None

    streak, max_w, max_l, cur_sign = 0, 0, 0, None
    for t in trades:
        sign = "W" if t["pnl"] > 0 else "L"
        streak = streak + 1 if sign == cur_sign else 1
        cur_sign = sign
        if sign == "W":
            max_w = max(max_w, streak)
        else:
            max_l = max(max_l, streak)

    return {
        "tradeCount": n,
        "winRate": len(wins) / n,
        "avgWin": avg_win,
        "avgLoss": avg_loss,
        "winLossRatio": (avg_win / abs(avg_loss)) if (avg_win and avg_loss) else None,
        "profitFactor": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "expectancy": sum(t["pnl"] for t in trades) / n,
        "avgHoldingPeriod": sum(t["holding_sessions"] for t in trades) / n,
        "maxConsecutiveWins": max_w,
        "maxConsecutiveLosses": max_l,
    }
