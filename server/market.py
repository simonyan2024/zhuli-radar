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
    # 上证主板
    "600519", "601318", "600036", "601166", "600900", "601899",
    "600276", "603259", "600030", "601398", "600887", "600309",
    "600406", "601888", "600000", "601288", "600028", "601857",
    "600104", "601601", "600016", "601328", "600050", "601668",
    "600031", "600048", "600111", "600150", "600690", "600809",
    "601012", "601088", "601628", "601633", "601728", "601766",
    "601985", "603288", "603501", "603799",
    # 深市主板（非创业板）
    "000001", "000002", "000063", "000100", "000157", "000166",
    "000333", "000338", "000425", "000538", "000568", "000625",
    "000651", "000725", "000768", "000776", "000858", "000895",
    "000938", "000977", "001979", "002001", "002027", "002142",
    "002230", "002241", "002352", "002415", "002475", "002594",
    "002714", "002736",
    # 常见 ETF
    "510050", "510300", "510500", "510880", "512000", "512100",
    "512480", "512660", "512690", "512760", "512880", "512980",
    "513050", "513100", "513180", "513500", "515790", "516160",
    "518880", "588000", "588080", "159915", "159919", "159922",
    "159925", "159941", "159995",
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
    "ETF": ["ETF", "基金"],
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


def normalize_code(raw: str) -> str:
    s = (raw or "").strip().upper()
    s = s.replace("SH", "").replace("SZ", "").replace(".", "")
    s = "".join(ch for ch in s if ch.isdigit())
    if len(s) > 6:
        s = s[-6:]
    return s.zfill(6) if s else ""


def market_prefix(code: str) -> str:
    c = normalize_code(code)
    if c.startswith(("5", "6")):
        return "sh"
    if c.startswith(("0", "1", "2", "3")):
        return "sz"
    return "sh"


def is_chinext(code: str) -> bool:
    c = normalize_code(code)
    return c.startswith(("300", "301"))


def is_etf(code: str) -> bool:
    c = normalize_code(code)
    return bool(re.match(r"^(51|52|56|58)\d{4}$", c) or re.match(r"^(15|16)\d{4}$", c))


def is_sh_main(code: str) -> bool:
    c = normalize_code(code)
    return bool(re.match(r"^(600|601|603|605)\d{3}$", c))


def is_sz_main(code: str) -> bool:
    c = normalize_code(code)
    if is_chinext(c):
        return False
    return bool(re.match(r"^(000|001|002)\d{3}$", c))


def is_allowed_symbol(code: str) -> bool:
    c = normalize_code(code)
    if not c or is_chinext(c):
        return False
    return is_sh_main(c) or is_sz_main(c) or is_etf(c)


def is_sse_main(code: str) -> bool:
    return is_allowed_symbol(code)



def _get(url: str, timeout: float = 12, referer: str | None = None) -> bytes:
    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Connection": "close",
    }
    if referer:
        headers["Referer"] = referer
    elif "sina" in url:
        headers["Referer"] = "https://finance.sina.com.cn/"
    elif "gtimg" in url or "qq.com" in url:
        headers["Referer"] = "https://finance.qq.com/"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_text(url: str, encoding: str = "utf-8", referer: str | None = None) -> str:
    raw = _get(url, referer=referer)
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="ignore")


def _get_text_any(urls: list[tuple[str, str]], encoding: str = "utf-8") -> str:
    """Try (url, referer) pairs; raise last error."""
    last = None
    for url, ref in urls:
        try:
            return _get_text(url, encoding=encoding, referer=ref)
        except Exception as e:
            last = e
            continue
    raise last or RuntimeError("all sources failed")


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
    # Prefer easy_tdx when available
    try:
        from .tdx_bridge import tdx_index_klines
        tb = tdx_index_klines(count)
        if tb and len(tb) >= 20:
            _cache_set(f"index_k_{count}", tb)
            return tb
    except Exception:
        pass

    bars: list[dict] = []
    # 1) Tencent
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,{count},qfq"
        data = json.loads(_get_text(url, referer="https://finance.qq.com/"))
        pack = (data.get("data") or {}).get("sh000001") or {}
        rows = pack.get("qfqday") or pack.get("day") or []
        for r in rows:
            bars.append({
                "date": str(r[0]),
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]) if len(r) > 5 else 0,
            })
    except Exception:
        bars = []

    # 2) Sohu fallback
    if len(bars) < 20:
        try:
            from datetime import datetime, timedelta
            end_d = datetime.now().strftime("%Y%m%d")
            start_d = (datetime.now() - timedelta(days=int(count * 1.8))).strftime("%Y%m%d")
            url = f"https://q.stock.sohu.com/hisHq?code=zs_000001&start={start_d}&end={end_d}&stat=1&order=A"
            data = json.loads(_get_text(url))
            rows = (data[0].get("hq") if data else None) or []
            bars = []
            for r in rows:
                # date, open, close, change, pct, low, high, vol, amount, turnover
                bars.append({
                    "date": str(r[0]).replace("/", "-") if "/" in str(r[0]) else str(r[0]),
                    "open": float(r[1]),
                    "close": float(r[2]),
                    "low": float(r[5]),
                    "high": float(r[6]),
                    "volume": float(r[7]) if len(r) > 7 else 0,
                })
        except Exception:
            pass

    if not bars:
        # 3) synthesize minimal from live quote so scan can continue
        try:
            q = fetch_index_quote()
            px = float(q["price"] or 0)
            bars = [{"date": shanghai_date(), "open": px, "high": px, "low": px, "close": px, "volume": 0}] * 30
            bars = [dict(b, date=shanghai_date()) for b in bars]  # same day bad for analysis but avoids crash
            # better: flat series with tiny noise dates
            bars = []
            from datetime import datetime, timedelta
            for i in range(60):
                d = (datetime.now() - timedelta(days=60 - i)).strftime("%Y-%m-%d")
                bars.append({"date": d, "open": px, "high": px, "low": px, "close": px, "volume": 0})
        except Exception as e:
            raise RuntimeError(f"指数K线不可用: {e}")

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


def _parse_tencent_quotes(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for part in text.strip().split(";"):
        if '="' not in part:
            continue
        body = part.split('="')[1].rstrip('"')
        p = body.split("~")
        if len(p) < 6:
            continue
        code = (p[2] or "").zfill(6)
        if not is_sse_main(code):
            continue
        price = float(p[3] or 0)
        prev = float(p[4] or 0)
        if price <= 0:
            continue
        name = p[1] or code
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
            "turnover": float(p[38] or 0) if len(p) > 38 else 0,
            "industry": classify_industry(name),
        }
    return out


def fetch_quotes_tencent(codes: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(codes), 40):
        batch = codes[i : i + 40]
        q = ",".join(f"{market_prefix(c)}{c}" for c in batch)
        try:
            text = _get_text(
                f"https://qt.gtimg.cn/q={q}",
                encoding="gbk",
                referer="https://finance.qq.com/",
            )
            out.update(_parse_tencent_quotes(text))
        except Exception:
            # secondary host
            try:
                text = _get_text(
                    f"https://qt.gtimg.cn/q={q}",
                    encoding="gbk",
                    referer=None,
                )
                out.update(_parse_tencent_quotes(text))
            except Exception:
                continue
    return out


def fetch_main_board_quotes(limit: int = 80) -> list[dict]:
    """Liquid pool: Sina amount-rank when possible, else Tencent core list."""
    cached = _cache_get(f"quotes_{limit}", _CACHE_TTL["quotes"])
    if cached:
        return cached
    out: dict[str, dict] = {}

    # 1) Sina ranked list (often blocked overseas with 501)
    try:
        rows = []
        for node in ("sh_a", "sz_a"):
            try:
                url = (
                    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                    f"Market_Center.getHQNodeData?page=1&num={max(limit // 2, 30)}&sort=amount&asc=0&node={node}"
                )
                part = json.loads(_get_text(url, referer="https://finance.sina.com.cn/"))
                if isinstance(part, list):
                    rows.extend(part)
            except Exception:
                continue
        for r in rows:
            code = str(r.get("code") or "").zfill(6)
            if not is_allowed_symbol(code):
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
    except Exception:
        out = {}

    # 2) Always merge Tencent core quotes (works on more hosts)
    codes = list(dict.fromkeys(CORE_CODES + list(out.keys())))[: max(limit, 48)]
    tq = fetch_quotes_tencent(codes)
    for code, q in tq.items():
        if code not in out or (out[code].get("price") or 0) <= 0:
            out[code] = q
        else:
            # keep sina amount if present, refresh price from tencent
            out[code] = {**out[code], **{k: q[k] for k in ("price", "change", "changePct", "high", "low", "open", "volume") if q.get(k) is not None}}

    if not out:
        # last resort: tencent only on core
        out = fetch_quotes_tencent(CORE_CODES)

    ranked = sorted(out.values(), key=lambda x: x.get("amount") or 0, reverse=True)
    if not ranked:
        raise RuntimeError("主板行情不可用（公开源均失败，请稍后重试）")
    _cache_set(f"quotes_{limit}", ranked)
    return ranked



def fetch_klines(code: str, count: int = 90) -> list[dict]:
    key = f"k_{code}_{count}"
    cached = _cache_get(key, _CACHE_TTL["klines"])
    if cached:
        return cached
    try:
        from .tdx_bridge import tdx_stock_klines
        tb = tdx_stock_klines(code, count)
        if tb and len(tb) >= 15:
            _cache_set(key, tb)
            return tb
    except Exception:
        pass
    symbol = f"{market_prefix(code)}{code}"
    bars: list[dict] = []
    # tencent
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{count},qfq"
        data = json.loads(_get_text(url, referer="https://finance.qq.com/"))
        pack = (data.get("data") or {}).get(symbol) or {}
        rows = pack.get("qfqday") or pack.get("day") or []
        for r in rows:
            bars.append({
                "date": str(r[0]),
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]) * 100 if len(r) > 5 else 0,
            })
    except Exception:
        bars = []
    # sina
    if len(bars) < 10:
        try:
            url = (
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={count}"
            )
            rows = json.loads(_get_text(url, referer="https://finance.sina.com.cn/"))
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
        except Exception:
            pass
    if bars:
        _cache_set(key, bars)
    return bars  # may be empty — caller skips


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


def fetch_stock_quote(code: str) -> dict:
    """Single SSE main-board quote: TDX first, then Tencent."""
    code = normalize_code(code)
    if not code:
        raise ValueError("请输入股票代码")
    if not is_sse_main(code):
        raise ValueError("支持上证/深市主板与ETF；不支持创业板(300/301)")
    try:
        from .tdx_bridge import tdx_stock_quote
        tq = tdx_stock_quote(code)
        if tq and tq.get("price"):
            if not tq.get("industry"):
                tq["industry"] = classify_industry(tq.get("name") or code)
            return tq
    except Exception:
        pass
    text = _get_text(f"https://qt.gtimg.cn/q={market_prefix(code)}{code}", encoding="gbk")
    m = __import__("re").search(r'="([^"]*)"', text)
    if not m or not m.group(1) or m.group(1) == "1":
        raise RuntimeError(f"未找到股票 {code}")
    p = m.group(1).split("~")
    if len(p) < 6 or not p[1]:
        raise RuntimeError(f"未找到股票 {code}")
    price = float(p[3] or 0)
    prev = float(p[4] or 0)
    name = p[1]
    return {
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
        "turnover": float(p[38] or 0) if len(p) > 38 else 0,
        "industry": classify_industry(name),
    }
