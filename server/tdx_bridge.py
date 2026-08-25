"""
Optional easy_tdx integration.
- Data: try TDX protocol, fall back to public HTTP (market.py)
- Indicators: easy_tdx.indicator on any OHLCV bars when package installed
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("zhuli_radar.tdx")

_HAS_EASY = False
try:
    import easy_tdx  # noqa: F401
    _HAS_EASY = True
except ImportError:
    _HAS_EASY = False


def easy_tdx_available() -> bool:
    return _HAS_EASY


def _bars_from_df(df) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for _, row in df.iterrows():
        d = row.get("date")
        if hasattr(d, "strftime"):
            ds = d.strftime("%Y-%m-%d")
        else:
            ds = str(d)[:10]
        vol = float(row["vol"] if "vol" in row.index else row.get("volume", 0) or 0)
        out.append({
            "date": ds,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": vol,
        })
    return out


def tdx_index_klines(count: int = 120) -> list[dict] | None:
    if not _HAS_EASY:
        return None
    try:
        from easy_tdx import TdxClient, Market, KlineCategory
        with TdxClient() as c:
            df = c.get_index_bars(Market.SH, "000001", KlineCategory.DAY, 0, count)
        bars = _bars_from_df(df)
        return bars or None
    except Exception as e:
        log.warning("tdx index kline failed: %s", e)
        return None


def tdx_stock_klines(code: str, count: int = 120) -> list[dict] | None:
    if not _HAS_EASY:
        return None
    try:
        from easy_tdx import TdxClient, Market, KlineCategory
        from .market import market_prefix
        mkt = Market.SZ if market_prefix(code) == "sz" else Market.SH
        with TdxClient() as c:
            df = c.get_security_bars(mkt, code, KlineCategory.DAY, 0, count)
        bars = _bars_from_df(df)
        return bars or None
    except Exception as e:
        log.warning("tdx stock kline %s failed: %s", code, e)
        return None


def tdx_stock_quote(code: str) -> dict | None:
    if not _HAS_EASY:
        return None
    try:
        from easy_tdx import TdxClient, Market
        from .market import market_prefix
        mkt = Market.SZ if market_prefix(code) == "sz" else Market.SH
        with TdxClient() as c:
            df = c.get_security_quotes([(mkt, code)])
        if df is None or getattr(df, "empty", True):
            return None
        row = df.iloc[0]
        # column names vary by version — be defensive
        def g(*names, default=0):
            for n in names:
                if n in df.columns:
                    v = row[n]
                    return v
            return default
        price = float(g("price", "last_close", "close", default=0) or 0)
        prev = float(g("last_close", "pre_close", "prev_close", default=price) or price)
        name = str(g("name", "code", default=code))
        return {
            "code": code,
            "name": name if name != code else code,
            "price": price,
            "prevClose": prev,
            "open": float(g("open", default=price) or price),
            "high": float(g("high", default=price) or price),
            "low": float(g("low", default=price) or price),
            "change": round(price - prev, 2),
            "changePct": round((price - prev) / prev * 100, 2) if prev else 0,
            "volume": float(g("vol", "volume", default=0) or 0),
            "amount": float(g("amount", default=0) or 0),
            "turnover": float(g("turnover", default=0) or 0),
        }
    except Exception as e:
        log.warning("tdx quote %s failed: %s", code, e)
        return None


def tdx_fund_flow(code: str) -> dict | None:
    if not _HAS_EASY:
        return None
    try:
        from easy_tdx import TdxClient, Market
        from .market import market_prefix
        mkt = Market.SZ if market_prefix(code) == "sz" else Market.SH
        with TdxClient() as c:
            ff = c.get_fund_flow(mkt, code)
        if ff is None:
            return None
        if hasattr(ff, "to_dict"):
            return {"raw": ff.to_dict() if not hasattr(ff, "iloc") else ff.iloc[-1].to_dict()}
        if isinstance(ff, dict):
            return ff
        return {"raw": str(ff)[:500]}
    except Exception as e:
        log.warning("tdx fund_flow %s failed: %s", code, e)
        return None


def compute_tech_indicators(bars: list[dict]) -> dict[str, Any]:
    """MACD/KDJ/RSI/BOLL on bars. Uses easy_tdx if present, else pure-Python subset."""
    if len(bars) < 30:
        return {"ok": False, "reason": "K线不足"}
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    if _HAS_EASY:
        try:
            import pandas as pd
            from easy_tdx.indicator import compute_indicators
            df = pd.DataFrame(bars)
            out = compute_indicators(df, ["MACD", "RSI", "KDJ", "BOLL"])
            last = out.iloc[-1]
            prev = out.iloc[-2] if len(out) > 1 else last
            return {
                "ok": True,
                "source": "easy_tdx",
                "macd": {
                    "dif": _f(last.get("MACD_DIF")),
                    "dea": _f(last.get("MACD_DEA")),
                    "hist": _f(last.get("MACD_HIST")),
                    "cross": _macd_cross(prev, last),
                },
                "rsi": _f(last.get("RSI")),
                "kdj": {
                    "k": _f(last.get("KDJ_K")),
                    "d": _f(last.get("KDJ_D")),
                    "j": _f(last.get("KDJ_J")),
                },
                "boll": {
                    "upper": _f(last.get("BOLL_UPPER")),
                    "mid": _f(last.get("BOLL_MID")),
                    "lower": _f(last.get("BOLL_LOWER")),
                },
            }
        except Exception as e:
            log.warning("easy_tdx indicators failed, fallback: %s", e)

    return _pure_indicators(closes, highs, lows)


def _f(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return None
        return round(float(v), 4)
    except Exception:
        return None


def _macd_cross(prev, last) -> str:
    try:
        ph, lh = float(prev.get("MACD_HIST", 0) or 0), float(last.get("MACD_HIST", 0) or 0)
        if ph <= 0 < lh:
            return "金叉"
        if ph >= 0 > lh:
            return "死叉"
    except Exception:
        pass
    return "—"


def _ema(vals: list[float], n: int) -> list[float]:
    if not vals:
        return []
    k = 2 / (n + 1)
    out = [vals[0]]
    for i in range(1, len(vals)):
        out.append(vals[i] * k + out[-1] * (1 - k))
    return out


def _pure_indicators(closes, highs, lows) -> dict[str, Any]:
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = _ema(dif, 9)
    hist = [d - e for d, e in zip(dif, dea)]
    # RSI 14
    rsis = []
    for i in range(len(closes)):
        if i < 14:
            rsis.append(None)
            continue
        gains = losses = 0.0
        for j in range(i - 13, i + 1):
            ch = closes[j] - closes[j - 1]
            if ch >= 0:
                gains += ch
            else:
                losses -= ch
        if losses == 0:
            rsis.append(100.0)
        else:
            rs = gains / losses
            rsis.append(100 - 100 / (1 + rs))
    # simple boll 20
    n = 20
    mid = sum(closes[-n:]) / n
    var = sum((c - mid) ** 2 for c in closes[-n:]) / n
    std = var ** 0.5
    cross = "—"
    if len(hist) >= 2:
        if hist[-2] <= 0 < hist[-1]:
            cross = "金叉"
        elif hist[-2] >= 0 > hist[-1]:
            cross = "死叉"
    return {
        "ok": True,
        "source": "builtin",
        "macd": {
            "dif": round(dif[-1], 4),
            "dea": round(dea[-1], 4),
            "hist": round(hist[-1], 4),
            "cross": cross,
        },
        "rsi": round(rsis[-1], 2) if rsis[-1] is not None else None,
        "kdj": None,
        "boll": {
            "upper": round(mid + 2 * std, 4),
            "mid": round(mid, 4),
            "lower": round(mid - 2 * std, 4),
        },
    }


def indicator_hints(ind: dict, phase: str) -> list[str]:
    """Turn indicators into short Chinese evidence lines."""
    if not ind or not ind.get("ok"):
        return []
    hints = []
    macd = ind.get("macd") or {}
    if macd.get("cross") == "金叉":
        hints.append("MACD 金叉，动能转强（辅助，非单独买卖点）。")
    elif macd.get("cross") == "死叉":
        hints.append("MACD 死叉，动能转弱（辅助）。")
    rsi = ind.get("rsi")
    if rsi is not None:
        if rsi >= 70:
            hints.append(f"RSI={rsi:.1f} 偏高，注意拥挤与回撤。")
        elif rsi <= 30:
            hints.append(f"RSI={rsi:.1f} 偏低，超卖区需结合形态。")
    boll = ind.get("boll") or {}
    # phase consistency notes
    if phase == "拉升" and macd.get("hist") is not None and macd["hist"] > 0:
        hints.append("主升阶段与 MACD 柱>0 同向。")
    if phase in ("出货", "下跌") and macd.get("hist") is not None and macd["hist"] < 0:
        hints.append("弱势阶段与 MACD 柱<0 同向。")
    return hints[:4]
