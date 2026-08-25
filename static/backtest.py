"""Simple rule backtest on daily bars (honest costs + T+1 approximation)."""

from __future__ import annotations

from .analyze import analyze_index, analyze_stock
from .market import fetch_index_klines, fetch_klines_batch, fetch_main_board_quotes


def run_backtest(
    levels_allow: list[str] | None = None,
    max_hold: int = 8,
    cost_bps: float = 15,
) -> dict:
    """
    Walk last ~80 sessions on a fixed liquid pool.
    Signal at close → trade next bar open (approx); sell when level not allowed.
    T+1: cannot sell same day as buy.
    """
    levels_allow = levels_allow or ["可关注"]
    quotes = fetch_main_board_quotes(60)[:36]
    codes = [q["code"] for q in quotes]
    names = {q["code"]: q["name"] for q in quotes}
    index_bars = fetch_index_klines(100)
    kmap = fetch_klines_batch(codes, 100, workers=14)

    # trading calendar from index
    dates = [b["date"] for b in index_bars]
    if len(dates) < 40:
        return {"ok": False, "error": "指数K线不足"}

    cash = 1.0
    positions: dict[str, dict] = {}  # code -> {shares, entry_i, entry_price}
    equity_curve = []
    trades = []
    cost = cost_bps / 10000.0

    def portfolio_value(i: int) -> float:
        v = cash
        for code, pos in positions.items():
            bars = kmap.get(code) or []
            # map date
            d = dates[i]
            px = pos["entry_price"]
            for b in bars:
                if b["date"] == d:
                    px = b["close"]
                    break
            v += pos["shares"] * px
        return v

    start_i = max(25, len(dates) - 80)
    for i in range(start_i, len(dates)):
        d = dates[i]
        idx_slice = index_bars[: i + 1]
        regime = analyze_index(idx_slice, index_bars[i]["close"])["regime"]

        # mark-to-market
        equity_curve.append({"date": d, "equity": round(portfolio_value(i), 4), "regime": regime})

        # sells first (T+1: entry_i < i)
        to_sell = []
        for code, pos in list(positions.items()):
            if pos["entry_i"] >= i:
                continue
            bars = kmap.get(code) or []
            # build bars up to i
            sub = [b for b in bars if b["date"] <= d]
            if len(sub) < 25:
                continue
            # fake quote at close
            q = {
                "code": code,
                "name": names.get(code, code),
                "price": sub[-1]["close"],
                "changePct": 0,
                "amount": 0,
                "volume": sub[-1]["volume"],
                "open": sub[-1]["open"],
                "high": sub[-1]["high"],
                "low": sub[-1]["low"],
                "prevClose": sub[-2]["close"] if len(sub) > 1 else sub[-1]["close"],
                "turnover": 0,
                "industry": [],
            }
            a = analyze_stock(sub, idx_slice, q, regime)
            if a["level"] not in levels_allow:
                to_sell.append(code)

        for code in to_sell:
            pos = positions.pop(code)
            bars = kmap.get(code) or []
            px = pos["entry_price"]
            for b in bars:
                if b["date"] == d:
                    px = b["close"]
                    break
            proceeds = pos["shares"] * px * (1 - cost)
            cash += proceeds
            trades.append({
                "date": d,
                "code": code,
                "name": names.get(code, code),
                "side": "卖",
                "price": round(px, 3),
                "reason": "级别不再满足",
            })

        if regime == "弱势空头":
            continue  # silent — no new buys

        # candidates
        cands = []
        for code in codes:
            if code in positions:
                continue
            bars = kmap.get(code) or []
            sub = [b for b in bars if b["date"] <= d]
            if len(sub) < 25:
                continue
            q = {
                "code": code,
                "name": names.get(code, code),
                "price": sub[-1]["close"],
                "changePct": 0,
                "amount": 0,
                "volume": sub[-1]["volume"],
                "open": sub[-1]["open"],
                "high": sub[-1]["high"],
                "low": sub[-1]["low"],
                "prevClose": sub[-2]["close"] if len(sub) > 1 else sub[-1]["close"],
                "turnover": 0,
                "industry": [],
            }
            a = analyze_stock(sub, idx_slice, q, regime)
            if a["level"] in levels_allow:
                cands.append((a["scores"]["force"], code, a, sub[-1]["close"]))
        cands.sort(reverse=True)
        slots = max_hold - len(positions)
        for _, code, a, px in cands[:slots]:
            if cash < 0.02:
                break
            alloc = cash / max(slots, 1)
            shares = (alloc * (1 - cost)) / px if px else 0
            if shares <= 0:
                continue
            cash -= shares * px * (1 + cost)
            positions[code] = {"shares": shares, "entry_i": i, "entry_price": px}
            trades.append({
                "date": d,
                "code": code,
                "name": names.get(code, code),
                "side": "买",
                "price": round(px, 3),
                "reason": f"{a['level']}/{a['phase']}/{a['vsIndex']}",
            })
            slots -= 1

    # final equity
    final = equity_curve[-1]["equity"] if equity_curve else 1.0
    # max drawdown
    peak = 1.0
    max_dd = 0.0
    for p in equity_curve:
        peak = max(peak, p["equity"])
        max_dd = min(max_dd, p["equity"] / peak - 1)

    # vs index
    i0 = index_bars[start_i]["close"]
    i1 = index_bars[-1]["close"]
    index_ret = i1 / i0 - 1 if i0 else 0

    return {
        "ok": True,
        "start": dates[start_i],
        "end": dates[-1],
        "finalEquity": round(final, 4),
        "totalReturn": round(final - 1, 4),
        "indexReturn": round(index_ret, 4),
        "excessReturn": round((final - 1) - index_ret, 4),
        "maxDrawdown": round(max_dd, 4),
        "trades": len(trades),
        "tradeList": trades[-40:],
        "equityCurve": equity_curve,
        "params": {
            "levelsAllow": levels_allow,
            "maxHold": max_hold,
            "costBps": cost_bps,
            "pool": len(codes),
        },
        "note": "信号日收盘定级，次日以收盘近似成交；含成本与T+1；弱势空头不新开仓。公开数据演示用。",
    }
