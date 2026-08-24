/* 主力鉴 radar client */

const REFRESH_MS = 25000;
let scanData = null;
let levelFilter = "全部";
let timer = null;

const $ = (id) => document.getElementById(id);

function pctClass(n) {
  if (n > 0.0005) return "up";
  if (n < -0.0005) return "down";
  return "muted";
}

function fmtPct(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const s = n > 0 ? "+" : "";
  return s + n.toFixed(2) + "%";
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

function drawSpark(bars) {
  const svg = $("spark");
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
  drawSpark(idx.bars || []);
  $("sessionPill").textContent = data.sessionLabel || data.session || "—";
  const silent = data.silent;
  const sp = $("silentPill");
  sp.textContent = silent ? "雷达静默" : "雷达开启";
  sp.className = "pill " + (silent ? "off" : "on");
  $("clock").textContent = "更新 " + (data.asOfLabel || "—");
  const st = data.stats || {};
  $("statsLine").textContent = `池 ${st.pool || 0} · 可关注 ${st.watch || 0} · 观察 ${st.observe || 0} · 谨慎 ${st.caution || 0} · 回避 ${st.avoid || 0}`;
}

function filteredEchoes() {
  if (!scanData) return [];
  let list = scanData.echoes || [];
  if (levelFilter === "热门板块") {
    list = list.filter((e) => e.hotSector);
  } else if (levelFilter !== "全部") {
    list = list.filter((e) => e.analysis.level === levelFilter);
  }
  if (scanData.silent && levelFilter === "可关注") {
    return [];
  }
  return list;
}

function renderEchoes() {
  const box = $("echoList");
  if (!scanData) {
    box.innerHTML = `<div class="loading">正在扫描公开行情…</div>`;
    return;
  }
  if (scanData.silent && levelFilter === "可关注") {
    box.innerHTML = `<div class="empty">雷达静默中：弱势空头下不主动给出「可关注」。可切换到「全部」查看结构。</div>`;
    return;
  }
  const list = filteredEchoes();
  if (!list.length) {
    box.innerHTML = `<div class="empty">本屏无回波。空结果是正常状态。</div>`;
    return;
  }
  box.innerHTML = list
    .map((e) => {
      const q = e.quote;
      const a = e.analysis;
      const tone = levelTone(a.level);
      const tactics = (a.tactics || []).map((t) => t.name).slice(0, 2).join(" · ") || "手法不显著";
      const inds = (q.industry || []).slice(0, 2).join(" / ");
      return `<div class="echo">
        <div>
          <div class="name">${q.name}<span class="code">${q.code}</span></div>
          <div class="tags">
            <span class="tag ${tone}">${a.level}</span>
            <span class="tag">${a.phase}</span>
            <span class="tag">${a.mind}</span>
            <span class="tag">${a.vsIndex}</span>
            ${e.hotSector ? '<span class="tag up">板块共振</span>' : ""}
            ${inds ? `<span class="tag">${inds}</span>` : ""}
          </div>
          <div class="reason">${a.levelReason || ""} · ${tactics} · 额 ${fmtYi(q.amount)}</div>
        </div>
        <div style="text-align:right">
          <div class="tabular">${fmtPrice(q.price)}</div>
          <div class="tabular ${pctClass(q.changePct)}">${fmtPct(q.changePct)}</div>
        </div>
      </div>`;
    })
    .join("");
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

async function loadScan(force = false) {
  try {
    const res = await fetch("/api/scan?force=" + (force ? "1" : "0"));
    const data = await res.json();
    if (!data.ok && data.error) throw new Error(data.error);
    scanData = data;
    renderIndex(data);
    renderEchoes();
    renderSectors();
  } catch (err) {
    $("echoList").innerHTML = `<div class="err">扫描失败：${err.message || err}</div>`;
    $("regimeBox").textContent = "行情源暂时不可用，将自动重试。";
  }
}

function setupNav() {
  document.querySelectorAll(".nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const v = btn.dataset.view;
      $("view-radar").classList.toggle("hidden", v !== "radar");
      $("view-backtest").classList.toggle("hidden", v !== "backtest");
      $("view-rules").classList.toggle("hidden", v !== "rules");
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
  box.innerHTML = `<div class="loading">回测运行中（拉取K线与复权计算，约数十秒）…</div>`;
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
      <p class="subtle" style="font-size:0.8rem;margin:0.75rem 0">${data.start} → ${data.end} · 成交 ${data.trades} 笔 · ${data.note}</p>
      ${drawEquity(data.equityCurve)}
      <h3 style="font-family:var(--display);font-size:1rem;margin:1rem 0 0.5rem">最近成交</h3>
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
