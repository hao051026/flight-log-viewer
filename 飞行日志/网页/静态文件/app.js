"use strict";

// 飞行日志查看器 - 前端逻辑（纯原生 JavaScript + Canvas，无外部依赖）

const fileInput = document.getElementById("fileInput");
const uploadBtn = document.getElementById("uploadBtn");
const statusEl = document.getElementById("status");
const summaryCard = document.getElementById("summaryCard");
const chartCard = document.getElementById("chartCard");
const summaryEl = document.getElementById("summary");
const channelSelect = document.getElementById("channelSelect");
const canvas = document.getElementById("logChart");
const ctx = canvas.getContext("2d");

let currentSeries = [];
const PALETTE = ["#000000", "#ff006e", "#ccff00", "#00d9ff", "#ff9500", "#ff006e", "#00d9ff", "#ff9500", "#ccff00", "#000000"];

function setStatus(msg, isErr) {
  statusEl.textContent = msg;
  statusEl.className = "status " + (isErr ? "err" : "ok");
}

function fmtTime(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}分${r}秒` : `${r}秒`;
}

// 渲染统计摘要表（带注解）
function renderSummary(summary) {
  const notes = summary.param_notes || {};
  const rows = [
    ["日志文件", summary.source || "—"],
    ["日志格式", summary.format || "—"],
    ["飞控固件", summary.firmware || "—"],
    ["飞行时长", fmtTime(summary.duration_s)],
    ["数据采样数", summary.sample_count ?? "—"],
    ["解锁周期", summary.armed_cycles ?? "—"],
    ["最高海拔", summary.max_altitude_m != null ? summary.max_altitude_m.toFixed(1) + " 米" : "—"],
    ["最高速度", summary.max_speed_m_s != null ? summary.max_speed_m_s.toFixed(1) + " 米/秒" : "—"],
    ["最大电流", summary.max_current_a != null ? summary.max_current_a.toFixed(1) + " 安培" : "—"],
    ["最大水平加速度", summary.max_horizontal_accel_g != null ? summary.max_horizontal_accel_g.toFixed(2) + " g" : "—"],
    ["电池最低电压", summary.battery_min_v != null ? summary.battery_min_v.toFixed(2) + " 伏" : "—"],
    ["电池起始电压", summary.battery_start_v != null ? summary.battery_start_v.toFixed(2) + " 伏" : "—"],
    ["电池结束电压", summary.battery_end_v != null ? summary.battery_end_v.toFixed(2) + " 伏" : "—"],
  ];
  // key -> 字段名（用于查注解）
  const keyMap = {
    "日志文件": "source", "日志格式": "format", "飞控固件": "firmware",
    "飞行时长": "duration_s", "数据采样数": "sample_count", "解锁周期": "armed_cycles",
    "最高海拔": "max_altitude_m", "最高速度": "max_speed_m_s", "最大电流": "max_current_a",
    "最大水平加速度": "max_horizontal_accel_g", "电池最低电压": "battery_min_v",
    "电池起始电压": "battery_start_v", "电池结束电压": "battery_end_v",
  };
  let html = '<table class="brutal-table">';
  html += "<thead><tr><th>参数</th><th>数值</th><th>注解</th></tr></thead><tbody>";
  for (const [k, v] of rows) {
    const note = notes[keyMap[k]] || "";
    html += `<tr><td>${k}</td><td>${v}</td><td class="note">${note}</td></tr>`;
  }
  html += "</tbody></table>";

  if (summary.channel_report && Object.keys(summary.channel_report).length) {
    html += '<h3 style="margin-top:16px;font-size:15px;font-weight:900">通道统计（最小值 ~ 最大值）</h3><table class="brutal-table">';
    html += "<thead><tr><th>通道</th><th>数值范围</th><th>注解</th></tr></thead><tbody>";
    for (const [name, [mn, mx]] of Object.entries(summary.channel_report)) {
      html += `<tr><td>${name}</td><td>${mn.toFixed(3)} ~ ${mx.toFixed(3)}</td><td class="note">${window.__channelNote ? window.__channelNote(name) : ""}</td></tr>`;
    }
    html += "</tbody></table>";
  }
  summaryEl.innerHTML = html;
}

// 获取已选中的通道
function getSelected() {
  const out = [];
  for (const opt of channelSelect.options) {
    if (opt.selected) out.push(currentSeries[+opt.value]);
  }
  return out;
}

// —— 原生 Canvas 绘制曲线 ——
function resizeCanvas() {
  const wrap = canvas.parentElement;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  canvas.width = w * devicePixelRatio;
  canvas.height = h * devicePixelRatio;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  return { w, h };
}

function drawChart() {
  const sel = getSelected();
  if (sel.length === 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  const { w, h } = resizeCanvas();

  // 收集所有选中通道的数据（过滤 null）
  let tMin = Infinity, tMax = -Infinity, vMin = Infinity, vMax = -Infinity;
  const seriesData = [];
  for (const s of sel) {
    if (!s || !s.time || !s.values) continue;
    const pts = [];
    for (let i = 0; i < s.time.length; i++) {
      const v = s.values[i];
      if (v == null || isNaN(v)) continue;
      const t = s.time[i];
      pts.push([t, v]);
      if (t < tMin) tMin = t;
      if (t > tMax) tMax = t;
      if (v < vMin) vMin = v;
      if (v > vMax) vMax = v;
    }
    if (pts.length > 1) seriesData.push(pts);
  }

  if (seriesData.length === 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawText("没有可绘制的数据", w / 2, h / 2);
    return;
  }
  // 保证时间轴有效
  if (!(tMax > tMin)) tMax = tMin + 1;
  if (!(vMax > vMin)) vMax = vMin + 1;
  // 给数值范围加一点外边距
  const vPad = (vMax - vMin) * 0.06;
  vMin -= vPad; vMax += vPad;

  // ---- 先测量图例高度，避免图例压住曲线 ----
  const labelFont = "bold 11px monospace";
  ctx.font = labelFont;
  const legendRowH = 16;          // 每行图例高度
  const legendPad = 12;           // 图例区上下留白
  let legendH = legendPad;        // 图例总高度（至少一行的留白）
  // 模拟排版计算图例行数
  let lx = 12, rows = 1;
  for (let si = 0; si < seriesData.length; si++) {
    const label = sel[si].label || sel[si].cn_name || sel[si].name || "通道";
    const tWidth = ctx.measureText(label).width;
    if (lx + 18 + tWidth > w - 8 && lx !== 12) { lx = 12; rows++; }
    lx += 18 + tWidth + 16;
  }
  legendH = legendPad + rows * legendRowH;

  // ---- 绘图区留白（顶部预留图例空间） ----
  const padL = 12, padR = 8, padT = legendH, padB = 34;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  if (plotH < 40) return;   // 画布太小不画

  const X = t => padL + ((t - tMin) / (tMax - tMin)) * plotW;
  // Y 轴：应用纵向缩放（zoomY 放大细节）
  const vCenter = (vMin + vMax) / 2;
  let vSpan = (vMax - vMin);
  if (!(vSpan > 0)) vSpan = 1;
  const vVMin = vCenter - vSpan / 2 / chartPlayState.zoomY;
  const vVMax = vCenter + vSpan / 2 / chartPlayState.zoomY;
  const Y = v => padT + plotH - ((v - vVMin) / (vVMax - vVMin || 1)) * plotH;

  // 清空 + 白底纸面背景
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  // 外边框（Neo 黑框）
  ctx.strokeStyle = "#000000";
  ctx.lineWidth = 3;
  ctx.strokeRect(0, 0, w, h);

  // ---- 画图例（放在顶部留白区内，最上方） ----
  ctx.textAlign = "left"; ctx.font = labelFont;
  lx = padL; let ly = 14;
  for (let si = 0; si < seriesData.length; si++) {
    const label = sel[si].label || sel[si].cn_name || sel[si].name || "通道";
    const color = PALETTE[si % PALETTE.length];
    const tWidth = ctx.measureText(label).width;
    if (lx + 18 + tWidth > w - padR && lx !== padL) { lx = padL; ly += legendRowH; }
    ctx.fillStyle = color;
    ctx.fillRect(lx, ly - 8, 12, 4);
    ctx.fillStyle = "#000000";
    ctx.fillText(label, lx + 16, ly - 4);
    lx += 18 + tWidth + 16;
  }

  // 图例下方画一条分隔虚线
  ctx.strokeStyle = "rgba(0,0,0,0.35)";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(padL, padT - 6); ctx.lineTo(w - padR, padT - 6); ctx.stroke();
  ctx.setLineDash([]);

  // 网格：细黑线
  ctx.strokeStyle = "rgba(0,0,0,0.15)";
  ctx.lineWidth = 1;
  for (let gx = 0; gx <= 4; gx++) {
    const x = padL + (gx / 4) * plotW;
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke();
  }
  for (let gy = 0; gy <= 4; gy++) {
    const y = padT + (gy / 4) * plotH;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
  }

  // 坐标轴标题（等宽）
  ctx.fillStyle = "#000000"; ctx.font = "bold 12px monospace"; ctx.textAlign = "center";
  ctx.fillText("时间（秒）", w / 2, h - 6);
  // 数值刻度
  ctx.textAlign = "right"; ctx.fillStyle = "#000000";
  for (let gy = 0; gy <= 4; gy++) {
    const y = padT + (gy / 4) * plotH;
    const val = vMax - ((vMax - vMin) / 4) * gy;
    ctx.fillText(val.toFixed(typeof val === "number" && Math.abs(val) < 100 ? 1 : 0), padL - 4, y + 4);
  }
  // 时间刻度
  ctx.textAlign = "center";
  for (let gx = 0; gx <= 4; gx++) {
    const x = padL + (gx / 4) * plotW;
    const tVal = tMin + ((tMax - tMin) / 4) * gx;
    ctx.fillText(tVal.toFixed(1), x, padT + plotH + 14);
  }

  // 绘制每条曲线（Neo-Brutalist 强调色）；播放/拖动进度条时只画到当前帧
  const playFrac = (chartPlayState.playing || chartPlayState.frame > 0) ? chartPlayState.frame : 1;   // 0..1
  const maxIdx = (idx, n) => Math.max(2, Math.floor(n * playFrac));     // 至少画 2 点
  const cutX = [];
  for (let si = 0; si < seriesData.length; si++) {
    const pts = seriesData[si];
    const color = PALETTE[si % PALETTE.length];
    const lim = maxIdx(si, pts.length);
    const stepMax = Math.max(1, Math.ceil(lim / 1500));
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.4;
    let started = false;
    for (let i = 0; i < lim; i += stepMax) {
      const x = X(pts[i][0]), y = Y(pts[i][1]);
      if (!started) { ctx.moveTo(x, y); started = true; }
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    if (lim < pts.length) {
      // 记录当前播放端点的 x（用于进度游标）
      const px = X(pts[lim - 1][0]);
      cutX.push([px, pts[lim - 1][1]]);
    }
  }

  // 播放进度游标（竖线）——播放中或拖动进度条时显示
  if ((chartPlayState.playing || chartPlayState.frame > 0) && cutX.length) {
    const cx2 = cutX[0][0];
    ctx.strokeStyle = "#ff006e";
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(cx2, padT); ctx.lineTo(cx2, padT + plotH); ctx.stroke();
    ctx.setLineDash([]);
    // 游标时间标签
    const tNow = tMin + (tMax - tMin) * playFrac;
    ctx.fillStyle = "#ff006e";
    ctx.font = "bold 11px monospace";
    ctx.textAlign = "center";
    ctx.fillText(tNow.toFixed(1) + "s", cx2, padT - 8);
  }
}

function drawText(text, x, y) {
  ctx.fillStyle = "#000000";
  ctx.font = "bold 14px monospace";
  ctx.textAlign = "center";
  ctx.fillText(text, x, y);
}

/* ---- 曲线图：播放状态与滚轮缩放（独立于轨迹图） ---- */
const chartPlayState = {
  playing: false,      // 是否播放中
  frame: 0,            // 播放进度 0..1
  raf: null,           // 动画帧句柄
  zoomY: 1,            // 纵向缩放
  panY: 0,             // 纵向平移（归一化）
};
const chartWheelState = {
  listener: null,
};

function startChartPlay() {
  if (chartPlayState.playing) return;
  const btn = document.getElementById("chartPlayBtn");
  chartPlayState.playing = true;
  if (btn) btn.textContent = "⏸ 暂停";
  const step = () => {
    if (!chartPlayState.playing) return;
    chartPlayState.frame += 0.003;
    if (chartPlayState.frame >= 1) {   // 播完自动回到开头继续
      chartPlayState.frame = 0;
    }
    const seek = document.getElementById("chartSeek");
    if (seek) seek.value = Math.round(chartPlayState.frame * 100);
    const lbl = document.getElementById("chartProgressLabel");
    if (lbl) lbl.textContent = Math.round(chartPlayState.frame * 100) + "%";
    drawChart();
    chartPlayState.raf = requestAnimationFrame(step);
  };
  chartPlayState.raf = requestAnimationFrame(step);
}

function stopChartPlay() {
  chartPlayState.playing = false;
  if (chartPlayState.raf) { cancelAnimationFrame(chartPlayState.raf); chartPlayState.raf = null; }
  const btn = document.getElementById("chartPlayBtn");
  if (btn) btn.textContent = "▶ 播放";
}

function bindChartControls() {
  const btn = document.getElementById("chartPlayBtn");
  if (btn) btn.onclick = () => {
    if (chartPlayState.playing) stopChartPlay();
    else startChartPlay();
  };
  const seek = document.getElementById("chartSeek");
  if (seek) seek.oninput = () => {
    chartPlayState.frame = (+seek.value) / 100;
    const lbl = document.getElementById("chartProgressLabel");
    if (lbl) lbl.textContent = Math.round(chartPlayState.frame * 100) + "%";
    drawChart();
  };
  // 曲线图滚轮：纵向缩放（滚轮上下=放大/缩小曲线幅度）——只绑定曲线画布，不影响轨迹图
  const canvasEl = document.getElementById("logChart");
  if (canvasEl) {
    canvasEl.onwheel = e => {
      e.preventDefault();
      e.stopPropagation();
      const f = e.deltaY < 0 ? 1.12 : 0.89;
      chartPlayState.zoomY = Math.max(0.2, Math.min(8, chartPlayState.zoomY * f));
      drawChart();
    };
  }
}

// 填充通道下拉
let channelNoteMap = {};
window.__channelNote = function (cnNameOrLabel) {
  return channelNoteMap[cnNameOrLabel] || "";
};
function buildChart(series) {
  currentSeries = Array.isArray(series) ? series : [];
  stopChartPlay();
  chartPlayState.frame = 0;
  chartPlayState.zoomY = 1;
  const seekEl = document.getElementById("chartSeek");
  if (seekEl) seekEl.value = 0;
  const lblEl = document.getElementById("chartProgressLabel");
  if (lblEl) lblEl.textContent = "0%";
  channelSelect.innerHTML = "";
  channelNoteMap = {};
  currentSeries.forEach((s, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = s.label || s.cn_name || s.name || "通道" + i;
    const label = s.label || s.cn_name || s.name || "";
    const cn = s.cn_name || s.name || "";
    const note = s.note || "";
    // 用标签和中文名都能查到注解
    channelNoteMap[label] = note;
    channelNoteMap[cn] = note;
    if (note) opt.title = note;   // 悬浮提示
    channelSelect.appendChild(opt);
  });
  // 默认全选前 4 个
  for (let i = 0; i < Math.min(4, channelSelect.options.length); i++) {
    channelSelect.options[i].selected = true;
  }
  channelSelect.onchange = function () { drawChart(); updateNoteBar(); };
  drawChart();
  updateNoteBar();
  window.addEventListener("resize", drawChart);
}

// 在通道下拉下方更新“当前选中通道”的中文注解
function updateNoteBar() {
  let bar = document.getElementById("channelNotes");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "channelNotes";
    bar.className = "channel-notes";
    channelSelect.parentElement.appendChild(bar);
  }
  const sel = getSelected();
  const parts = [];
  for (const s of sel) {
    const note = s.note || "暂无注解";
    const label = s.label || s.cn_name || s.name || "通道";
    parts.push(`<b>${label}</b>：${note}`);
  }
  bar.innerHTML = parts.length ? parts.join("<br>") : "请在上方选择要查看的通道";
}

uploadBtn.addEventListener("click", async () => {
  if (!fileInput.files.length) {
    setStatus("请先选择一个飞行日志文件。", true);
    return;
  }
  const file = fileInput.files[0];
  setStatus("正在上传解析…");
  uploadBtn.disabled = true;
  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch("/api/analyze", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || "解析失败");
    setStatus("✅ 解析成功：日志格式 " + data.format);
    summaryCard.style.display = "block";
    chartCard.style.display = "block";
    renderSummary(data.summary);
    buildChart(data.series || []);
    renderTrack(data.track || {});
  } catch (e) {
    setStatus("❌ " + e.message, true);
    summaryCard.style.display = "none";
    chartCard.style.display = "none";
  } finally {
    uploadBtn.disabled = false;
  }
});

// 拖拽上传
document.body.addEventListener("dragover", e => e.preventDefault());
document.body.addEventListener("drop", e => {
  e.preventDefault();
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    uploadBtn.click();
  }
});

/* ============================================================
 * 3D 飞行轨迹渲染器（原生 Canvas，零外部依赖）
 * 透视投影 + 手动旋转矩阵 + 高度着色 + 地面网格 + 交互
 * ============================================================ */

// 轨迹状态
const trackState = {
  points: [],        // 原始 [x,y,z] 米制
  norm: [],          // 归一化坐标
  rotX: -0.6,        // 绕 X 轴旋转
  rotY: 0.8,         // 绕 Y 轴旋转
  zoom: 1.0,         // 缩放
  dragging: false,
  lastX: 0, lastY: 0,
  durations: [],     // 每个轨迹点的累计时间（秒）
};

// 轨迹播放状态
const trackPlayState = {
  playing: false,
  frame: 0,          // 0..1
  raf: null,
  speed: 1,
};

function renderTrack(track) {
  const card = document.getElementById("trackCard");
  const metaEl = document.getElementById("trackMeta");
  const canvas = document.getElementById("trackCanvas");

  if (!track || !track.ok || !track.points || track.points.length < 2) {
    card.style.display = "none";
    return;
  }
  card.style.display = "block";

  const pts = track.points;
  const times = track.times || [];
  const m = track.meta || {};

  // 元信息（含精度说明）
  const dur = times.length >= 2 ? (times[times.length-1] - times[0]) : 0;
  const zBasis = m.z_basis ? `高度基准：${m.z_basis}` : "";
  metaEl.innerHTML =
    `轨迹点数 <b>${m.count}</b> ｜ 水平跨度 <b>${(m.span_xy_m/1000).toFixed(1)} km</b> ｜ ` +
    `高度 <b>${fmtNum(m.z_min)} ~ ${fmtNum(m.z_max)} m</b> ｜ ` +
    `坐标换算 <b>WGS84 椭球精确</b> ｜ ` +
    (dur > 0 ? `时长 <b>${fmtTime(dur)}</b> ｜ ` : "") +
    `来源 <b>${m.source || ""}</b>` +
    (zBasis ? `<br><span style="font-size:11px;opacity:.75">${zBasis}</span>` : "");

  // 归一化到 [-1,1] 便于渲染（保留各轴实际比例）
  const xs = pts.map(p=>p[0]), ys = pts.map(p=>p[1]), zs = pts.map(p=>p[2]);
  let mx = Math.max(...xs), mnx = Math.min(...xs);
  let my = Math.max(...ys), mny = Math.min(...ys);
  let mz = Math.max(...zs), mnz = Math.min(...zs);
  if (mx===mnx) mx=mnx+1; if (my===mny) my=mny+1; if (mz===mnz) mz=mnz+1;
  const cx=(mx+mnx)/2, cy=(my+mny)/2, cz=(mz+mnz)/2;
  const scale = Math.max(mx-mnx, my-mny, (mz-mnz)||1);
  trackState.points = pts;
  trackState.norm = pts.map(p => [
    (p[0]-cx)/scale,
    (p[1]-cy)/scale,
    (p[2]-cz)/scale,
  ]);
  // 地面网格水平跨度（用于画地平面）
  trackState.groundHalf = Math.max((mx-mnx)/scale, (my-mny)/scale) * 0.5 + 0.15;
  trackState.zRange = [(mnz-cz)/scale, (mz-cz)/scale];

  // 重置视角便于查看
  trackState.rotX = -0.6; trackState.rotY = 0.8; trackState.zoom = 1.0;
  // 累计飞行时间（用于播放时的进度标注）
  if (times.length >= pts.length) {
    trackState.durations = times.map(t => t - times[0]);
  } else {
    trackState.durations = pts.map((_, i) => i);
  }
  trackPlayState.frame = 0;
  if (trackPlayState.playing) stopTrackPlay();
  drawTrack();
  bindTrackEvents();
  bindTrackControls();
}

function fmtNum(v) {
  if (v == null || isNaN(v)) return "—";
  return v >= 100 ? Math.round(v).toString() : v.toFixed(1);
}

// 旋转一个点（先绕Y再绕X）
function rotatePoint(x, y, z) {
  const rx = trackState.rotX, ry = trackState.rotY;
  const cx = Math.cos(ry), sx = Math.sin(ry);
  // 绕 Y 轴
  const x1 = x * cx + z * sx;
  const z1 = -x * sx + z * cx;
  const y1 = y;
  // 绕 X 轴
  const cy = Math.cos(rx), sy = Math.sin(rx);
  const y2 = y1 * cy - z1 * sy;
  const z2 = y1 * sy + z1 * cy;
  return [x1, y2, z2];
}

function resizeTrackCanvas() {
  const wrap = document.getElementById("trackWrap");
  const w = wrap.clientWidth, h = wrap.clientHeight;
  const canvas = document.getElementById("trackCanvas");
  canvas.width = w * devicePixelRatio;
  canvas.height = h * devicePixelRatio;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  return { w, h, dpr: devicePixelRatio };
}

// 高度 -> Neo 强调色（低->高：绿->青->粉）
function heightColor(zn, zMin, zMax) {
  if (!(zMax > zMin)) return "#000000";
  const t = Math.max(0, Math.min(1, (zn - zMin) / (zMax - zMin)));
  // 定义了三个颜色过渡: lime -> cyan -> pink
  const stops = [
    [0, [204, 255, 0]],
    [0.5, [0, 217, 255]],
    [1, [255, 0, 110]],
  ];
  let c1 = stops[0], c2 = stops[stops.length-1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i][0] && t <= stops[i+1][0]) { c1 = stops[i]; c2 = stops[i+1]; break; }
  }
  const f = (t - c1[0]) / (c2[0] - c1[0] || 1);
  const r = Math.round(c1[1][0] + (c2[1][0]-c1[1][0])*f);
  const g = Math.round(c1[1][1] + (c2[1][1]-c1[1][1])*f);
  const b = Math.round(c1[1][2] + (c2[1][2]-c1[1][2])*f);
  return `rgb(${r},${g},${b})`;
}

function drawTrack() {
  const canvas = document.getElementById("trackCanvas");
  const ctx2 = canvas.getContext("2d");
  const { w, h } = resizeTrackCanvas();
  ctx2.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);

  // 白底
  ctx2.fillStyle = "#ffffff";
  ctx2.fillRect(0, 0, w, h);
  // 外框
  ctx2.strokeStyle = "#000";
  ctx2.lineWidth = 3;
  ctx2.strokeRect(0, 0, w, h);

  const norm = trackState.norm;
  if (!norm.length) return;
  const cx = w / 2, cy = h / 2;
  const s = 0.9 * Math.min(w, h) / (2.2 + (1 - trackState.zoom) * 2) * trackState.zoom;
  const zMin = trackState.zRange[0], zMax = trackState.zRange[1];

  const proj = p => {
    const rt = rotatePoint(p[0], p[1], p[2]);
    // 简单透视（z 不影响位置但影响一点缩放感）
    const f = 4.0;
    const persp = f / (f + rt[2]);
    return [cx + rt[0] * s * persp, cy - rt[1] * s * persp, rt[2], persp];
  };

  // ---- 地面网格（在 z = 底部高度处画一个网格平面） ----
  const gridLevel = zMin - 0.08;
  ctx2.strokeStyle = "rgba(0,0,0,0.22)";
  ctx2.lineWidth = 1;
  ctx2.beginPath();
  const gHalf = trackState.groundHalf || 1;
  const gN = 8;
  for (let i = 0; i <= gN; i++) {
    const t = -gHalf + (2*gHalf*i/gN);
    const p1 = proj([t, -gHalf, gridLevel]);
    const p2 = proj([t, gHalf, gridLevel]);
    ctx2.moveTo(p1[0], p1[1]); ctx2.lineTo(p2[0], p2[1]);
    const q1 = proj([-gHalf, t, gridLevel]);
    const q2 = proj([gHalf, t, gridLevel]);
    ctx2.moveTo(q1[0], q1[1]); ctx2.lineTo(q2[0], q2[1]);
  }
  ctx2.stroke();
  // 地面填充（淡柠檬色）
  ctx2.fillStyle = "rgba(204,255,0,0.18)";
  ctx2.beginPath();
  const corners = [[-gHalf,-gHalf],[gHalf,-gHalf],[gHalf,gHalf],[-gHalf,gHalf]].map(c=>proj([c[0],c[1],gridLevel]));
  ctx2.moveTo(corners[0][0], corners[0][1]);
  for (let i=1;i<corners.length;i++) ctx2.lineTo(corners[i][0], corners[i][1]);
  ctx2.closePath(); ctx2.fill();

  // ---- 轨迹线（按高度着色；播放时只画到当前帧） ----
  const stepMax = Math.max(1, Math.ceil(norm.length / 2000));
  const projected = norm.map(p => proj(p));
  const totalPts = projected.length;
  // 播放截断：取前 playFrac 比例的点
  const playFrac = trackPlayState.playing || trackPlayState.frame > 0 ? trackPlayState.frame : 1;
  const drawLimit = Math.max(2, Math.floor(totalPts * playFrac));
  ctx2.lineWidth = 2.6;
  ctx2.lineJoin = "round"; ctx2.lineCap = "round";
  // 先画一条暗色底（增加体积感）
  ctx2.beginPath();
  for (let i = 0; i < drawLimit; i += stepMax) {
    const p = projected[i];
    if (i === 0) ctx2.moveTo(p[0], p[1]); else ctx2.lineTo(p[0], p[1]);
  }
  // 若截断处不在整点，补画到截断点
  if (drawLimit < projected.length) {
    const p = projected[drawLimit - 1];
    ctx2.lineTo(p[0], p[1]);
  }
  ctx2.strokeStyle = "rgba(0,0,0,0.25)";
  ctx2.lineWidth = 4.5;
  ctx2.stroke();

  // 高度渐变主轨迹（同截断）
  for (let i = 0; i < Math.min(drawLimit - 1, projected.length - 1); i += stepMax) {
    const a = projected[i], b = projected[Math.min(i + stepMax, drawLimit - 1)];
    const zn = norm[i][2];
    ctx2.beginPath();
    ctx2.moveTo(a[0], a[1]); ctx2.lineTo(b[0], b[1]);
    ctx2.strokeStyle = heightColor(zn, zMin, zMax);
    ctx2.lineWidth = 2.6;
    ctx2.stroke();
  }

  // ---- 起点 / 播放中动态终点标记 ----
  if (projected.length) {
    const start = projected[0];
    // 起点：粉色方块
    ctx2.fillStyle = "#ff006e";
    ctx2.beginPath(); ctx2.rect(start[0]-6, start[1]-6, 12, 12); ctx2.fill();
    ctx2.strokeStyle = "#000"; ctx2.lineWidth = 2; ctx2.stroke();
    // 当前/最终终点：青色圆
    const cur = projected[Math.min(drawLimit, projected.length) - 1];
    ctx2.fillStyle = "#00d9ff";
    ctx2.beginPath(); ctx2.arc(cur[0], cur[1], 7, 0, Math.PI*2); ctx2.fill();
    ctx2.strokeStyle = "#000"; ctx2.lineWidth = 2; ctx2.stroke();
  }

  // ---- 坐标轴提示（右下角小信息） ----
  ctx2.font = "bold 11px monospace";
  ctx2.fillStyle = "#000";
  ctx2.textAlign = "right";
  ctx2.fillText(`X 东 ${Math.round(trackState.points[0][0])}m · Y 北 · Z 高`, w-10, h-10);
}

// 绑定鼠标交互：拖拽旋转 + 滚轮缩放
function bindTrackEvents() {
  const trackCanvasEl = document.getElementById("trackCanvas");
  trackCanvasEl.onmousedown = e => {
    trackState.dragging = true;
    trackState.lastX = e.clientX; trackState.lastY = e.clientY;
    trackCanvasEl.style.cursor = "grabbing";
    e.preventDefault();
  };
  window.onmousemove = e => {
    if (!trackState.dragging) return;
    const dx = e.clientX - trackState.lastX;
    const dy = e.clientY - trackState.lastY;
    trackState.lastX = e.clientX; trackState.lastY = e.clientY;
    trackState.rotY += dx * 0.01;
    trackState.rotX += dy * 0.01;
    trackState.rotX = Math.max(-1.5, Math.min(1.5, trackState.rotX));
    drawTrack();
  };
  window.onmouseup = () => {
    trackState.dragging = false;
    document.getElementById("trackCanvas").style.cursor = "grab";
  };
  trackCanvasEl.onwheel = e => {
    e.preventDefault();
    trackState.zoom *= (e.deltaY < 0) ? 1.12 : 0.89;
    trackState.zoom = Math.max(0.3, Math.min(4, trackState.zoom));
    drawTrack();
  };
  trackCanvasEl.style.cursor = "grab";
}

/* ---- 轨迹播放控制（独立于曲线图播放） ---- */
function startTrackPlay() {
  if (trackPlayState.playing) return;
  const btn = document.getElementById("trackPlayBtn");
  trackPlayState.playing = true;
  if (btn) btn.textContent = "⏸ 暂停";
  const step = () => {
    if (!trackPlayState.playing) return;
    trackPlayState.frame += 0.0025 * trackPlayState.speed;
    if (trackPlayState.frame >= 1) {
      trackPlayState.frame = 1;
      stopTrackPlay();        // 播完停在终点
      updateTrackProgressUI();
      drawTrack();
      return;
    }
    updateTrackProgressUI();
    drawTrack();
    trackPlayState.raf = requestAnimationFrame(step);
  };
  trackPlayState.raf = requestAnimationFrame(step);
}

function stopTrackPlay() {
  trackPlayState.playing = false;
  if (trackPlayState.raf) { cancelAnimationFrame(trackPlayState.raf); trackPlayState.raf = null; }
  const btn = document.getElementById("trackPlayBtn");
  if (btn) btn.textContent = "▶ 播放";
}

function updateTrackProgressUI() {
  const lbl = document.getElementById("trackProgressLabel");
  const seek = document.getElementById("trackSeek");
  const pct = Math.round(trackPlayState.frame * 100);
  if (lbl) {
    const n = trackState.points.length;
    const idx = Math.min(n - 1, Math.floor(trackPlayState.frame * n));
    const tSec = trackPlayState.frame > 0 && trackState.durations.length === n
      ? trackState.durations[idx] : trackPlayState.frame;
    lbl.textContent = `${fmtNum(tSec)}s · ${idx + 1}/${n} 帧`;
  }
  if (seek) seek.value = pct;
}

function bindTrackControls() {
  const btn = document.getElementById("trackPlayBtn");
  if (btn) btn.onclick = () => {
    if (trackPlayState.playing) stopTrackPlay();
    else {
      if (trackPlayState.frame >= 1) trackPlayState.frame = 0;   // 播完再点从头播
      startTrackPlay();
    }
  };
  const seek = document.getElementById("trackSeek");
  if (seek) seek.oninput = () => {
    trackPlayState.frame = (+seek.value) / 100;
    updateTrackProgressUI();
    drawTrack();
  };
  const speedSel = document.getElementById("trackSpeed");
  if (speedSel) speedSel.onchange = () => {
    trackPlayState.speed = parseFloat(speedSel.value) || 1;
  };
}

// 滚轮分离开关：曲线图滚轮 = 纵向缩放曲线；
// 轨迹图滚轮 = 3D 缩放（各自监听自己的画布，互不干扰）。
window.addEventListener("load", () => {
  bindChartControls();
});