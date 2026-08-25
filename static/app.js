/* 主力雷达 client v0.2 — scan + stock + watchlist */

const REFRESH_MS = 25000;
const WATCH_KEY = "zhuli_watch_v1";
let scanData = null;
let levelFilter = "全部";
let timer = null;
let currentStock = null;

const $ = (id) => document.getElementById(id);

function pctClass(n) {
  if (n > 0.0005) return "up";
  if (n < -0.0005) return "down";
  return "muted";
}
function fmtPct(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return (n > 0 ? "+" : "") + Number(n).toFixed(2) + "%";
}
function fmtPrice(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtYi(n) {
  if (!n) return "—";
  if (n >= 1e8) return (n / 1e8).toFixed(1) + "亿";
  if (n >= 1e4) return (n / 1e4).toFixed(0) + "万";
  return String(Math.round(n));
}
function levelTone(level) {
  if (level === "可关注") return "up";
  if (level === "回避") return "down";
  if (level === "谨慎") return "warn";
  return "";
}

function getWatch() {
  try {
    return JSON.parse(localStorage.getItem(WATCH_KEY) || "[]");
  } catch {
    return [];
  }
}
function setWatch(list) {
  localStorage.setItem(WATCH_KEY, JSON.stringify(list));
}
function isWatched(code) {
  return getWatch().some((x) => x.code === code);
}
function toggleWatch(code, name) {
  let list = getWatch();
  if (list.some((x) => x.code === code)) {
    list = list.filter((x) => x.code !== code);
  } else {
    list.unshift({ code, name: name || code, addedAt: Date.now() });
  }
  setWatch(list);
  updateWatchBtn();
  renderWatchList();
}

function updateWatchBtn() {
  const btn = $("btnWatchToggle");
  if (!btn) return;
  if (!currentStock) {
    btn.textContent = "加入自选";
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
  btn.textContent = isWatched(currentStock.code) ? "取消自选" : "加入自选";
}

function drawSpark(svgId, bars) {
  const svg = $(svgId);
  if (!svg) return;
  if (!bars || bars.length < 2) {
    svg.innerHTML = "";
    return;
  }
  const w = 300, h = 64, pad = 4;
  const closes = bars.map((b) => b.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = Math.max(max - min, 1e-6);
  const pts = closes
    .map((c, i) => {
      const x = pad + (i / (closes.length - 1)) * (w - pad * 2);
      const y = pad + (1 - (c - min) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = closes[closes.length - 1] >= closes[0];
  const color = up ? "#c45c4a" : "#3d8f73";
  svg.innerHTML = `<polyline fill="none" stroke="${color}" stroke-width="1.6" points="${pts}" />`;
}

function renderIndex(data) {
  const idx = data.index;
  $("idxPrice").textContent = fmtPrice(idx.price);
  const ch = $("idxChange");
  ch.textContent = `${fmtPct(idx.changePct)}　${idx.change > 0 ? "+" : ""}${fmtPrice(idx.change)}`;
  ch.className = "tabular " + pctClass(idx.changePct);
  $("regimeBox").textContent = `${idx.regime}　${idx.regimeDetail || ""}`;
  $("indexMeta").innerHTML = `
    <div class="stat"><div class="label">近5日</div><div class="val tabular ${pctClass((idx.ret5 || 0) * 100)}">${fmtPct((idx.ret5 || 0) * 100)}</div></div>
    <div class="stat"><div class="label">近20日</div><div class="val tabular ${pctClass((idx.ret20 || 0) * 100)}">${fmtPct((idx.ret20 || 0) * 100)}</div></div>
    <div class="stat"><div class="label">MA20</div><div class="val tabular">${fmtPrice(idx.ma20)}</div></div>
    <div class="stat"><div class="label">扫描耗时</div><div class="val tabular">${data.elapsedMs || "—"} ms</div></div>
  `;
  $("scanNote").textContent = data.note || "";
  drawSpark("spark", idx.bars || []);
  $("sessionPill").textContent = data.sessionLabel || data.session || "—";
  const silent = data.silent;
  const sp = $("silentPill");
  sp.textContent = silent ? "雷达静默" : "雷达开启";
  sp.className = "pill " + (silent ? "off" : "on");
  $("clock").textContent = "更新 " + (data.asOfLabel || "—");
  const st = data.stats || {};
  $("statsLine").textContent = `池 ${st.pool || 0} · 可关注 ${st.watch || 0} · 观察 ${st.observe || 0} · 谨慎 ${st.caution || 0} · 回避 ${st.avoid || 0}`;
}

function openStock(code) {
  $("stockCode").value = code;
  document.querySelectorAll(".nav button").forEach((b) => b.classList.remove("active"));
  document.querySelector('.nav button[data-view="stock"]').classList.add("active");
  showView("stock");
  loadStock(code);
}

function filteredEchoes() {
  if (!scanData) return [];
  let list = scanData.echoes || [];
  if (levelFilter === "热门板块") list = list.filter((e) => e.hotSector);
  else if (levelFilter !== "全部") list = list.filter((e) => e.analysis.level === levelFilter);
  if (scanData.silent && levelFilter === "可关注") return [];
  return list;
}

function renderEchoes() {
  const box = $("echoList");
  if (!scanData) {
    box.innerHTML = `<div class="loading">正在扫描公开行情…</div>`;
    return;
  }
  if (scanData.silent && levelFilter === "可关注") {
    box.innerHTML = `<div class="empty">雷达静默中：弱势空头下不主动给出「可关注」。</div>`;
    return;
  }
  const list = filteredEchoes();
  if (!list.length) {
    box.innerHTML = `<div class="empty">本屏无回波。</div>`;
    return;
  }
  box.innerHTML = list
    .map((e) => {
      const q = e.quote;
      const a = e.analysis;
      const tone = levelTone(a.level);
      const tactics = (a.tactics || []).map((t) => t.name).slice(0, 2).join(" · ") || "手法不显著";
      const inds = (q.industry || []).slice(0, 2).join(" / ");
      const watched = isWatched(q.code) ? "★" : "";
      return `<div class="echo" data-code="${q.code}" style="cursor:pointer">
        <div>
          <div class="name">${watched}${q.name}<span class="code">${q.code}</span></div>
          <div class="tags">
            <span class="tag ${tone}">${a.level}</span>
            <span class="tag">${a.phase}</span>
            <span class="tag">${a.mind}</span>
            <span class="tag">${a.vsIndex}</span>
            ${e.hotSector ? '<span class="tag up">板块共振</span>' : ""}
            ${inds ? `<span class="tag">${inds}</span>` : ""}
          </div>
          <div class="reason">${(a.buyAdvice && a.buyAdvice.action) ? ("建议：" + a.buyAdvice.action + " · ") : ""}${a.levelReason || ""} · ${tactics} · 额 ${fmtYi(q.amount)}</div>
        </div>
        <div style="text-align:right">
          <div class="tabular">${fmtPrice(q.price)}</div>
          <div class="tabular ${pctClass(q.changePct)}">${fmtPct(q.changePct)}</div>
        </div>
      </div>`;
    })
    .join("");
  box.querySelectorAll(".echo").forEach((el) => {
    el.addEventListener("click", () => openStock(el.dataset.code));
  });
}

function renderSectors() {
  const box = $("sectorList");
  if (!scanData) {
    box.innerHTML = `<div class="loading">计算中…</div>`;
    return;
  }
  const rows = scanData.sectors || [];
  if (!rows.length) {
    box.innerHTML = `<div class="empty">暂无板块聚合</div>`;
    return;
  }
  box.innerHTML = rows
    .map(
      (s) => `<div class="sector-row">
      <span>${s.industry} <span class="subtle">(${s.count})</span>${s.crowded ? ' <span class="tag warn">拥挤</span>' : ""}</span>
      <span class="tabular ${pctClass(s.excessPct)}">超额 ${fmtPct(s.excessPct)} · 广度 ${(s.breadth * 100).toFixed(0)}%</span>
    </div>`
    )
    .join("");
}


function renderIndicators(ind) {
  if (!ind || !ind.ok) return "";
  const macd = ind.macd || {};
  const boll = ind.boll || {};
  const kdj = ind.kdj || {};
  return `<h3 style="font-family:var(--display);font-size:0.95rem;margin:1rem 0 0.4rem">技术指标（辅助）</h3>
    <div class="index-meta">
      <div class="stat"><div class="label">MACD</div><div class="val tabular">${macd.cross || "—"} / hist ${macd.hist ?? "—"}</div></div>
      <div class="stat"><div class="label">RSI</div><div class="val tabular">${ind.rsi ?? "—"}</div></div>
      <div class="stat"><div class="label">布林中轨</div><div class="val tabular">${boll.mid ?? "—"}</div></div>
      <div class="stat"><div class="label">KDJ.J</div><div class="val tabular">${kdj.j ?? "—"}</div></div>
    </div>
    <p class="subtle" style="font-size:0.75rem;margin:0.35rem 0 0">指标不单独定级；与量价阶段冲突时以量价与大盘闸门为准。引擎：${ind.source || "—"}</p>`;
}


function renderBuyAdvice(b) {
  if (!b) return "";
  const reasons = (b.reasons || []).map((x) => `<li>${x}</li>`).join("") || "<li>暂无</li>";
  const risks = (b.risks || []).map((x) => `<li>${x}</li>`).join("") || "<li>暂无</li>";
  const tone = (b.action || "").includes("不建议") || (b.action || "").includes("暂不")
    ? "down"
    : (b.action || "").includes("可")
      ? "up"
      : "muted";
  return `<div class="card" style="margin:0.75rem 0;padding:0.85rem;background:var(--elevated)">
    <div style="font-weight:600">买入建议 <span class="tag ${tone}">${b.strength || ""}</span></div>
    <div class="${tone}" style="margin:0.35rem 0;font-size:1.05rem">${b.action || "—"}</div>
    <p class="muted" style="font-size:0.85rem;margin:0 0 0.5rem">${b.summary || ""}</p>
    <div style="font-size:0.8rem;color:var(--subtle)">依据</div>
    <ul class="muted" style="font-size:0.85rem;margin:0.25rem 0 0.5rem;padding-left:1.1rem">${reasons}</ul>
    <div style="font-size:0.8rem;color:var(--subtle)">风险与约束</div>
    <ul class="muted" style="font-size:0.85rem;margin:0.25rem 0 0.5rem;padding-left:1.1rem">${risks}</ul>
    <div style="font-size:0.8rem;color:var(--subtle)">操作思路（研究用）</div>
    <p class="muted" style="font-size:0.85rem;margin:0.25rem 0 0">${b.plan || ""}</p>
    <p class="subtle" style="font-size:0.72rem;margin:0.5rem 0 0">不构成投资建议；请独立判断并控制仓位。</p>
  </div>`;
}

function renderStockDetail(data) {
  const q = data.quote;
  const a = data.analysis;
  const idx = data.index || {};
  const tone = levelTone(a.level);
  const tactics = (a.tactics || [])
    .map((t) => `<div class="sector-row"><span>${t.name} <span class="tag">${t.side}</span></span><span class="subtle">${t.evidence}</span></div>`)
    .join("") || `<div class="subtle">手法标签不显著</div>`;
  const evidence = (a.evidence || []).map((x) => `<li>${x}</li>`).join("");
  $("stockResult").innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
      <div>
        <div class="name" style="font-size:1.2rem;font-weight:600">${q.name} <span class="code">${q.code}</span></div>
        <div class="tags" style="margin-top:0.4rem">
          <span class="tag ${tone}">${a.level}</span>
          <span class="tag">${a.phase}</span>
          <span class="tag">${a.mind}</span>
          <span class="tag">${a.vsIndex}</span>
          ${(q.industry || []).map((i) => `<span class="tag">${i}</span>`).join("")}
        </div>
      </div>
      <div style="text-align:right">
        <div class="index-price tabular" style="font-size:1.6rem">${fmtPrice(q.price)}</div>
        <div class="tabular ${pctClass(q.changePct)}">${fmtPct(q.changePct)}</div>
      </div>
    </div>
    <p class="reason" style="margin:0.75rem 0">${a.levelReason || ""}</p>
    ${renderBuyAdvice(a.buyAdvice)}
    <div class="index-meta">
      <div class="stat"><div class="label">主力强度</div><div class="val">${a.scores?.force ?? "—"}</div></div>
      <div class="stat"><div class="label">质量</div><div class="val">${a.scores?.quality ?? "—"}</div></div>
      <div class="stat"><div class="label">风险</div><div class="val">${a.scores?.risk ?? "—"}</div></div>
      <div class="stat"><div class="label">大盘环境</div><div class="val">${idx.regime || "—"}</div></div>
    </div>
    ${renderIndicators(data.indicators)}
    <p class="subtle" style="font-size:0.75rem;margin:0.5rem 0 0">数据源：${data.dataSource || "public"}</p>
    <svg id="stockSpark" class="spark" viewBox="0 0 300 64" preserveAspectRatio="none" style="margin-top:0.75rem"></svg>
    <h3 style="font-family:var(--display);font-size:0.95rem;margin:1rem 0 0.4rem">手法</h3>
    ${tactics}
    <h3 style="font-family:var(--display);font-size:0.95rem;margin:1rem 0 0.4rem">证据</h3>
    <ul class="muted" style="font-size:0.85rem;padding-left:1.1rem;margin:0">${evidence}</ul>
    <p class="subtle" style="font-size:0.75rem;margin-top:0.75rem">${data.note || ""} · ${a.vsIndexDetail || ""}</p>
  `;
  drawSpark("stockSpark", data.bars || []);
  currentStock = { code: q.code, name: q.name };
  updateWatchBtn();
}

async function loadStock(code) {
  const box = $("stockResult");
  box.innerHTML = `<div class="loading">分析中…</div>`;
  try {
    const res = await fetch("/api/stock?code=" + encodeURIComponent(code.trim()));
    const raw = await res.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      throw new Error("接口非 JSON（HTTP " + res.status + "）：" + raw.slice(0, 100));
    }
    if (!res.ok || data.ok === false) throw new Error(data.error || "HTTP " + res.status);
    renderStockDetail(data);
  } catch (err) {
    currentStock = null;
    updateWatchBtn();
    box.innerHTML = `<div class="err">${err.message || err}</div>`;
  }
}

function renderWatchList() {
  const box = $("watchList");
  const list = getWatch();
  if (!list.length) {
    box.innerHTML = `<div class="empty">暂无自选。在「个股」分析后点「加入自选」，或点雷达列表进个股再加。</div>`;
    return;
  }
  box.innerHTML = list
    .map((x) => {
      const st = x._status || {};
      const tone = levelTone(st.level);
      return `<div class="echo" data-code="${x.code}" style="cursor:pointer">
        <div>
          <div class="name">${x.name || x.code}<span class="code">${x.code}</span></div>
          <div class="tags">
            ${st.level ? `<span class="tag ${tone}">${st.level}</span>` : `<span class="tag">待刷新</span>`}
            ${st.phase ? `<span class="tag">${st.phase}</span>` : ""}
            ${st.vsIndex ? `<span class="tag">${st.vsIndex}</span>` : ""}
          </div>
          <div class="reason">${st.levelReason || "点此查看个股分析"}</div>
        </div>
        <div style="text-align:right">
          <div class="tabular">${st.price != null ? fmtPrice(st.price) : "—"}</div>
          <div class="tabular ${pctClass(st.changePct || 0)}">${st.changePct != null ? fmtPct(st.changePct) : ""}</div>
          <button type="button" class="btn-rm" data-rm="${x.code}" style="margin-top:0.35rem;font-size:0.75rem">移除</button>
        </div>
      </div>`;
    })
    .join("");
  box.querySelectorAll(".echo").forEach((el) => {
    el.addEventListener("click", (ev) => {
      if (ev.target.classList.contains("btn-rm")) return;
      openStock(el.dataset.code);
    });
  });
  box.querySelectorAll(".btn-rm").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      toggleWatch(btn.dataset.rm);
    });
  });
}

async function refreshWatch() {
  const list = getWatch();
  if (!list.length) return;
  $("watchList").innerHTML = `<div class="loading">刷新中…</div>`;
  const next = [];
  for (const item of list) {
    try {
      const res = await fetch("/api/stock?code=" + encodeURIComponent(item.code));
      const data = await res.json();
      if (data.ok === false) throw new Error(data.error);
      next.push({
        ...item,
        name: data.quote?.name || item.name,
        _status: {
          price: data.quote?.price,
          changePct: data.quote?.changePct,
          level: data.analysis?.level,
          phase: data.analysis?.phase,
          vsIndex: data.analysis?.vsIndex,
          levelReason: data.analysis?.levelReason,
        },
      });
    } catch {
      next.push({ ...item, _status: { levelReason: "刷新失败" } });
    }
  }
  setWatch(next.map(({ _status, ...rest }) => rest));
  // keep status in memory for render
  const merged = next;
  localStorage.setItem(WATCH_KEY, JSON.stringify(merged.map(({ _status, ...r }) => r)));
  // temporarily attach status for UI
  const saved = getWatch().map((x) => {
    const hit = merged.find((m) => m.code === x.code);
    return hit || x;
  });
  // write statuses onto objects for renderWatchList via a side channel
  window.__watchStatus = Object.fromEntries(merged.map((m) => [m.code, m._status]));
  // patch render to use __watchStatus
  const box = $("watchList");
  box.innerHTML = saved
    .map((x) => {
      const st = (window.__watchStatus && window.__watchStatus[x.code]) || {};
      const tone = levelTone(st.level);
      return `<div class="echo" data-code="${x.code}" style="cursor:pointer">
        <div>
          <div class="name">${x.name || x.code}<span class="code">${x.code}</span></div>
          <div class="tags">
            ${st.level ? `<span class="tag ${tone}">${st.level}</span>` : `<span class="tag">—</span>`}
            ${st.phase ? `<span class="tag">${st.phase}</span>` : ""}
            ${st.vsIndex ? `<span class="tag">${st.vsIndex}</span>` : ""}
          </div>
          <div class="reason">${st.levelReason || ""}</div>
        </div>
        <div style="text-align:right">
          <div class="tabular">${st.price != null ? fmtPrice(st.price) : "—"}</div>
          <div class="tabular ${pctClass(st.changePct || 0)}">${st.changePct != null ? fmtPct(st.changePct) : ""}</div>
          <button type="button" class="btn-rm" data-rm="${x.code}" style="margin-top:0.35rem;font-size:0.75rem">移除</button>
        </div>
      </div>`;
    })
    .join("");
  box.querySelectorAll(".echo").forEach((el) => {
    el.addEventListener("click", (ev) => {
      if (ev.target.classList.contains("btn-rm")) return;
      openStock(el.dataset.code);
    });
  });
  box.querySelectorAll(".btn-rm").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      toggleWatch(btn.dataset.rm);
    });
  });
}

async function loadScan(force = false) {
  try {
    const res = await fetch("/api/scan?force=" + (force ? "true" : "false"));
    const raw = await res.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      throw new Error("接口返回非 JSON（HTTP " + res.status + "）：" + raw.slice(0, 120));
    }
    if (!res.ok || (data.ok === false && data.error)) throw new Error(data.error || "HTTP " + res.status);
    scanData = data;
    renderIndex(data);
    renderEchoes();
    renderSectors();
  } catch (err) {
    $("echoList").innerHTML = `<div class="err">扫描失败：${err.message || err}</div>`;
    $("regimeBox").textContent = "请检查 /api/health 与 /api/scan。";
  }
}

function showView(v) {
  ["radar", "stock", "watch", "backtest", "rules"].forEach((name) => {
    const el = $("view-" + name);
    if (el) el.classList.toggle("hidden", name !== v);
  });
  if (v === "watch") renderWatchList();
}

function setupNav() {
  document.querySelectorAll(".nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      showView(btn.dataset.view);
    });
  });
  document.querySelectorAll("#levelFilters button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#levelFilters button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      levelFilter = btn.dataset.level;
      renderEchoes();
    });
  });
  $("stockForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const code = $("stockCode").value.trim();
    if (code) loadStock(code);
  });
  $("btnWatchToggle").addEventListener("click", () => {
    if (currentStock) toggleWatch(currentStock.code, currentStock.name);
  });
  $("btnRefreshWatch").addEventListener("click", refreshWatch);
  $("btnClearWatch").addEventListener("click", () => {
    if (confirm("确定清空全部自选？")) {
      setWatch([]);
      renderWatchList();
      updateWatchBtn();
    }
  });
}

function drawEquity(curve) {
  if (!curve || curve.length < 2) return "";
  const w = 600, h = 180, pad = 12;
  const vals = curve.map((p) => p.equity);
  const min = Math.min(...vals, 1);
  const max = Math.max(...vals, 1);
  const span = Math.max(max - min, 0.01);
  const pts = vals
    .map((v, i) => {
      const x = pad + (i / (vals.length - 1)) * (w - pad * 2);
      const y = pad + (1 - (v - min) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = vals[vals.length - 1];
  const color = last >= 1 ? "#c45c4a" : "#3d8f73";
  const y1 = pad + (1 - (1 - min) / span) * (h - pad * 2);
  return `<svg class="eq-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <line x1="${pad}" x2="${w - pad}" y1="${y1}" y2="${y1}" stroke="#3c3d36" stroke-dasharray="4 4" />
    <polyline fill="none" stroke="${color}" stroke-width="1.8" points="${pts}" />
  </svg>`;
}

async function runBacktest() {
  const box = $("btResult");
  box.innerHTML = `<div class="loading">回测运行中…</div>`;
  const levels = $("btLevels").value;
  const hold = $("btHold").value;
  try {
    const res = await fetch(`/api/backtest?levels=${encodeURIComponent(levels)}&max_hold=${hold}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "回测失败");
    const trades = (data.tradeList || [])
      .slice()
      .reverse()
      .map(
        (t) =>
          `<tr><td>${t.date}</td><td>${t.side}</td><td>${t.name} <span class="subtle mono">${t.code}</span></td><td class="tabular">${t.price}</td><td>${t.reason}</td></tr>`
      )
      .join("");
    box.innerHTML = `
      <div class="index-meta" style="margin-top:0">
        <div class="stat"><div class="label">策略收益</div><div class="val tabular ${pctClass((data.totalReturn || 0) * 100)}">${fmtPct((data.totalReturn || 0) * 100)}</div></div>
        <div class="stat"><div class="label">上证同期</div><div class="val tabular ${pctClass((data.indexReturn || 0) * 100)}">${fmtPct((data.indexReturn || 0) * 100)}</div></div>
        <div class="stat"><div class="label">超额</div><div class="val tabular ${pctClass((data.excessReturn || 0) * 100)}">${fmtPct((data.excessReturn || 0) * 100)}</div></div>
        <div class="stat"><div class="label">最大回撤</div><div class="val tabular">${fmtPct((data.maxDrawdown || 0) * 100)}</div></div>
      </div>
      <p class="subtle" style="font-size:0.8rem;margin:0.75rem 0">${data.start} → ${data.end} · 成交 ${data.trades} 笔</p>
      ${drawEquity(data.equityCurve)}
      <table class="table"><thead><tr><th>日期</th><th>方向</th><th>标的</th><th>价格</th><th>原因</th></tr></thead><tbody>${trades || "<tr><td colspan=5>无成交</td></tr>"}</tbody></table>
    `;
  } catch (err) {
    box.innerHTML = `<div class="err">${err.message || err}</div>`;
  }
}

function startTimer() {
  if (timer) clearInterval(timer);
  timer = setInterval(() => loadScan(false), REFRESH_MS);
}

setupNav();
updateWatchBtn();
$("btRun").addEventListener("click", runBacktest);
loadScan(true);
startTimer();
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (timer) clearInterval(timer);
    timer = null;
  } else {
    loadScan(true);
    startTimer();
  }
});
