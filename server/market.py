"""Public market data: Shanghai index + main-board quotes/klines."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Any

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TZ = timezone(timedelta(hours=8))

# Core Shanghai main-board names (fallback / always include)
CORE_CODES = [
    "600519", "601318", "600036", "601166", "600900", "601899",
    "600276", "603259", "600030", "601398", "600887", "600309",
    "600406", "601888", "600000", "601288", "600028", "601857",
    "600104", "601601", "600016", "601328", "600050", "601668",
]

# Simple industry tags for demo auto-classification
INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "银行": ["银行"],
    "电力": ["电力", "水电", "火电", "电网", "能源"],
    "证券": ["证券", "信托"],
    "保险": ["保险", "人寿"],
    "白酒": ["茅台", "五粮", "汾酒", "泸州", "洋河", "古井"],
    "医药": ["医药", "生物", "制药", "药业", "医疗"],
    "半导体": ["芯片", "半导体", "集成电路", "微电", "硅"],
    "通信": ["通信", "光纤", "网络设备"],
    "汽车": ["汽车", "汽配", "轮胎"],
    "地产": ["地产", "置业", "房地产"],
    "煤炭": ["煤炭", "煤矿", "焦煤"],
    "有色": ["铜", "铝", "锌", "黄金", "有色", "矿业"],
    "石油": ["石油", "石化", "油气"],
    "军工": ["军工", "航发", "航天", "兵器"],
}

_cache: dict[str, Any] = {}
_CACHE_TTL = {
    "quotes": 20,
    "index": 10,
    "klines": 300,
    "scan": 20,
}


def _now() -> datetime:
    return datetime.now(TZ)


def shanghai_date() -> str:
    return _now().strftime("%Y-%m-%d")


def market_session() -> str:
    now = _now()
    if now.weekday() >= 5:
        return "closed"
    m = now.hour * 60 + now.minute
    if 9 * 60 + 15 <= m < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= m < 11 * 60 + 30:
        return "open"
    if 11 * 60 + 30 <= m < 13 * 60:
        return "lunch"
    if 13 * 60 <= m < 15 * 60:
        return "open"
    if 15 * 60 <= m < 15 * 60 + 30:
        return "post"
    return "closed"


def session_label(s: str) -> str:
    return {
        "pre": "竞价",
        "open": "盘中",
        "lunch": "午休",
        "post": "已收盘",
        "closed": "休市",
    }.get(s, s)


def is_sse_main(code: str) -> bool:
    c = code.replace("sh", "").replace("SH", "")
    return bool(re.match(r"^(600|601|603|605)\d{3}$", c))


def _get(url: str, timeout: float = 12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_text(url: str, encoding: str = "utf-8") -> str:
    raw = _get(url)
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="ignore")


def _cache_get(key: str, ttl: float):
    hit = _cache.get(key)
    if hit and time.time() - hit["at"] < ttl:
        return hit["value"]
    return None


def _cache_set(key: str, value: Any):
    _cache[key] = {"at": time.time(), "value": value}


def classify_industry(name: str) -> list[str]:
    tags = []
    for ind, kws in INDUSTRY_KEYWORDS.items():
        if any(k in name for k in kws):
            tags.append(ind)
    return tags or ["综合"]


def fetch_index_quote() -> dict:
    cached = _cache_get("index_quote", _CACHE_TTL["index"])
    if cached:
        return cached
    # Tencent batch
    text = _get_text("https://qt.gtimg.cn/q=sh000001", encoding="gbk")
    # v_sh000001="1~上证指数~000001~price~prev~open~..."
    m = re.search(r'="([^"]*)"', text)
    if not m:
        raise RuntimeError("上证指数行情不可用")
    p = m.group(1).split("~")
    price = float(p[3] or 0)
    prev = float(p[4] or 0)
    open_ = float(p[5] or 0)
    volume = float(p[6] or 0)
    high = float(p[33] or price) if len(p) > 33 else price
    low = float(p[34] or price) if len(p) > 34 else price
    change = price - prev
    change_pct = (change / prev * 100) if prev else 0
    q = {
        "code": "000001",
        "name": "上证指数",
        "price": price,
        "prevClose": prev,
        "open": open_,
        "high": high,
        "low": low,
        "change": round(change, 2),
        "changePct": round(change_pct, 2),
        "volume": volume,
        "amount": 0,
    }
    _cache_set("index_quote", q)
    return q


def fetch_index_klines(count: int = 120) -> list[dict]:
    cached = _cache_get(f"index_k_{count}", _CACHE_TTL["klines"])
    if cached:
        return cached
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,{count},qfq"
    data = json.loads(_get_text(url))
    pack = (data.get("data") or {}).get("sh000001") or {}
    rows = pack.get("qfqday") or pack.get("day") or []
    bars = []
    for r in rows:
        bars.append({
            "date": str(r[0]),
            "open": float(r[1]),
            "close": float(r[2]),
            "high": float(r[3]),
            "low": float(r[4]),
            "volume": float(r[5]) if len(r) > 5 else 0,
        })
    # merge live
    try:
        q = fetch_index_quote()
        today = shanghai_date()
        live = {
            "date": today,
            "open": q["open"] or q["price"],
            "high": q["high"] or q["price"],
            "low": q["low"] or q["price"],
            "close": q["price"],
            "volume": q["volume"],
        }
        if bars and bars[-1]["date"] >= today:
            bars[-1] = {**live, "date": bars[-1]["date"]}
        elif bars:
            bars.append(live)
    except Exception:
        pass
    _cache_set(f"index_k_{count}", bars)
    return bars


def fetch_main_board_quotes(limit: int = 80) -> list[dict]:
    cached = _cache_get(f"quotes_{limit}", _CACHE_TTL["quotes"])
    if cached:
        return cached
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"Market_Center.getHQNodeData?page=1&num={limit}&sort=amount&asc=0&node=sh_a"
    )
    rows = json.loads(_get_text(url))
    out: dict[str, dict] = {}
    for r in rows:
        code = str(r.get("code") or "").zfill(6)
        if not is_sse_main(code):
            continue
        name = r.get("name") or code
        price = float(r.get("trade") or 0)
        prev = float(r.get("settlement") or 0)
        out[code] = {
            "code": code,
            "name": name,
            "price": price,
            "prevClose": prev,
            "open": float(r.get("open") or 0),
            "high": float(r.get("high") or 0),
            "low": float(r.get("low") or 0),
            "change": float(r.get("pricechange") or 0),
            "changePct": float(r.get("changepercent") or 0),
            "volume": float(r.get("volume") or 0),
            "amount": float(r.get("amount") or 0),
            "turnover": float(r.get("turnoverratio") or 0),
            "industry": classify_industry(name),
        }
    # ensure core codes present via tencent if missing
    missing = [c for c in CORE_CODES if c not in out]
    if missing:
        for batch in [missing[i : i + 20] for i in range(0, len(missing), 20)]:
            q = ",".join(f"sh{c}" for c in batch)
            try:
                text = _get_text(f"https://qt.gtimg.cn/q={q}", encoding="gbk")
                for part in text.strip().split(";"):
                    if "=\"" not in part:
                        continue
                    body = part.split('="')[1].rstrip('"')
                    p = body.split("~")
                    if len(p) < 6:
                        continue
                    code = p[2]
                    if not is_sse_main(code):
                        continue
                    price = float(p[3] or 0)
                    prev = float(p[4] or 0)
                    name = p[1]
                    out[code] = {
                        "code": code,
                        "name": name,
                        "price": price,
                        "prevClose": prev,
                        "open": float(p[5] or 0),
                        "high": float(p[33] or price) if len(p) > 33 else price,
                        "low": float(p[34] or price) if len(p) > 34 else price,
                        "change": round(price - prev, 2),
                        "changePct": round((price - prev) / prev * 100, 2) if prev else 0,
                        "volume": float(p[6] or 0),
                        "amount": float(p[37] or 0) * 10000 if len(p) > 37 else 0,
                        "turnover": 0,
                        "industry": classify_industry(name),
                    }
            except Exception:
                continue
    ranked = sorted(out.values(), key=lambda x: x["amount"], reverse=True)
    _cache_set(f"quotes_{limit}", ranked)
    return ranked


def fetch_klines(code: str, count: int = 90) -> list[dict]:
    key = f"k_{code}_{count}"
    cached = _cache_get(key, _CACHE_TTL["klines"])
    if cached:
        return cached
    symbol = f"sh{code}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq"
    try:
        data = json.loads(_get_text(url))
        pack = (data.get("data") or {}).get(symbol) or {}
        rows = pack.get("qfqday") or pack.get("day") or []
        bars = []
        for r in rows:
            bars.append({
                "date": str(r[0]),
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]) * 100 if len(r) > 5 else 0,
            })
        if bars:
            _cache_set(key, bars)
            return bars
    except Exception:
        pass
    # sina fallback
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={count}"
    )
    rows = json.loads(_get_text(url))
    bars = [
        {
            "date": r["day"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
        }
        for r in rows
    ]
    _cache_set(key, bars)
    return bars


def merge_live_bar(bars: list[dict], quote: dict) -> list[dict]:
    if not bars or not quote.get("price"):
        return bars
    today = shanghai_date()
    live = {
        "date": today,
        "open": quote.get("open") or quote["price"],
        "high": quote.get("high") or quote["price"],
        "low": quote.get("low") or quote["price"],
        "close": quote["price"],
        "volume": quote.get("volume") or bars[-1]["volume"],
    }
    if bars[-1]["date"] >= today:
        return bars[:-1] + [{**live, "date": bars[-1]["date"]}]
    return bars + [live]


def fetch_klines_batch(codes: list[str], count: int = 90, workers: int = 12) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}

    def one(c: str):
        try:
            return c, fetch_klines(c, count)
        except Exception:
            return c, []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, c) for c in codes]
        for f in as_completed(futs):
            code, bars = f.result()
            result[code] = bars
    return result
