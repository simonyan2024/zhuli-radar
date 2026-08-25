"""Radar scan funnel: regime → sectors → stocks → levels."""

from __future__ import annotations

import time
from datetime import datetime

from .analyze import analyze_index, analyze_stock, sector_relative_strength
from .market import (
    fetch_index_klines,
    fetch_index_quote,
    fetch_klines_batch,
    fetch_main_board_quotes,
    market_session,
    merge_live_bar,
    session_label,
    shanghai_date,
)

_scan_cache: dict | None = None
_scan_at = 0.0
SCAN_TTL = 18


def run_scan(force: bool = False, pool_size: int = 28) -> dict:
    global _scan_cache, _scan_at
    if not force and _scan_cache and time.time() - _scan_at < SCAN_TTL:
        return _scan_cache

    t0 = time.time()
    session = market_session()
    index_q = fetch_index_quote()
    index_bars = fetch_index_klines(120)
    index_meta = analyze_index(index_bars, index_q["price"])
    silent = bool(index_meta["silent"])

    quotes = fetch_main_board_quotes(100)[:pool_size]
    sectors = sector_relative_strength(quotes, index_q["changePct"])
    hot_sectors = [s for s in sectors[:8] if s["excessPct"] > 0.3 and not s["crowded"]]

    # Always compute stock features (even if silent — UI can hide active list)
    codes = [q["code"] for q in quotes]
    kmap = fetch_klines_batch(codes, 90, workers=14)

    echoes = []
    for q in quotes:
        bars = merge_live_bar(kmap.get(q["code"]) or [], q)
        if len(bars) < 5:
            continue
        analysis = analyze_stock(bars, index_bars, q, index_meta["regime"])
        echoes.append({
            "quote": q,
            "analysis": analysis,
            "hotSector": bool(set(q.get("industry") or []) & {s["industry"] for s in hot_sectors}),
        })

    # sort: level priority then force
    level_rank = {"可关注": 0, "观察": 1, "谨慎": 2, "回避": 3}
    echoes.sort(
        key=lambda x: (
            level_rank.get(x["analysis"]["level"], 9),
            -x["analysis"]["scores"]["force"],
        )
    )

    if silent:
        active = []
        note = "大盘处于弱势空头，雷达默认静默。仅展示环境与板块，不主动给出可关注列表。"
    else:
        active = [e for e in echoes if e["analysis"]["level"] in ("可关注", "观察")]
        note = "样本为沪深主板与ETF成交活跃标的（不含创业板）；盘中级别为临时结果，收盘后建议再确认。"

    payload = {
        "asOf": datetime.now().isoformat(timespec="seconds"),
        "asOfLabel": datetime.now().strftime("%H:%M:%S"),
        "date": shanghai_date(),
        "session": session,
        "sessionLabel": session_label(session),
        "elapsedMs": int((time.time() - t0) * 1000),
        "silent": silent,
        "note": note,
        "index": {
            **index_q,
            **index_meta,
            "bars": index_bars[-60:],
        },
        "sectors": sectors[:12],
        "hotSectors": hot_sectors[:6],
        "echoes": echoes,
        "active": active[:40],
        "stats": {
            "pool": len(quotes),
            "watch": sum(1 for e in echoes if e["analysis"]["level"] == "可关注"),
            "observe": sum(1 for e in echoes if e["analysis"]["level"] == "观察"),
            "caution": sum(1 for e in echoes if e["analysis"]["level"] == "谨慎"),
            "avoid": sum(1 for e in echoes if e["analysis"]["level"] == "回避"),
        },
    }
    _scan_cache = payload
    _scan_at = time.time()
    return payload


def analyze_code(code: str) -> dict:
    """Full single-stock radar analysis."""
    from .market import (
        fetch_stock_quote,
        fetch_klines,
        fetch_index_klines,
        fetch_index_quote,
        merge_live_bar,
        market_session,
        session_label,
        shanghai_date,
        normalize_code,
    )
    from .analyze import analyze_index, analyze_stock

    code = normalize_code(code)
    quote = fetch_stock_quote(code)
    index_q = fetch_index_quote()
    index_bars = fetch_index_klines(120)
    index_meta = analyze_index(index_bars, index_q["price"])
    bars = merge_live_bar(fetch_klines(code, 120), quote)
    analysis = analyze_stock(bars, index_bars, quote, index_meta["regime"])
    indicators = {}
    fund_flow = None
    data_source = "public"
    try:
        from .tdx_bridge import compute_tech_indicators, indicator_hints, tdx_fund_flow, easy_tdx_available
        indicators = compute_tech_indicators(bars)
        hints = indicator_hints(indicators, analysis.get("phase") or "")
        if hints:
            analysis.setdefault("evidence", []).extend(hints)
        if easy_tdx_available():
            data_source = "easy_tdx+public"
            fund_flow = tdx_fund_flow(code)
    except Exception:
        indicators = {}
    return {
        "ok": True,
        "asOf": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "date": shanghai_date(),
        "session": market_session(),
        "sessionLabel": session_label(market_session()),
        "quote": quote,
        "analysis": analysis,
        "indicators": indicators,
        "fundFlow": fund_flow,
        "dataSource": data_source,
        "index": {**index_q, **index_meta},
        "bars": bars[-60:],
        "note": "个股：量价阶段+相对上证为主；MACD/RSI/布林为辅助。有 easy-tdx 时优先通达信数据。仅研究参考。",
    }
