"""Regime, phase, tactics, relative strength — rule-friendly features."""

from __future__ import annotations

from typing import Any


def sma(vals: list[float], n: int, i: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(vals[i - n + 1 : i + 1]) / n


def ret(closes: list[float], i: int, n: int) -> float | None:
    if i < n or not closes[i - n]:
        return None
    return closes[i] / closes[i - n] - 1


def range_pos(bars: list[dict], i: int, n: int) -> float:
    window = bars[max(0, i - n + 1) : i + 1]
    hi = max(b["high"] for b in window)
    lo = min(b["low"] for b in window)
    if hi == lo:
        return 0.5
    return (bars[i]["close"] - lo) / (hi - lo)


def shadow_parts(bar: dict) -> dict:
    span = max(bar["high"] - bar["low"], 1e-9)
    body_top = max(bar["open"], bar["close"])
    body_bot = min(bar["open"], bar["close"])
    return {
        "body": abs(bar["close"] - bar["open"]) / span,
        "upper": (bar["high"] - body_top) / span,
        "lower": (body_bot - bar["low"]) / span,
        "closeLoc": (bar["close"] - bar["low"]) / span,
    }


def analyze_index(bars: list[dict], price: float) -> dict:
    if len(bars) < 25:
        return {
            "regime": "震荡",
            "regimeDetail": "样本不足",
            "ma20": 0,
            "ma60": 0,
            "ret5": 0,
            "ret20": 0,
            "silent": False,
        }
    closes = [b["close"] for b in bars]
    i = len(closes) - 1
    ma20 = sma(closes, 20, i) or price
    ma60 = sma(closes, 60, i) or ma20
    r5 = ret(closes, i, 5) or 0
    r20 = ret(closes, i, 20) or 0
    ma20_prev = sma(closes, 20, max(20, i - 5)) or ma20
    slope = (ma20 / ma20_prev - 1) if ma20_prev else 0

    if price > ma20 > ma60 and slope > 0.004 and r20 > 0.03:
        regime = "强势多头"
    elif price > ma20 and r20 > 0:
        regime = "偏多震荡"
    elif price < ma20 < ma60 and slope < -0.004 and r20 < -0.03:
        regime = "弱势空头"
    elif price < ma20:
        regime = "偏空震荡"
    else:
        regime = "震荡"

    silent = regime in ("弱势空头",)
    hints = {
        "强势多头": "趋势向上，允许主动扫描进攻型标的。",
        "偏多震荡": "偏多但斜率一般，优先质量与相对强度。",
        "震荡": "方向不明，缩短列表、提高过滤。",
        "偏空震荡": "偏弱，默认谨慎；少追拉升。",
        "弱势空头": "空头环境，雷达默认静默（可在规则中关闭）。",
    }
    detail = (
        f"近5日{r5*100:+.1f}%，近20日{r20*100:+.1f}%，"
        f"价格在20日均线{'上方' if price > ma20 else '下方'}。"
        f"{hints[regime]}"
    )
    return {
        "regime": regime,
        "regimeDetail": detail,
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "ret5": round(r5, 4),
        "ret20": round(r20, 4),
        "silent": silent,
    }


def _align(a: list[dict], b: list[dict]) -> tuple[list[dict], list[dict]]:
    mp = {x["date"]: x for x in b}
    left, right = [], []
    for x in a:
        y = mp.get(x["date"])
        if y:
            left.append(x)
            right.append(y)
    return left, right


def analyze_stock(bars: list[dict], index_bars: list[dict], quote: dict, regime: str) -> dict:
    # 少於 12 根：无法分析；12～24 根：降级分析（标注 sample=partial）
    if len(bars) < 12:
        return {
            "phase": "横盘",
            "phaseConfidence": 20,
            "mind": "样本不足",
            "tactics": [],
            "vsIndex": "独立",
            "vsIndexDetail": f"仅{len(bars)}根K线",
            "level": "观察",
            "levelReason": "行情源返回K线过少，请稍后重试或换网络环境。",
            "buyAdvice": {
                "action": "暂不评估",
                "strength": "无",
                "summary": "K线条数不足，暂停买入评估。",
                "reasons": [f"当前仅{len(bars)}根日K（需至少约12根才能做降级判断）。"],
                "risks": ["多半是公开行情源限流/海外访问失败，不是股票本身无数据。"],
                "plan": "稍后重新分析；国内网络或本机部署通常可拉满K线。",
            },
            "scores": {"force": 15, "quality": 15, "risk": 60},
            "evidence": [f"有效交易日{len(bars)}，低于最低门槛"],
            "sample": "short",
        }

    s_bars, i_bars = _align(bars, index_bars)
    if len(s_bars) < 25:
        s_bars, i_bars = bars, index_bars

    i = len(s_bars) - 1
    closes = [b["close"] for b in s_bars]
    vols = [b["volume"] for b in s_bars]
    last = s_bars[i]
    prev = s_bars[i - 1]
    ma5 = sma(closes, 5, i) or last["close"]
    ma10 = sma(closes, 10, i) or ma5
    ma20 = sma(closes, 20, i) or ma10
    ma60 = sma(closes, 60, i) or ma20
    vol_ma = sma(vols, 20, i) or last["volume"] or 1
    vol_ratio = last["volume"] / vol_ma if vol_ma else 1
    pos60 = range_pos(s_bars, i, min(60, len(s_bars)))
    r1 = last["close"] / prev["close"] - 1 if prev["close"] else 0
    r5 = ret(closes, i, 5) or 0
    r20 = ret(closes, i, 20) or 0

    window = s_bars[max(0, i - 9) : i + 1]
    up_vol = sum(b["volume"] for b in window if b["close"] >= b["open"])
    down_vol = sum(b["volume"] for b in window if b["close"] < b["open"])
    upper_bias = sum(shadow_parts(b)["upper"] for b in window) / len(window)
    lower_bias = sum(shadow_parts(b)["lower"] for b in window) / len(window)

    # residual vs index
    s_ret = [
        s_bars[k]["close"] / s_bars[k - 1]["close"] - 1
        for k in range(1, len(s_bars))
    ]
    i_ret = [
        i_bars[k]["close"] / i_bars[k - 1]["close"] - 1
        for k in range(1, min(len(i_bars), len(s_bars)))
    ]
    n = min(20, len(s_ret), len(i_ret))
    resid20 = sum(s_ret[-n + k] - i_ret[-n + k] for k in range(n)) if n else 0
    resist_list = [
        s_ret[-n + k] - i_ret[-n + k]
        for k in range(n)
        if i_ret[-n + k] < -0.004
    ]
    resist = sum(resist_list) / len(resist_list) if resist_list else 0
    index_ret5 = ret([b["close"] for b in i_bars], len(i_bars) - 1, 5) or 0

    vol_stall = vol_ratio > 1.7 and abs(r1) < 0.012
    ma_bull = ma5 > ma10 > ma20 and last["close"] > ma20
    ma_bear = ma5 < ma10 < ma20 and last["close"] < ma20

    scores = {
        "吸筹": (1 - pos60) * 1.3
        + (0.5 if vol_ratio < 0.95 else 0)
        + (0.5 if lower_bias > upper_bias else 0)
        + (1.0 if resid20 > 0 and index_ret5 < 0 else 0)
        + (0.7 if resist > 0.004 else 0)
        - (1.2 if pos60 > 0.72 else 0),
        "洗盘": (
            (1.1 if 0.035 < (max(b["high"] for b in s_bars[max(0, i - 5) : i + 1]) - last["close"])
             / max(max(b["high"] for b in s_bars[max(0, i - 5) : i + 1]), 1e-9) < 0.13 else 0)
            + (0.7 if last["close"] > ma60 else 0)
            + (0.5 if lower_bias > 0.2 else 0)
        ),
        "拉升": (1.2 if ma_bull else 0)
        + (0.5 if pos60 > 0.62 else 0)
        + (0.7 if up_vol > down_vol * 1.05 else 0)
        + (0.8 if resid20 > 0.02 else 0)
        + (0.5 if r5 > 0.025 else 0)
        - (0.9 if vol_stall else 0),
        "出货": (0.8 if pos60 > 0.7 else 0)
        + (1.4 if vol_stall else 0)
        + (0.7 if upper_bias > 0.24 else 0)
        + (0.8 if down_vol > up_vol * 1.08 else 0)
        + (0.7 if resid20 < 0 and pos60 > 0.58 else 0),
        "下跌": (1.2 if ma_bear else 0)
        + (0.8 if pos60 < 0.35 else 0)
        + (0.8 if r20 < -0.08 else 0),
        "横盘": (1.2 if (max(b["high"] for b in s_bars[max(0, i - 19) : i + 1])
                        - min(b["low"] for b in s_bars[max(0, i - 19) : i + 1]))
                       / last["close"] < 0.08 else 0)
        + (0.5 if abs(r20) < 0.045 else 0),
    }
    phase = max(scores, key=scores.get)
    conf = min(95, max(40, 48 + (scores[phase] - sorted(scores.values())[-2]) * 18))

    # vs index
    if index_ret5 < -0.008 and resist > 0.006:
        vs, vs_d = "抗跌", f"大盘近5日偏弱时，该股下跌日平均超额{resist*100:.1f}%。"
    elif resid20 > 0.025:
        vs, vs_d = "领涨", f"近20日相对上证超额{resid20*100:.1f}%。"
    elif index_ret5 > 0.008 and resid20 < -0.01:
        vs, vs_d = "滞涨", "指数上行时跟不上，需防高位轮动离开。"
    elif resid20 < -0.025 and index_ret5 < 0:
        vs, vs_d = "领跌", "弱市中更弱，主动减仓特征。"
    elif index_ret5 < 0:
        vs, vs_d = "跟跌", "大体跟随指数回落。"
    else:
        vs, vs_d = "跟涨", f"跟随指数，超额{resid20*100:.1f}%。"

    tactics = []
    sh = shadow_parts(last)
    if vol_ratio > 1.8 and sh["body"] < 0.28:
        tactics.append({"name": "对倒放量", "side": "中", "evidence": f"量比{vol_ratio:.2f}但实体偏小。"})
    if vol_stall:
        tactics.append({"name": "放量滞涨", "side": "空", "evidence": "量能放大价格停滞。"})
    if sh["closeLoc"] > 0.82 and last["close"] > last["open"] and r1 > 0.012:
        tactics.append({"name": "尾盘拉升", "side": "多", "evidence": "收盘靠近最高价。"})
    if r1 <= -0.02 and sh["lower"] > 0.35 and sh["closeLoc"] > 0.55:
        tactics.append({"name": "打压吸筹", "side": "多", "evidence": "下跌但长下影收回。"})
    if pos60 > 0.7 and r1 > 0 and vol_ratio < 0.85:
        tactics.append({"name": "缩量上涨", "side": "多", "evidence": "高位涨而量缩，或为控盘。"})
    if sh["upper"] > 0.4 and last["close"] <= last["open"]:
        tactics.append({"name": "长上影压盘", "side": "空", "evidence": "上方卖压明显。"})

    # mind
    if phase == "吸筹" and vs == "抗跌":
        mind = "逆势吸筹"
    elif phase == "吸筹":
        mind = "低位吸筹"
    elif phase == "洗盘":
        mind = "清洗浮筹"
    elif phase == "拉升" and vol_ratio < 0.9 and r5 > 0:
        mind = "强势控盘"
    elif phase == "拉升":
        mind = "主升推进"
    elif phase == "出货" and vol_stall:
        mind = "诱多派发"
    elif phase == "出货":
        mind = "高位派发"
    elif phase == "下跌":
        mind = "弃庄离场"
    else:
        mind = "观望待变"

    # level
    weak = regime in ("弱势空头", "偏空震荡")
    strong = regime in ("强势多头", "偏多震荡")
    bad_tactics = {t["name"] for t in tactics} & {"放量滞涨", "长上影压盘", "对倒放量"}

    if phase in ("出货", "下跌") or (vol_stall and pos60 > 0.65):
        level, reason = "回避", f"{phase}或高位量价背离，优先不参与。"
    elif weak and phase == "拉升":
        level, reason = "谨慎", "大盘偏弱时的拉升，更像反弹，不追高。"
    elif phase == "拉升" and pos60 > 0.88:
        level, reason = "谨慎", "主升但位置过伸，等待回踩更合适。"
    elif phase == "拉升" and strong and vs not in ("滞涨", "领跌") and "放量滞涨" not in bad_tactics:
        level, reason = "可关注", f"大盘{regime}且个股主升、相对不弱。"
    elif phase in ("吸筹", "洗盘") and vs in ("抗跌", "领涨", "独立", "跟涨") and not weak:
        level, reason = "可关注", f"{phase}且相对大盘不差，适合观察低吸而非追涨。"
    elif phase in ("吸筹", "洗盘") and vs == "抗跌":
        level, reason = "观察", "逆势抗跌值得盯，大盘未稳前不加仓。"
    elif bad_tactics:
        level, reason = "谨慎", "出现" + "、".join(bad_tactics) + "。"
    else:
        level, reason = "观察", f"阶段{phase}，等待价量确认。"

    evidence = [
        f"60日位置{pos60*100:.0f}%，近5日{r5*100:+.1f}%，近20日{r20*100:+.1f}%。",
        f"量比{vol_ratio:.2f}，相对上证20日超额{resid20*100:+.1f}%。",
        vs_d,
    ]

    # --- 买入建议（研究用，非投资承诺）---
    buy_reasons = []
    buy_risks = []
    if regime == "弱势空头":
        buy_risks.append("大盘弱势空头，雷达默认不开主动买入建议。")
    elif weak:
        buy_risks.append(f"大盘处于{regime}，系统性风险偏高。")
    else:
        buy_reasons.append(f"大盘环境为「{regime}」，未触发空头静默。")

    if phase in ("吸筹", "洗盘") and not weak:
        buy_reasons.append(f"量价阶段判为「{phase}」（置信约{round(conf)}%），偏左侧/中继结构。")
    if phase == "拉升" and strong and pos60 <= 0.88:
        buy_reasons.append(f"主升阶段且位置未极端过伸（60日分位{pos60*100:.0f}%）。")
    if vs in ("抗跌", "领涨"):
        buy_reasons.append(f"相对上证表现：{vs}。{vs_d}")
    if mind in ("逆势吸筹", "低位吸筹", "清洗浮筹", "强势控盘"):
        buy_reasons.append(f"主力语义标签：{mind}。")
    for tac in tactics:
        if tac.get("side") == "多":
            buy_reasons.append(f"多头手法「{tac['name']}」：{tac.get('evidence','')}")
        elif tac.get("side") == "空":
            buy_risks.append(f"空头手法「{tac['name']}」：{tac.get('evidence','')}")

    if phase in ("出货", "下跌"):
        buy_risks.append(f"阶段为「{phase}」，不支持买入叙事。")
    if vol_stall and pos60 > 0.6:
        buy_risks.append("高位放量滞涨，量价背离风险。")
    if pos60 > 0.88:
        buy_risks.append("60日位置过高，追高盈亏比差。")
    if bad_tactics:
        buy_risks.append("出现警示手法：" + "、".join(sorted(bad_tactics)) + "。")

    # action mapping from level + regime
    if regime == "弱势空头" or level == "回避":
        action, strength = "不建议买入", "无"
        plan = "优先回避或观望；若持仓以风控为主，不新增仓。"
        summary = reason
    elif level == "谨慎":
        action, strength = "暂不买入", "弱"
        plan = "等待大盘转稳或个股回踩确认后再评估；不追涨。"
        summary = reason
    elif level == "观察":
        action, strength = "观望（可记入观察池）", "弱"
        plan = "放入观察列表，等待价量或大盘出现确认信号，不急于买入。"
        summary = reason
    elif level == "可关注":
        if phase in ("吸筹", "洗盘"):
            action, strength = "可考虑分批低吸（研究建议）", "中"
            plan = "仅小仓试错思路：回踩支撑/缩量企稳再看，不一次性重仓；严格止损与T+1约束。"
        elif phase == "拉升":
            action, strength = "可关注回踩再介入（研究建议）", "中"
            plan = "不建议猛追涨停式打法；优先等短线回踩均线或缩量整理后再评估。"
        else:
            action, strength = "可关注", "中"
            plan = "结合自身风险承受力，小仓位研究性参与，预设退出条件。"
        summary = reason
        if not buy_reasons:
            buy_reasons.append(level + "：" + reason)
    else:
        action, strength = "观望", "无"
        plan = "维持观察。"
        summary = reason

    if not buy_reasons and action.startswith("可"):
        buy_reasons.append(summary)
    if not buy_risks:
        buy_risks.append("公开数据延迟、模型误判、黑天鹅与涨跌停无法预知。")
    buy_risks.append("本结论为规则研究输出，不构成投资建议；A股T+1，亏损可能。")

    buy_advice = {
        "action": action,
        "strength": strength,
        "summary": summary,
        "reasons": buy_reasons[:8],
        "risks": buy_risks[:8],
        "plan": plan,
    }

    force = min(95, max(15, conf * 0.5 + (18 if phase in ("拉升", "吸筹") else 0) + min(15, abs(resid20) * 200)))
    quality = min(95, max(15, 40 + (15 if phase in ("吸筹", "洗盘", "拉升") else 0) - (20 if vol_stall else 0)))
    risk = min(95, max(15, 30 + (25 if phase in ("出货", "下跌") else 0) + (12 if weak else 0) + (10 if pos60 > 0.9 else 0)))

    return {
        "phase": phase,
        "phaseConfidence": round(conf),
        "mind": mind,
        "tactics": tactics[:5],
        "vsIndex": vs,
        "vsIndexDetail": vs_d,
        "level": level,
        "levelReason": reason,
        "buyAdvice": buy_advice,
        "scores": {"force": round(force), "quality": round(quality), "risk": round(risk)},
        "evidence": evidence + ([f"K线仅{len(s_bars)}根，结论为降级分析"] if len(s_bars) < 25 else []),
        "sample": "partial" if len(s_bars) < 25 else "ok",
        "features": {
            "pos60": round(pos60, 3),
            "volRatio": round(vol_ratio, 2),
            "resid20": round(resid20, 4),
            "r5": round(r5, 4),
            "r20": round(r20, 4),
        },
    }


def sector_relative_strength(quotes: list[dict], index_change_pct: float) -> list[dict]:
    """Aggregate by industry tag using today's change as proxy for rotation."""
    buckets: dict[str, list[dict]] = {}
    for q in quotes:
        for ind in q.get("industry") or ["综合"]:
            buckets.setdefault(ind, []).append(q)
    rows = []
    for ind, items in buckets.items():
        if len(items) < 2:
            continue
        avg_pct = sum(x["changePct"] for x in items) / len(items)
        up = sum(1 for x in items if x["changePct"] > 0.05)
        breadth = up / len(items)
        excess = avg_pct - index_change_pct
        amount = sum(x["amount"] for x in items)
        # crowding: high average pct + high breadth
        crowded = avg_pct > 4 and breadth > 0.7
        strength = excess + breadth * 2
        rows.append({
            "industry": ind,
            "count": len(items),
            "avgChangePct": round(avg_pct, 2),
            "excessPct": round(excess, 2),
            "breadth": round(breadth, 2),
            "amount": amount,
            "crowded": crowded,
            "strength": round(strength, 2),
        })
    rows.sort(key=lambda x: x["strength"], reverse=True)
    return rows
