"""
Optional data providers: AkShare / Tushare.
Priority used by market.py: tdx → akshare → tushare → public HTTP.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger("zhuli.data")

_HAS_AK = False
_HAS_TS = False
try:
    import akshare as ak  # noqa: F401
    _HAS_AK = True
except ImportError:
    pass
try:
    import tushare as ts  # noqa: F401
    _HAS_TS = True
except ImportError:
    pass


def providers_status() -> dict[str, Any]:
    token = bool(os.environ.get("66b2d7dab5c95d63c8087a66227978fc0d46f0a471ca70bab24b87f9") or os.environ.get("TUSHARE_PRO_TOKEN"))
    return {
        "akshare": _HAS_AK,
        "tushare": _HAS_TS,
        "tushareToken": token,
    }


def _ts_pro():
    if not _HAS_TS:
        return None
    token = os.environ.get("66b2d7dab5c95d63c8087a66227978fc0d46f0a471ca70bab24b87f9") or os.environ.get("TUSHARE_PRO_TOKEN") or ""
    if not token:
        return None
    try:
        import tushare as ts
        return ts.pro_api(token)
    except Exception as e:
        log.warning("tushare pro init failed: %s", e)
        return None


def _ts_code(code: str, prefix: str) -> str:
    """600519 + sh -> 600519.SH ; 000001 + sz -> 000001.SZ"""
    c = code.zfill(6)
    m = "SH" if prefix == "sh" else "SZ"
    return f"{c}.{m}"


def ak_index_klines(count: int = 120) -> list[dict] | None:
    if not _HAS_AK:
        return None
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is None or df.empty:
            return None
        df = df.tail(count)
        bars = []
        for _, r in df.iterrows():
            d = r.get("date")
            if hasattr(d, "strftime"):
                ds = d.strftime("%Y-%m-%d")
            else:
                ds = str(d)[:10]
            bars.append({
                "date": ds,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume") or 0),
            })
        return bars or None
    except Exception as e:
        log.warning("ak index kline: %s", e)
        return None


def ak_stock_klines(code: str, prefix: str, count: int = 90) -> list[dict] | None:
    if not _HAS_AK:
        return None
    try:
        import akshare as ak
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=int(count * 2.2))).strftime("%Y%m%d")
        # ETF vs stock
        is_etf = code.startswith(("51", "52", "56", "58", "15", "16"))
        if is_etf:
            try:
                df = ak.fund_etf_hist_em(
                    symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq"
                )
            except Exception:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq"
                )
        else:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq"
            )
        if df is None or df.empty:
            return None
        # columns: 日期 开盘 收盘 最高 最低 成交量 ...
        col_map = {}
        for c in df.columns:
            cs = str(c)
            if "日期" in cs or cs.lower() == "date":
                col_map["date"] = c
            elif "开盘" in cs or cs.lower() == "open":
                col_map["open"] = c
            elif "收盘" in cs or cs.lower() == "close":
                col_map["close"] = c
            elif "最高" in cs or cs.lower() == "high":
                col_map["high"] = c
            elif "最低" in cs or cs.lower() == "low":
                col_map["low"] = c
            elif "成交量" in cs or cs.lower() == "volume":
                col_map["volume"] = c
        bars = []
        for _, r in df.iterrows():
            d = r[col_map.get("date", df.columns[0])]
            if hasattr(d, "strftime"):
                ds = d.strftime("%Y-%m-%d")
            else:
                ds = str(d)[:10].replace("/", "-")
            bars.append({
                "date": ds,
                "open": float(r[col_map["open"]]),
                "high": float(r[col_map["high"]]),
                "low": float(r[col_map["low"]]),
                "close": float(r[col_map["close"]]),
                "volume": float(r[col_map["volume"]]) if "volume" in col_map else 0,
            })
        return bars[-count:] if bars else None
    except Exception as e:
        log.warning("ak stock kline %s: %s", code, e)
        return None


def ts_index_klines(count: int = 120) -> list[dict] | None:
    pro = _ts_pro()
    if pro is None:
        return None
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=int(count * 2))).strftime("%Y%m%d")
        df = pro.index_daily(ts_code="000001.SH", start_date=start, end_date=end)
        if df is None or df.empty:
            return None
        df = df.sort_values("trade_date")
        bars = []
        for _, r in df.iterrows():
            ds = str(r["trade_date"])
            if len(ds) == 8:
                ds = f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
            bars.append({
                "date": ds,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("vol") or 0),
            })
        return bars[-count:] if bars else None
    except Exception as e:
        log.warning("ts index kline: %s", e)
        return None


def ts_stock_klines(code: str, prefix: str, count: int = 90) -> list[dict] | None:
    pro = _ts_pro()
    if pro is None:
        return None
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=int(count * 2.2))).strftime("%Y%m%d")
        ts_code = _ts_code(code, prefix)
        # fund daily for ETF
        is_etf = code.startswith(("51", "52", "56", "58", "15", "16"))
        if is_etf:
            try:
                df = pro.fund_daily(ts_code=ts_code, start_date=start, end_date=end)
            except Exception:
                df = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
        else:
            df = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
        if df is None or df.empty:
            return None
        df = df.sort_values("trade_date")
        bars = []
        for _, r in df.iterrows():
            ds = str(r["trade_date"])
            if len(ds) == 8:
                ds = f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"
            bars.append({
                "date": ds,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("vol") or 0),
            })
        return bars[-count:] if bars else None
    except Exception as e:
        log.warning("ts stock kline %s: %s", code, e)
        return None


def ak_spot_quotes(limit: int = 80) -> list[dict] | None:
    """A-share spot list via Eastmoney through AkShare."""
    if not _HAS_AK:
        return None
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return None
        # 代码 名称 最新价 涨跌幅 成交额 ...
        out = []
        for _, r in df.iterrows():
            code = str(r.get("代码") or r.get("code") or "").zfill(6)
            try:
                price = float(r.get("最新价") or 0)
            except Exception:
                continue
            if price <= 0:
                continue
            try:
                chg = float(r.get("涨跌幅") or 0)
            except Exception:
                chg = 0
            try:
                amount = float(r.get("成交额") or 0)
            except Exception:
                amount = 0
            name = str(r.get("名称") or code)
            out.append({
                "code": code,
                "name": name,
                "price": price,
                "prevClose": price / (1 + chg / 100) if chg != -100 else price,
                "open": float(r.get("今开") or price),
                "high": float(r.get("最高") or price),
                "low": float(r.get("最低") or price),
                "change": round(price - (price / (1 + chg / 100) if chg != -100 else price), 2),
                "changePct": chg,
                "volume": float(r.get("成交量") or 0),
                "amount": amount,
                "turnover": float(r.get("换手率") or 0) if r.get("换手率") is not None else 0,
            })
        out.sort(key=lambda x: x["amount"], reverse=True)
        return out[: max(limit, 50)]
    except Exception as e:
        log.warning("ak spot: %s", e)
        return None
