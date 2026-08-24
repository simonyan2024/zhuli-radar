"""FastAPI entry: radar API + static UI."""

from __future__ import annotations

import traceback
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .backtest import run_backtest
from .market import fetch_index_quote, market_session, session_label
from .scan import run_scan

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="主力鉴雷达", version="0.1.0")


@app.get("/api/health")
def health():
    return {"ok": True, "session": session_label(market_session())}


@app.get("/api/index")
def api_index():
    try:
        q = fetch_index_quote()
        return {"ok": True, "session": market_session(), "sessionLabel": session_label(market_session()), "index": q}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/scan")
def api_scan(force: bool = Query(False)):
    try:
        data = run_scan(force=force)
        return {"ok": True, **data}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/backtest")
def api_backtest(
    levels: str = Query("可关注"),
    max_hold: int = Query(8, ge=1, le=20),
):
    try:
        allow = [x.strip() for x in levels.split(",") if x.strip()]
        data = run_backtest(levels_allow=allow, max_hold=max_hold)
        return data
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/")
def index_page():
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
