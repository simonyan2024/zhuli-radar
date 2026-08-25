"""FastAPI entry: radar API + static UI."""

from __future__ import annotations

import traceback
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="主力雷达", version="0.3.0")


def _lazy_scan():
    from .scan import run_scan, analyze_code
    return run_scan, analyze_code


def _lazy_backtest():
    from .backtest import run_backtest
    return run_backtest


def _lazy_market():
    from .market import fetch_index_quote, market_session, session_label, fetch_stock_quote, normalize_code
    return fetch_index_quote, market_session, session_label, fetch_stock_quote, normalize_code


@app.get("/api/health")
def health():
    try:
        _, market_session, session_label, _, _ = _lazy_market()
        try:
            from .tdx_bridge import easy_tdx_available
            tdx = easy_tdx_available()
        except Exception:
            tdx = False
        return {
            "ok": True,
            "session": session_label(market_session()),
            "static": STATIC.exists(),
            "version": "0.3.0",
            "easyTdx": tdx,
            "features": ["radar", "stock", "watch", "indicators", "backtest"],
        }
    except Exception as e:
        return {"ok": True, "session": "unknown", "warn": str(e), "version": "0.3.0"}


@app.get("/api/routes")
def list_routes():
    paths = sorted({getattr(r, "path", None) for r in app.routes if getattr(r, "path", None)})
    return {"ok": True, "paths": paths}


@app.get("/api/index")
def api_index():
    try:
        fetch_index_quote, market_session, session_label, _, _ = _lazy_market()
        q = fetch_index_quote()
        return {
            "ok": True,
            "session": market_session(),
            "sessionLabel": session_label(market_session()),
            "index": q,
        }
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)



@app.get("/api/diag")
def api_diag():
    """Data-source diagnostics for cloud deploy."""
    from .market import fetch_index_quote, fetch_main_board_quotes, fetch_klines
    info = {"ok": True, "steps": {}}
    try:
        q = fetch_index_quote()
        info["steps"]["index"] = {"ok": True, "price": q.get("price")}
    except Exception as e:
        info["steps"]["index"] = {"ok": False, "error": str(e)}
    try:
        qs = fetch_main_board_quotes(10)
        info["steps"]["quotes"] = {"ok": True, "n": len(qs), "sample": qs[0]["code"] if qs else None}
    except Exception as e:
        info["steps"]["quotes"] = {"ok": False, "error": str(e)}
    try:
        code = (info["steps"].get("quotes") or {}).get("sample") or "600519"
        bars = fetch_klines(code, 20)
        info["steps"]["kline"] = {"ok": bool(bars), "n": len(bars), "code": code}
    except Exception as e:
        info["steps"]["kline"] = {"ok": False, "error": str(e)}
    info["ok"] = all(v.get("ok") for v in info["steps"].values())
    return info


@app.get("/api/scan")
@app.get("/api/scan/")
def api_scan(force: bool = Query(False)):
    try:
        run_scan, _ = _lazy_scan()
        data = run_scan(force=force)
        return {"ok": True, **data}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/stock")
@app.get("/api/stock/")
def api_stock(code: str = Query(..., min_length=1, description="上证主板代码，如 600519")):
    try:
        _, analyze_code = _lazy_scan()
        data = analyze_code(code)
        return data
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/quote")
def api_quote(code: str = Query(..., min_length=1)):
    try:
        *_, fetch_stock_quote, normalize_code = _lazy_market()
        q = fetch_stock_quote(normalize_code(code))
        return {"ok": True, "quote": q}
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/backtest")
@app.get("/api/backtest/")
def api_backtest(
    levels: str = Query("可关注"),
    max_hold: int = Query(8, ge=1, le=20),
):
    try:
        run_backtest = _lazy_backtest()
        allow = [x.strip() for x in levels.split(",") if x.strip()]
        data = run_backtest(levels_allow=allow, max_hold=max_hold)
        return data
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/")
def index_page():
    index = STATIC / "index.html"
    if not index.exists():
        return PlainTextResponse(
            "index.html missing. Check that static/index.html was uploaded to the repo.",
            status_code=500,
        )
    return FileResponse(index)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        {
            "ok": False,
            "error": "Not Found",
            "path": str(request.url.path),
            "hint": "Try /api/health /api/scan /api/stock?code=600519",
        },
        status_code=404,
    )


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
