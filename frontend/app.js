/* India Disaster Intelligence — dashboard logic.
 *
 * The map is rendered purely from our own boundary file with no tile layer.
 * That is deliberate: it removes any external tile dependency (so the page
 * works on a restricted government network) and guarantees the depicted
 * boundaries are the official ones rather than a third party's rendering.
 */

const SEV_RING = {
  EXTREME: '#f85149', SEVERE: '#ff8b3d', MODERATE: '#d29922',
  MINOR: '#4d5b6b', INFO: '#3d4854',
};
const CONF_BADGE = {
  CORROBORATED: ['b-corr', 'Corroborated'], OFFICIAL: ['b-off', 'Official'],
  MODELLED: ['b-mod', 'Modelled'], REPORTED: ['b-rep', 'Reported'],
};
const TIER_BADGE = {
  1: ['b-off', 'OFFICIAL'], 2: ['b-mod', 'MODELLED'], 3: ['b-rep', 'REPORTED'],
};

const state = {
  meta: null,
  features: [],
  hazards: new Set(),      // empty = all
  selectedState: '',
  selectedId: null,
  from: '', to: '',
  days: [],                // [{d, n}] for the timeline
};

let map, stateLayer, markerLayer, statePolys = {};

/* Framing bounds. Deliberately NOT the geometry's own bounds: the island
 * territories stretch those far enough that the mainland renders tiny. This
 * frames the landmass while keeping the islands on screen. */
const INDIA_BOUNDS = L.latLngBounds([[7.2, 68.5], [35.8, 97.2]]);

/* ── helpers ─────────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* All storage is UTC; IST is applied only here, at the edge. */
function ist(iso, withTime = true) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  const o = { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' };
  if (withTime) { o.hour = '2-digit'; o.minute = '2-digit'; o.hour12 = false; }
  return d.toLocaleString('en-IN', o).replace(',', '') + (withTime ? ' IST' : '');
}
function ago(iso) {
  if (!iso) return '';
  const m = (Date.now() - new Date(iso)) / 60000;
  if (isNaN(m)) return '';
  if (m < 60) return Math.max(0, Math.round(m)) + 'm ago';
  if (m < 1440) return Math.round(m / 60) + 'h ago';
  return Math.round(m / 1440) + 'd ago';
}
const ymd = (d) => d.toISOString().slice(0, 10);

/* ── map ─────────────────────────────────────────────────────── */
function initMap() {
  map = L.map('map', {
    center: [22.6, 82], zoom: 5, minZoom: 3.5, maxZoom: 11,
    zoomControl: false, attributionControl: true,
    preferCanvas: false, worldCopyJump: false, zoomSnap: 0.25, zoomDelta: 0.5,
  });
  L.control.zoom({ position: 'topright' }).addTo(map);
  map.attributionControl.setPrefix('');
  map.attributionControl.addAttribution(
    'Boundaries: LGD / Survey of India derived &middot; Alerts: NDMA SACHET, GDACS, USGS');
  markerLayer = L.layerGroup().addTo(map);
}

function styleState(count, selected) {
  // Choropleth intensity by event count; selection wins visually.
  const t = count === 0 ? 0 : Math.min(1, Math.log10(count + 1) / 1.7);
  return {
    fillColor: count === 0 ? '#0d1520' : `rgba(37,99,160,${0.12 + t * 0.5})`,
    fillOpacity: 1,
    color: selected ? '#4a9eff' : '#22303f',
    weight: selected ? 2 : 0.8,
  };
}

function drawStates(geo, counts) {
  if (stateLayer) stateLayer.remove();
  statePolys = {};
  stateLayer = L.geoJSON(geo, {
    style: (f) => styleState(counts[f.properties.state] || 0, f.properties.state === state.selectedState),
    onEachFeature: (f, layer) => {
      const name = f.properties.state;
      statePolys[name] = layer;
      const n = counts[name] || 0;
      layer.bindTooltip(
        `<b>${esc(name)}</b><br>${n} event${n === 1 ? '' : 's'}`,
        { sticky: true, className: 'stt', opacity: 0.95 });
      layer.on('mouseover', () => layer.setStyle({ color: '#4a9eff', weight: 1.6 }));
      layer.on('mouseout', () => layer.setStyle(
        styleState(counts[name] || 0, name === state.selectedState)));
      layer.on('click', () => selectState(name === state.selectedState ? '' : name));
    },
  }).addTo(map);
  stateLayer.bringToBack();
  if (!window.__fitted) {
    window.__fitted = true;
    if (!state.selectedState) frameIndia();
  }
}

/* Leaflet can measure the container before the grid has settled, which leaves
 * the country rendered far too small. Re-measure, then frame. */
function frameIndia() {
  map.invalidateSize();
  map.fitBounds(INDIA_BOUNDS, { padding: [8, 8] });
}

function markerIcon(f) {
  const p = f.properties;
  const ring = SEV_RING[p.severity] || SEV_RING.INFO;
  const big = ['EXTREME', 'SEVERE'].includes(p.severity);
  const size = big ? 34 : 27;
  const sel = p.id === state.selectedId ? ' sel' : '';
  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div class="marker${sel}" style="width:${size}px;height:${size}px;border:2px solid ${ring}">
             ${hazardSvg(p.hazard_type, big ? 18 : 15)}</div>`,
  });
}

/* Many alerts share one district headquarters coordinate, which stacks them
 * into an unreadable pile. Offset co-located markers around a small circle so
 * every event stays individually clickable. */
function spread(features) {
  const groups = {};
  features.forEach((f) => {
    const [lon, lat] = f.geometry.coordinates;
    const k = `${lat.toFixed(3)},${lon.toFixed(3)}`;
    (groups[k] = groups[k] || []).push(f);
  });
  const out = [];
  Object.values(groups).forEach((g) => {
    if (g.length === 1) { out.push([g[0], g[0].geometry.coordinates[1], g[0].geometry.coordinates[0]]); return; }
    const r = 0.16 + Math.min(0.22, g.length * 0.012);
    g.forEach((f, i) => {
      const a = (2 * Math.PI * i) / g.length - Math.PI / 2;
      const [lon, lat] = f.geometry.coordinates;
      out.push([f, lat + r * Math.sin(a) * 0.62, lon + r * Math.cos(a)]);
    });
  });
  return out;
}

function drawMarkers(features) {
  markerLayer.clearLayers();
  // Severe events drawn last so they sit on top of the pile.
  spread(features)
    .sort((a, b) => (SEVERITY_RANK[a[0].properties.severity] || 0) - (SEVERITY_RANK[b[0].properties.severity] || 0))
    .forEach(([f, lat, lon]) => {
      L.marker([lat, lon], { icon: markerIcon(f), riseOnHover: true })
        .on('click', () => showDetail(f))
        .addTo(markerLayer);
    });
}

/* ── filters ─────────────────────────────────────────────────── */
function selectState(name) {
  state.selectedState = name;
  $('state').value = name;
  if (name && statePolys[name]) {
    map.fitBounds(statePolys[name].getBounds(), { padding: [40, 40], maxZoom: 8 });
    $('stateBadge').style.display = 'flex';
    $('stateName').textContent = name;
    $('maptip').style.display = 'none';
  } else {
    frameIndia();
    $('stateBadge').style.display = 'none';
    $('maptip').style.display = 'flex';
  }
  load();
}

function activeHazards() {
  return state.hazards.size ? [...state.hazards] : null;
}

function query() {
  const p = new URLSearchParams();
  if (state.from) p.set('from', state.from);
  if (state.to) p.set('to', state.to);
  if (state.selectedState) p.set('state', state.selectedState);
  const st = $('status').value; if (st) p.set('status', st);
  const hz = activeHazards(); if (hz) p.set('hazards', hz.join(','));
  return p.toString();
}

function setPreset(days) {
  const today = new Date();
  if (days === 'all') {
    state.from = state.meta?.span?.from?.slice(0, 10) || '2026-08-01';
    state.to = ymd(today);
  } else {
    const start = new Date(today); start.setDate(start.getDate() - Number(days) + 1);
    state.from = ymd(start); state.to = ymd(today);
  }
  $('from').value = state.from; $('to').value = state.to;
  [...$('presets').children].forEach((b) => b.classList.toggle('on', b.dataset.d === String(days)));
  return load();
}

/* ── rendering ───────────────────────────────────────────────── */
function renderHazards() {
  const box = $('haz');
  box.innerHTML = state.meta.hazards.map((h) => {
    const on = !state.hazards.size || state.hazards.has(h.key);
    return `<label class="${on ? '' : 'off'}" data-k="${h.key}">
      <input type="checkbox" ${on ? 'checked' : ''}>
      <span class="ico">${hazardSvg(h.key, 17)}</span>
      <span class="nm">${esc(h.label)}</span>
      <span class="ct">${h.count}</span></label>`;
  }).join('') || '<div style="color:var(--muted);font-size:11px;padding:4px">No events yet</div>';

  box.querySelectorAll('label').forEach((lb) => {
    lb.querySelector('input').onchange = (e) => {
      const k = lb.dataset.k;
      // Empty set means "all"; first click narrows to just that hazard.
      if (!state.hazards.size) state.meta.hazards.forEach((h) => state.hazards.add(h.key));
      e.target.checked ? state.hazards.add(k) : state.hazards.delete(k);
      if (state.hazards.size === state.meta.hazards.length) state.hazards.clear();
      renderHazards(); load();
    };
  });
}

function renderStatline() {
  const s = state.meta.statuses || {};
  const health = state.meta.health || [];
  const now = Date.now();
  const chips = health.map((h) => {
    const mins = h.last_success ? (now - new Date(h.last_success)) / 60000 : Infinity;
    const stale = mins > (h.stale_after_mins || 180);
    const col = !h.last_success ? 'var(--bad)' : stale ? 'var(--warn)' : 'var(--ok)';
    const tip = !h.last_success ? `never succeeded — ${h.last_error || 'no data'}`
      : stale ? `STALE — last success ${ago(h.last_success)}`
        : `healthy — ${h.items_last_run} items, ${ago(h.last_success)}`;
    return `<span class="pill" title="${esc(tip)}"><span class="dot" style="background:${col}"></span>${esc(h.source)}${stale ? ' <b style="color:var(--warn)">STALE</b>' : ''}</span>`;
  }).join('');

  $('statline').innerHTML = `
    <span class="pill"><span class="dot" style="background:var(--bad)"></span>Active <b>${s.ACTIVE || 0}</b></span>
    <span class="pill"><span class="dot" style="background:var(--warn)"></span>Watch <b>${s.WATCH || 0}</b></span>
    <span class="pill"><span class="dot" style="background:var(--resolved,#4d5b6b)"></span>Resolved <b>${s.RESOLVED || 0}</b></span>
    ${chips}
    ${state.meta.unlocated ? `<span class="pill" title="These alerts carry an LGD district code that is not yet in the gazetteer — usually a newly created district. They are counted but cannot be placed on the map. See scripts/build_gazetteer.py.">
      <span class="dot" style="background:var(--warn)"></span>${state.meta.unlocated} unmapped</span>` : ''}
    <span class="clock" id="clock"></span>`;
  tickClock();
}

function tickClock() {
  const el = $('clock'); if (!el) return;
  el.textContent = new Date().toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hour12: false,
  }) + ' IST';
}
setInterval(tickClock, 1000);

/* Timeline: one bar per day across the full data span, with drag-select. */
function renderTimeline() {
  const days = state.meta.daily || [];
  if (!days.length) { $('bars').innerHTML = ''; $('tlaxis').innerHTML = ''; return; }
  const span = state.meta.span || {};
  const start = new Date((span.from || days[0].d).slice(0, 10));
  const end = new Date();
  const byDay = Object.fromEntries(days.map((d) => [d.d, d.n]));

  const all = [];
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const k = ymd(d); all.push({ d: k, n: byDay[k] || 0 });
  }
  state.days = all;
  const max = Math.max(1, ...all.map((x) => x.n));

  $('bars').innerHTML = all.map((x, i) => {
    const out = (state.from && x.d < state.from) || (state.to && x.d > state.to);
    const h = x.n === 0 ? 2 : Math.max(4, Math.round((x.n / max) * 46));
    return `<div class="bar ${x.n === 0 ? 'zero' : ''} ${out ? 'out' : ''}"
      data-i="${i}" style="height:${h}px" title="${x.d} — ${x.n} event${x.n === 1 ? '' : 's'}"></div>`;
  }).join('');

  $('tlaxis').innerHTML = `<span>${ist(all[0].d, false)}</span>
    <span>${all.length} days</span><span>${ist(all[all.length - 1].d, false)}</span>`;
  $('tlinfo').textContent = `${state.from || all[0].d} → ${state.to || all[all.length - 1].d}`;
  wireDrag(all);
}

function wireDrag(all) {
  const bars = $('bars');
  let anchor = null;
  const idxOf = (e) => {
    const t = e.target.closest('.bar');
    return t ? Number(t.dataset.i) : null;
  };
  bars.onmousedown = (e) => { anchor = idxOf(e); };
  bars.onmouseup = (e) => {
    const j = idxOf(e);
    if (anchor === null || j === null) { anchor = null; return; }
    const [a, b] = [Math.min(anchor, j), Math.max(anchor, j)];
    state.from = all[a].d; state.to = all[b].d;
    $('from').value = state.from; $('to').value = state.to;
    [...$('presets').children].forEach((x) => x.classList.remove('on'));
    anchor = null;
    load();
  };
}

function showDetail(f, groupSize = 1) {
  const p = f.properties;
  state.selectedId = p.id;
  const col = HAZARD_COLORS[p.hazard_type] || HAZARD_COLORS.OTHER;
  const [cb, cl] = CONF_BADGE[p.confidence] || CONF_BADGE.REPORTED;
  const srcs = (p.sources || []).slice().sort((a, b) => a.tier - b.tier);

  const agencies = [...new Set(srcs.map((s) => s.agency).filter(Boolean))];

  $('detail').innerHTML = `
    <div class="lhead"><button class="back" id="dback">&larr; All events</button></div>
    <div class="dhead">
      <div class="ic" style="border-color:${col}44;background:${col}14">${hazardSvg(p.hazard_type, 19)}</div>
      <div style="min-width:0">
        <h2>${esc(p.headline || HAZARD_LABELS_JS[p.hazard_type] || p.hazard_type)}</h2>
        <div class="meta">${esc([p.district, p.state].filter(Boolean).join(', ') || 'Location unresolved')}${
          groupSize > 1 ? ` &middot; alert covers ${groupSize} districts` : ''}</div>
      </div>
      <button class="x" id="dx" title="Back to list">&times;</button>
    </div>

    <div class="dsec">
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
        <span class="badge b-${(p.status || '').toLowerCase()}">${esc(p.status)}</span>
        <span class="badge ${cb}">${cl}</span>
        <span class="badge b-resolved">${esc(p.severity)}</span>
      </div>
      <div class="kv">
        <span class="k">Hazard</span><span class="v">${esc(HAZARD_LABELS_JS[p.hazard_type] || p.hazard_type)}</span>
        <span class="k">First seen</span><span class="v">${ist(p.first_detected)}</span>
        <span class="k">Last update</span><span class="v">${ist(p.last_updated)} <span style="color:var(--muted)">(${ago(p.last_updated)})</span></span>
        ${p.expires_at ? `<span class="k">Valid until</span><span class="v">${ist(p.expires_at)}</span>` : ''}
        ${p.lgd_district ? `<span class="k">LGD code</span><span class="v" style="font-family:var(--mono)">${p.lgd_district}</span>` : ''}
        ${p.resolution_rule ? `<span class="k">Lifecycle</span><span class="v">${esc(p.resolution_rule)}</span>` : ''}
      </div>
    </div>

    <div class="dsec">
      <div class="st">Confirming agencies (${agencies.length || 0})</div>
      ${srcs.map((s) => {
        const [tb, tl] = TIER_BADGE[s.tier] || TIER_BADGE[3];
        return `<a class="src" href="${esc(s.url)}" target="_blank" rel="noopener">
          <div class="top"><span class="ag">${esc(s.agency || s.source)}</span>
            <span class="tier badge ${tb}">${tl}</span>
            <span style="margin-left:auto;font-size:10px;color:var(--muted)">${esc(s.source)}</span></div>
          <div class="hl">${esc(s.published_at ? ist(s.published_at) : '')}</div>
        </a>`;
      }).join('') || '<div style="color:var(--muted);font-size:11px">No source records</div>'}
      <div style="font-size:10px;color:var(--muted);margin-top:8px;line-height:1.5">
        Links open the issuing agency's original record. Always verify against the
        authoritative source before acting.
      </div>
    </div>`;

  $('dx').onclick = closeDetail;
  $('dback').onclick = closeDetail;
  drawMarkers(state.features);
}

function closeDetail() {
  state.selectedId = null;
  renderList();
  drawMarkers(state.features);
}

/* Default right-hand panel: the events behind the current filters, newest
 * first. Fills the space the tall-country map cannot use, and gives staff a
 * scannable list rather than forcing them to hunt for markers.
 *
 * One CAP alert covers many districts, so the map correctly holds one event
 * per district - but listing eleven identical headlines is unreadable. Rows
 * that share a hazard and headline collapse into a single entry showing the
 * district count, and expand to all of them on the map when clicked. */
function groupForList(features) {
  const groups = new Map();
  features.forEach((f) => {
    const p = f.properties;
    const k = `${p.hazard_type}|${p.headline}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(f);
  });
  return [...groups.values()].sort((a, b) =>
    (b[0].properties.first_detected || '').localeCompare(a[0].properties.first_detected || ''));
}

function renderList() {
  const groups = groupForList(state.features);

  $('detail').innerHTML = `
    <div class="lhead"><span class="t">${esc(state.selectedState || 'All India')}</span>
      <span class="n">${state.features.length}</span></div>
    <div id="evlist">${groups.map((g, gi) => {
      const p = g[0].properties;
      const col = HAZARD_COLORS[p.hazard_type] || HAZARD_COLORS.OTHER;
      const [cb, cl] = CONF_BADGE[p.confidence] || CONF_BADGE.REPORTED;
      const states = [...new Set(g.map((x) => x.properties.state).filter(Boolean))];
      const where = g.length > 1
        ? `${g.length} districts${states.length ? ' · ' + esc(states.slice(0, 2).join(', ')) : ''}`
        : esc([p.district, p.state].filter(Boolean).join(', ') || '—');
      return `<div class="ev" data-g="${gi}">
        <div class="ic" style="border-color:${col}44;background:${col}14">${hazardSvg(p.hazard_type, 15)}</div>
        <div class="bd">
          <div class="h">${esc(p.headline || p.hazard_type)}</div>
          <div class="m">
            <span class="badge b-${(p.status || '').toLowerCase()}">${esc(p.status)}</span>
            <span class="badge ${cb}">${cl}</span>
            <span>${where}</span>
            <span style="margin-left:auto">${ago(p.first_detected)}</span>
          </div>
        </div></div>`;
    }).join('') || '<div style="padding:16px;color:var(--muted);font-size:11.5px">No events match these filters.</div>'}</div>`;

  $('detail').querySelectorAll('.ev').forEach((el) => {
    el.onclick = () => {
      const g = groups[Number(el.dataset.g)];
      if (!g) return;
      if (g.length > 1) {
        // Frame every district the alert covers, then open the first.
        const pts = g.map((f) => [f.geometry.coordinates[1], f.geometry.coordinates[0]]);
        map.fitBounds(L.latLngBounds(pts).pad(0.35), { maxZoom: 8 });
      } else {
        const [lon, lat] = g[0].geometry.coordinates;
        map.setView([lat, lon], Math.max(map.getZoom(), 7), { animate: true });
      }
      showDetail(g[0], g.length);
    };
  });
}

/* ── data loading ────────────────────────────────────────────── */
async function loadMeta() {
  state.meta = await (await fetch('/api/meta')).json();
  const sel = $('state');
  sel.innerHTML = '<option value="">All India</option>' +
    state.meta.states.map((s) => `<option value="${esc(s.s)}">${esc(s.s)} (${s.n})</option>`).join('');
  sel.value = state.selectedState;
  renderHazards(); renderStatline(); renderTimeline();
}

async function load() {
  const data = await (await fetch('/api/events?' + query())).json();
  state.features = data.features || [];

  const counts = {};
  state.features.forEach((f) => {
    const s = f.properties.state; if (s) counts[s] = (counts[s] || 0) + 1;
  });

  if (!stateLayer) {
    const geo = await (await fetch('/api/states.geojson')).json();
    window.__geo = geo;
  }
  drawStates(window.__geo, counts);
  drawMarkers(state.features);

  const n = state.features.length;
  $('tipTxt').textContent = `${n} event${n === 1 ? '' : 's'} shown · click a state to zoom`;
  $('empty').style.display = n ? 'none' : 'grid';
  $('emptyMsg').textContent = state.selectedState
    ? `Nothing recorded in ${state.selectedState} for this window. Try widening the date range or clearing the state filter.`
    : 'Try widening the date range, or check the feed health indicators in the header.';
  renderTimeline();
  if (!state.selectedId) renderList();
  syncUrl();
}

/* ── wiring ──────────────────────────────────────────────────── */
window.HAZARD_LABELS_JS = {};

/* Deep links: the current view is reflected in the URL so staff can send a
 * colleague exactly what they are looking at. */
function syncUrl() {
  const p = new URLSearchParams();
  if (state.selectedState) p.set('state', state.selectedState);
  if (state.from) p.set('from', state.from);
  if (state.to) p.set('to', state.to);
  if (state.hazards.size) p.set('hazards', [...state.hazards].join(','));
  const st = $('status').value; if (st) p.set('status', st);
  history.replaceState(null, '', p.toString() ? '?' + p : location.pathname);
}

function applyUrl() {
  const p = new URLSearchParams(location.search);
  if (p.get('state')) state.selectedState = p.get('state');
  if (p.get('from')) state.from = p.get('from');
  if (p.get('to')) state.to = p.get('to');
  if (p.get('status')) $('status').value = p.get('status');
  (p.get('hazards') || '').split(',').filter(Boolean).forEach((h) => state.hazards.add(h));
  return p;
}

async function boot() {
  initMap();
  await loadMeta();
  (state.meta.hazards || []).forEach((h) => { window.HAZARD_LABELS_JS[h.key] = h.label; });

  const url = applyUrl();
  renderHazards();
  if (url.get('from') || url.get('to')) {
    $('from').value = state.from; $('to').value = state.to;
    [...$('presets').children].forEach((b) => b.classList.remove('on'));
    await load();
  } else {
    await setPreset('all');
  }
  // Only now do the state polygons exist, so a deep-linked state can be framed.
  if (state.selectedState) selectState(state.selectedState);

  $('presets').onclick = (e) => {
    const b = e.target.closest('button'); if (b) setPreset(b.dataset.d);
  };
  $('from').onchange = (e) => { state.from = e.target.value; load(); };
  $('to').onchange = (e) => { state.to = e.target.value; load(); };
  $('state').onchange = (e) => selectState(e.target.value);
  $('status').onchange = load;
  $('stateClear').onclick = () => selectState('');
  $('hazAll').onclick = () => {
    state.hazards.clear(); renderHazards(); load();
  };
  document.onkeydown = (e) => {
    if (e.key === 'Escape') { closeDetail(); if (state.selectedState) selectState(''); }
  };

  // Frame once the grid has settled, and again on any resize.
  requestAnimationFrame(() => setTimeout(() => { if (!state.selectedState) frameIndia(); }, 60));
  let rt; window.addEventListener('resize', () => {
    clearTimeout(rt);
    rt = setTimeout(() => { if (!state.selectedState) frameIndia(); else map.invalidateSize(); }, 150);
  });

  // Periodic refresh of counts and feed health without disturbing the view.
  setInterval(loadMeta, 120000);
}

boot();
