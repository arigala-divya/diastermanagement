"use strict";

const STATUS = {
  ALERT:    {label: "FLOOD ALERT", color: "var(--s-alert)", hex: "#d03b3b", rank: 0},
  WATCH:    {label: "WATCH",       color: "var(--s-watch)", hex: "#fab219", rank: 1},
  NORMAL:   {label: "NORMAL",      color: "var(--s-normal)", hex: "#0ca30c", rank: 2},
  BASELINE: {label: "BASELINE ONLY", color: "var(--s-none)", hex: "#5b6878", rank: 3},
  NO_DATA:  {label: "NO DATA",     color: "var(--s-none)", hex: "#5b6878", rank: 4},
};
// Icon shapes differ per status so state never rests on colour alone.
const ICON = {
  ALERT: '<svg viewBox="0 0 12 12"><path d="M6 1 11 10.5H1Z" fill="currentColor"/></svg>',
  WATCH: '<svg viewBox="0 0 12 12"><rect x="2" y="2" width="8" height="8" transform="rotate(45 6 6)" fill="currentColor"/></svg>',
  NORMAL: '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" fill="currentColor"/></svg>',
  BASELINE: '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
  NO_DATA: '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
};
const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("en-IN", {day: "2-digit", month: "short", year: "numeric", timeZone: "Asia/Kolkata"}) : "—";
const fmtDT = (iso) => iso ? new Date(iso).toLocaleString("en-IN", {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata"}) + " IST" : "—";
const km2 = (v) => v == null ? "—" : `${(+v).toFixed(1)} km²`;
const badge = (st) => `<span class="badge b-${st}">${ICON[st] || ""}${STATUS[st]?.label || st}</span>`;

let HOTSPOTS = [], selected = null, detail = null, current = null;
const markers = {}, boxes = {};
let overlay = null;

const map = L.map("map", {zoomControl: true, attributionControl: true, minZoom: 4}).setView([23.5, 82], 5);
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
const SAR_CREDIT = " · SAR: NISAR S-SAR GCOV via ISRO Bhoonidhi";
const baseLayers = {
  "Dark": L.layerGroup([
    L.tileLayer(`${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, {maxZoom: 16, attribution: "Esri, HERE, Garmin, © OpenStreetMap contributors" + SAR_CREDIT}),
    L.tileLayer(`${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, {maxZoom: 16}),
  ]),
  "Satellite": L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {maxZoom: 17, attribution: "Esri, Maxar, Earthstar Geographics" + SAR_CREDIT}),
};
baseLayers.Dark.addTo(map);
L.control.layers(baseLayers, null, {position: "topright"}).addTo(map);

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

// ---------------------------------------------------------------- overview
async function loadHotspots() {
  HOTSPOTS = await getJSON("/api/hotspots");
  HOTSPOTS.sort((a, b) => STATUS[a.status].rank - STATUS[b.status].rank
    || (b.latest?.new_water_km2 ?? -1) - (a.latest?.new_water_km2 ?? -1));
  renderStatline();
  renderList();
  renderMarkers();
}

function renderStatline() {
  const n = (s) => HOTSPOTS.filter((h) => h.status === s).length;
  const none = n("NO_DATA") + n("BASELINE");
  $("#statline").innerHTML = [
    ["ALERT", "Flood alerts", n("ALERT")], ["WATCH", "Watch", n("WATCH")],
    ["NORMAL", "Normal", n("NORMAL")], ["NO_DATA", "Awaiting data", none],
  ].map(([s, l, v]) => `<span class="pill"><i class="dot" style="background:${STATUS[s].color}"></i>${l} <b>${v}</b></span>`).join("");
}

function renderList() {
  $("#list").innerHTML = HOTSPOTS.map((h) => `
    <div class="hs ${h.id === selected ? "sel" : ""}" data-id="${h.id}">
      <i class="dot" style="background:${STATUS[h.status].color}"></i>
      <span class="nm">${esc(h.river)} · ${esc(h.name)}</span>
      ${badge(h.status)}
      <span class="rv">${esc(h.state)} · ${h.latest ? `${km2(h.latest.new_water_km2)} new water · ${fmtDate(h.latest.acquired_at)}` : `${h.scenes_ok} scene(s) processed`}</span>
    </div>`).join("");
  document.querySelectorAll(".hs").forEach((el) => el.onclick = () => select(el.dataset.id, true));
}

function renderMarkers() {
  for (const h of HOTSPOTS) {
    const st = STATUS[h.status];
    const [w, s, e, n] = h.bbox;
    if (!boxes[h.id]) {
      boxes[h.id] = L.rectangle([[s, w], [n, e]], {weight: 1, fill: false, dashArray: "3 3"}).addTo(map);
      markers[h.id] = L.circleMarker([h.lat, h.lon], {radius: 8, weight: 2, fillOpacity: .9})
        .addTo(map).on("click", () => select(h.id, false));
    }
    boxes[h.id].setStyle({color: st.hex, opacity: .55});
    markers[h.id].setStyle({color: "#0b0f14", fillColor: st.hex, radius: h.status === "ALERT" ? 10 : 8});
    markers[h.id].bindTooltip(`<b>${esc(h.river)}</b> · ${esc(h.name)}<br>${st.label}${h.latest ? ` · ${km2(h.latest.new_water_km2)} new water` : ""}`);
  }
}

// ---------------------------------------------------------------- detail
async function select(id, fly) {
  selected = id;
  history.replaceState(null, "", `#${id}`);
  renderList();
  detail = await getJSON(`/api/hotspots/${id}`);
  const h = HOTSPOTS.find((x) => x.id === id);
  if (fly) map.flyToBounds([[h.bbox[1], h.bbox[0]], [h.bbox[3], h.bbox[2]]], {maxZoom: 10, duration: .6});
  // Default comparison: the latest pass that is not itself the baseline
  // (a baseline compared with itself shows nothing).
  const real = detail.analyses.filter((x) => x.scene_id !== x.baseline_scene_id);
  current = real.length ? real[real.length - 1]
    : detail.analyses.length ? detail.analyses[detail.analyses.length - 1] : null;
  renderDetail(h);
}

function setOverlay(a) {
  if (overlay) { map.removeLayer(overlay); overlay = null; }
  if (!a || !$("#maplayer")?.checked) return;
  const lats = a.corners_ll.map((c) => c[0]), lons = a.corners_ll.map((c) => c[1]);
  overlay = L.imageOverlay(`/renders/${a.render_change}`,
    [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]], {opacity: .9}).addTo(map);
}

function renderDetail(h) {
  const a = current;
  const t = h.thresholds;
  const groups = [...new Set(detail.analyses.map((x) => x.grp))];
  const lt = h.latest;
  $("#detail").innerHTML = `
    <h2>${esc(h.river)} · ${esc(h.name)}</h2>
    <div class="meta">${esc(h.state)} · AOI ${(h.half_km * 2).toFixed(0)}×${(h.half_km * 2).toFixed(0)} km · ${h.lat.toFixed(2)}°N ${h.lon.toFixed(2)}°E</div>
    <div class="sec">
      <h3>Current status · latest pass</h3>
      ${badge(h.status)} ${lt ? `<span class="meta">${esc(lt.scene_id)} · ${fmtDT(lt.acquired_at)}</span>` : ""}
      ${lt ? `<ul class="reasons">${lt.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : `<p class="meta">${h.scenes_ok < 2 ? "Needs at least two processed passes on the same orbit track to compare." : "No analyses yet."}</p>`}
      ${h.active_alert ? `<p class="meta">Active episode: ${esc(h.active_alert.headline)}</p>` : ""}
    </div>
    ${a ? `
    <div class="sec"><h3>Selected pass · ${fmtDate(a.acquired_at)} · track ${esc(a.grp)} ${badge(a.level)}</h3>
      ${a.id !== lt?.id ? `<ul class="reasons" style="margin-top:0">${a.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    </div>
    <div class="sec kpis">
      <div class="kpi"><div class="v">${km2(a.new_water_km2)}</div><div class="l">new water vs baseline</div></div>
      <div class="kpi"><div class="v">${a.increase_pct > 0 ? "+" : ""}${a.increase_pct.toFixed(0)}%</div><div class="l">water extent change</div></div>
      <div class="kpi"><div class="v">${a.delta_prev_km2 > 0 ? "+" : ""}${a.delta_prev_km2.toFixed(1)}</div><div class="l">km² since previous pass</div></div>
    </div>
    <div class="sec">
      <h3>Baseline vs this pass <select id="pick">${detail.analyses.slice().reverse().map((x) =>
        `<option value="${x.id}" ${x.id === a.id ? "selected" : ""}>${fmtDate(x.acquired_at)} · ${x.grp} · ${STATUS[x.level].label}</option>`).join("")}</select></h3>
      <div class="compare showchg" id="compare">
        <img src="/renders/${a.render_before}" alt="Baseline SAR backscatter">
        <img class="after" src="/renders/${a.render_after}" alt="Current SAR backscatter">
        <img class="chg after" src="/renders/${a.render_change}" alt="Change map">
        <div class="bar"></div>
        <span class="tag l">Baseline ${fmtDate(a.baseline_at)}</span><span class="tag r">${fmtDate(a.acquired_at)}</span>
        <input type="range" min="0" max="100" value="50" id="slider" aria-label="Swipe between baseline and current pass">
      </div>
      <div class="ctrls">
        <label><input type="checkbox" id="showchg" checked> Change overlay</label>
        <label><input type="checkbox" id="maplayer" checked> Show on map</label>
        <span><i class="sw" style="background:#dc2626"></i> New water</span>
        <span><i class="sw" style="background:#2563eb"></i> Water on both dates</span>
        <span><i class="sw" style="background:#eab308"></i> Receded</span>
      </div>
      <div class="note">Dark = water (low radar backscatter). Threshold ${a.threshold_db} dB · detector ${esc(a.detector)}.</div>
    </div>` : ""}
    ${detail.analyses.length ? `
    <div class="sec">
      <h3>Water extent over time</h3>
      ${groups.length > 1 ? `<div class="legend">${groups.map((g, i) => `<span><i class="sw" style="background:${SERIES[i % 3]}"></i>Track ${esc(g)}</span>`).join("")}</div>` : ""}
      <div id="chart"></div>
      <div class="note">Each point is one satellite pass. Hollow point = baseline (driest pass on that track).</div>
    </div>` : ""}
    <div class="sec">
      <h3>Alerts</h3>
      ${detail.alerts.length ? detail.alerts.map((x) => `
        <div class="alert-row">${badge(x.level)} <span class="when">${x.status} · ${x.passes} pass${x.passes > 1 ? "es" : ""} · ${fmtDate(x.acquired_at)}${x.passes > 1 ? ` – ${fmtDate(x.last_acquired_at)}` : ""}</span>
          <div>${esc(x.headline)}</div>
          ${x.status === "ACTIVE" ? `<div class="res">Latest pass: ${STATUS[x.current_level].label}, ${km2(x.new_water_km2)} new water</div>` : ""}
          ${x.resolution_reason ? `<div class="res">Resolved: ${esc(x.resolution_reason)}</div>` : ""}
        </div>`).join("") : `<div class="meta">No alerts raised for this hotspot.</div>`}
    </div>
    <div class="sec">
      <h3>Passes</h3>
      <table><thead><tr><th>Date</th><th>Track</th><th>Status</th><th>New water</th></tr></thead><tbody>
      ${detail.scenes.slice().reverse().map((s) => {
        const an = detail.analyses.find((x) => x.scene_id === s.scene_id);
        const label = !an ? s.status.toLowerCase()
          : an.scene_id === an.baseline_scene_id ? "baseline" : STATUS[an.level].label;
        return `<tr class="${an ? "click" : ""} ${an && a && an.id === a.id ? "cur" : ""}" data-aid="${an ? an.id : ""}">
          <td>${fmtDate(s.acquired_at)}</td><td>${esc(s.grp)}</td>
          <td title="${esc(s.error || "")}">${esc(label)}</td><td>${an ? km2(an.new_water_km2) : "—"}</td></tr>`;
      }).join("")}
      </tbody></table>
      <div class="note">Thresholds: watch ≥ ${t.watch_km2} km² or +${t.watch_increase_pct}% · alert ≥ ${t.alert_km2} km² or +${t.alert_increase_pct}% (contiguous patch ≥ ${t.min_patch_km2} km²).</div>
    </div>`;

  const pick = (aid) => { current = detail.analyses.find((x) => x.id === +aid); renderDetail(h); };
  $("#pick")?.addEventListener("change", (e) => pick(e.target.value));
  document.querySelectorAll("tr.click").forEach((r) => r.onclick = () => pick(r.dataset.aid));
  const slider = $("#slider");
  if (slider) {
    slider.oninput = () => {
      const v = slider.value;
      document.querySelectorAll("#compare .after").forEach((img) => img.style.clipPath = `inset(0 0 0 ${v}%)`);
      $("#compare .bar").style.left = `${v}%`;
    };
    $("#showchg").onchange = (e) => $("#compare").classList.toggle("showchg", e.target.checked);
    $("#maplayer").onchange = () => setOverlay(a);
  }
  setOverlay(a);
  if (detail.analyses.length) drawChart(groups);
}

// ---------------------------------------------------------------- chart
function drawChart(groups) {
  const el = $("#chart");
  const W = 368, H = 190, m = {l: 40, r: 10, t: 10, b: 24};
  const pts = [];
  groups.forEach((g, gi) => {
    detail.analyses.filter((x) => x.grp === g).forEach((x) => pts.push({
      g, gi, t: new Date(x.acquired_at), v: x.water_new_km2, level: x.level, id: x.scene_id,
      nw: x.new_water_km2, aid: x.id, base: x.scene_id === x.baseline_scene_id}));
  });
  const t0 = Math.min(...pts.map((p) => +p.t)), t1 = Math.max(...pts.map((p) => +p.t));
  const vmax = Math.max(...pts.map((p) => p.v)) * 1.1 || 1;
  const x = (t) => m.l + (t1 === t0 ? .5 : (t - t0) / (t1 - t0)) * (W - m.l - m.r);
  const y = (v) => H - m.b - (v / vmax) * (H - m.t - m.b);
  const ticks = [0, .25, .5, .75, 1].map((f) => f * vmax);
  const nice = (v) => v >= 100 ? v.toFixed(0) : v.toFixed(1);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Water extent in square kilometres for each pass">`;
  ticks.forEach((v) => svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)"/>
    <text x="${m.l - 6}" y="${y(v) + 3.5}" text-anchor="end" fill="var(--muted)" font-size="10" style="font-variant-numeric:tabular-nums">${nice(v)}</text>`);
  svg += `<text x="${m.l}" y="${H - 6}" fill="var(--muted)" font-size="10">${fmtDate(new Date(t0).toISOString())}</text>
    <text x="${W - m.r}" y="${H - 6}" text-anchor="end" fill="var(--muted)" font-size="10">${fmtDate(new Date(t1).toISOString())}</text>
    <text x="${m.l + 4}" y="${m.t + 9}" fill="var(--muted)" font-size="10">km² water</text>`;
  groups.forEach((g, gi) => {
    const p = pts.filter((q) => q.g === g).sort((a, b) => a.t - b.t);
    svg += `<path d="${p.map((q, i) => `${i ? "L" : "M"}${x(+q.t).toFixed(1)},${y(q.v).toFixed(1)}`).join("")}" fill="none" stroke="${SERIES[gi % 3]}" stroke-width="2" stroke-linejoin="round"/>`;
  });
  pts.forEach((p, i) => {
    const c = SERIES[p.gi % 3];
    const sel = current && p.aid === current.id;
    svg += `<circle cx="${x(+p.t)}" cy="${y(p.v)}" r="${sel ? 6 : 4.5}" fill="${p.base ? "var(--panel)" : c}" stroke="${p.base ? c : "var(--panel)"}" stroke-width="2"/>`;
    if (p.level === "ALERT" || p.level === "WATCH")
      svg += `<path transform="translate(${x(+p.t) - 5},${y(p.v) - 17}) scale(.85)" d="${p.level === "ALERT" ? "M6 1 11 10.5H1Z" : "M6 1 11 6 6 11 1 6Z"}" fill="${STATUS[p.level].hex}"/>`;
    svg += `<circle cx="${x(+p.t)}" cy="${y(p.v)}" r="12" fill="transparent" data-i="${i}" class="hit"/>`;
  });
  svg += "</svg><div class='tt'></div>";
  el.innerHTML = svg;
  const tt = el.querySelector(".tt");
  el.querySelectorAll(".hit").forEach((c) => {
    const p = pts[+c.dataset.i];
    c.style.cursor = p.aid ? "pointer" : "default";
    c.onmouseenter = () => {
      tt.innerHTML = `<b>${fmtDate(p.t.toISOString())}</b> · Track ${esc(p.g)}<br>Water extent ${km2(p.v)}<br>${p.base ? "Baseline (driest pass)" : `New water ${km2(p.nw)} · ${STATUS[p.level].label}`}`;
      tt.style.display = "block";
      const r = el.getBoundingClientRect(), s = W / r.width;
      const px = x(+p.t) / s, py = y(p.v) / s;
      tt.style.left = `${Math.min(px + 10, r.width - tt.offsetWidth - 4)}px`;
      tt.style.top = `${Math.max(0, py - tt.offsetHeight - 8)}px`;
    };
    c.onmouseleave = () => tt.style.display = "none";
    c.onclick = () => { if (p.aid) { current = detail.analyses.find((q) => q.id === p.aid); renderDetail(HOTSPOTS.find((h) => h.id === selected)); } };
  });
}

// ---------------------------------------------------------------- refresh
async function pollStatus() {
  const s = await getJSON("/api/status");
  const btn = $("#refresh");
  btn.disabled = s.running;
  btn.textContent = s.running ? "Checking Bhoonidhi…" : "Check for new scenes";
  const lr = s.last_run;
  $("#runinfo").textContent = s.error ? `Last run failed: ${s.error}` :
    lr ? `Last check ${fmtDT(lr.finished_at || lr.started_at)}` : "No runs yet";
  return s.running;
}

$("#refresh").onclick = async () => {
  await getJSON("/api/refresh", {method: "POST"});
  const tick = async () => {
    if (await pollStatus()) setTimeout(tick, 10000);
    else { await loadHotspots(); if (selected) select(selected, false); }
  };
  tick();
};

loadHotspots().then(() => {
  const id = location.hash.slice(1);
  if (HOTSPOTS.some((h) => h.id === id)) select(id, true);
  return pollStatus();
}).catch((e) => {
  $("#detail").innerHTML = `<div class="empty">Could not load data: ${esc(e.message)}</div>`;
});
