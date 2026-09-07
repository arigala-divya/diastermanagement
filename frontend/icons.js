/* Hazard icon set.
 *
 * Drawn on a shared 24x24 grid with a 2.0 stroke and round joins. These are
 * built to survive being rendered at 15px inside a map marker, so each glyph
 * is a single bold silhouette rather than fine detail that turns to mush.
 *
 * Every hazard is distinguishable by SHAPE alone, not just colour, so the map
 * stays readable in greyscale and for colour-blind users. Severity is carried
 * separately by the marker's outer ring.
 */
const HAZARD_ICONS = {
  // Water — waves, rising level
  FLOOD: {
    d: '<path d="M2 17.5c2.2 0 2.2-1.9 4.4-1.9s2.2 1.9 4.4 1.9 2.2-1.9 4.4-1.9 2.2 1.9 4.4 1.9"/><path d="M2 21.5c2.2 0 2.2-1.9 4.4-1.9s2.2 1.9 4.4 1.9 2.2-1.9 4.4-1.9 2.2 1.9 4.4 1.9"/><path d="M6.5 13V7.2L12 3l5.5 4.2V13"/>',
  },
  HEAVY_RAIN: {
    d: '<path d="M6.6 13.6A4.1 4.1 0 0 1 7.4 5.5a5.7 5.7 0 0 1 10.8 1.7 3.6 3.6 0 0 1-.7 6.4"/><path d="M8.5 17v3M12 17.5v3.5M15.5 17v3"/>',
  },
  CLOUD_BURST: {
    d: '<path d="M6.6 12.6A4.1 4.1 0 0 1 7.4 4.5a5.7 5.7 0 0 1 10.8 1.7 3.6 3.6 0 0 1-.7 6.4"/><path d="M12 15v7"/><path d="M8.6 16.5 7.4 20M15.4 16.5l1.2 3.5"/>',
  },
  // Ocean
  HIGH_WAVE: {
    d: '<path d="M2 19.5c3 0 3-2.2 6-2.2s3 2.2 6 2.2 3-2.2 6-2.2"/><path d="M2.5 13.5C3.5 7 8.5 3.5 14 3.5c-2.5 3.6-2.8 8 0 11.4"/>',
  },
  STORM_SURGE: {
    d: '<path d="M2 20c3 0 3-2.2 6-2.2s3 2.2 6 2.2 3-2.2 6-2.2"/><path d="M3 14c4.5-6.5 9.5-8.5 14.5-8.5-2 3-2 6.5 0 9.5"/><path d="M19 4v3M22 6.5h-3"/>',
  },
  TSUNAMI: {
    d: '<path d="M2 20.5c3 0 3-2.2 6-2.2s3 2.2 6 2.2 3-2.2 6-2.2"/><path d="M2.5 15.5C2.5 7 8.5 2.5 15.5 2.5c-3.5 4-4 9-1 12.6"/><path d="M15 8.5c2.5.6 4.5 2.4 5.5 4.5"/>',
  },
  // Wind systems — spiral
  CYCLONE: {
    d: '<path d="M12 12c0-3.6 2.9-6.5 6.5-6.5M12 12c3.6 0 6.5 2.9 6.5 6.5M12 12c0 3.6-2.9 6.5-6.5 6.5M12 12c-3.6 0-6.5-2.9-6.5-6.5"/><circle cx="12" cy="12" r="1.9" fill="currentColor" stroke="none"/>',
  },
  GALE_WIND: {
    d: '<path d="M2 7.5h11.5A3.2 3.2 0 1 0 10.3 4"/><path d="M2 12.5h15A3.2 3.2 0 1 1 13.8 16"/><path d="M2 17.5h8.5A2.6 2.6 0 1 1 8 20.2"/>',
  },
  DUST_STORM: {
    d: '<path d="M2 7h10.5A2.6 2.6 0 1 0 10 4.2"/><path d="M2 11.5h13A2.6 2.6 0 1 1 12.5 15"/><path d="M3 16h11M5 20h10"/>',
  },
  // Electrical
  LIGHTNING: {
    d: '<path d="M13.8 2 5.5 13.2h5.2L9.5 22l9-11.6h-5.4z"/>',
    fill: true,
  },
  THUNDERSTORM: {
    d: '<path d="M6.6 12.8A4.1 4.1 0 0 1 7.4 4.7a5.7 5.7 0 0 1 10.8 1.7 3.6 3.6 0 0 1-.7 6.4"/><path d="M13.2 14 9.6 19.2h3.1L11.4 23l4.8-6.1h-3z"/>',
  },
  // Ground
  EARTHQUAKE: {
    d: '<path d="M1.5 12h3.2l2.4-6.5L10.6 18l2.8-9.5 2.3 5.5 1.8-3h5"/><path d="M4 20.5h5.5M14 20.5h6"/>',
  },
  LANDSLIDE: {
    d: '<path d="M2 20.5h20"/><path d="M2.5 20.5 11 5.5l3.6 6.3"/><circle cx="16.8" cy="14.6" r="1.9" fill="currentColor" stroke="none"/><circle cx="20.4" cy="18" r="1.5" fill="currentColor" stroke="none"/><circle cx="13.2" cy="17.6" r="1.3" fill="currentColor" stroke="none"/>',
  },
  AVALANCHE: {
    d: '<path d="M2 20.5h20"/><path d="M3.5 20.5 12 4l8.5 16.5"/><path d="M8 13c1.7 1.4 2.8-.9 4.5.5s2.5-.8 3.8.4"/>',
  },
  // Temperature
  HEATWAVE: {
    d: '<circle cx="12" cy="8.5" r="3.6"/><path d="M12 1.8v1.9M12 13.3v1.9M18.7 8.5h-1.9M7.2 8.5H5.3M16.8 3.7l-1.4 1.4M8.6 11.9l-1.4 1.4M16.8 13.3l-1.4-1.4M8.6 5.1 7.2 3.7"/><path d="M3 19c2.2 0 2.2-1.7 4.5-1.7S9.7 19 12 19s2.2-1.7 4.5-1.7S18.7 19 21 19"/>',
  },
  COLDWAVE: {
    d: '<path d="M12 2v20M3.3 7l17.4 10M3.3 17l17.4-10"/><path d="M9 4.3 12 6.8l3-2.5M9 19.7l3-2.5 3 2.5"/><path d="M5.6 10.9 4.7 7.3l3.6-.4M18.4 13.1l.9 3.6-3.6.4"/>',
  },
  DROUGHT: {
    d: '<circle cx="17" cy="6" r="3"/><path d="M2 17h20M4 21h16"/><path d="M8 17V9M8 12.5c0-2.2-1.8-4-4-4 0 2.2 1.8 4 4 4Z"/><path d="M8 13.5c0-1.8 1.5-3.2 3.2-3.2 0 1.8-1.4 3.2-3.2 3.2Z"/>',
  },
  // Other
  FOREST_FIRE: {
    d: '<path d="M12 22.5c4 0 6.8-2.7 6.8-6.3 0-3.8-3.1-5.7-4.4-9-.2 1.4-.9 2.6-2 3.4.2-2.6-.7-5.6-3.4-8.1.3 3-1.2 4.6-2.7 6.3-1.4 1.6-2.6 3.3-2.6 6.1 0 4.2 3.4 7.6 8.3 7.6Z"/>',
    fill: true,
  },
  FOG: {
    d: '<path d="M3 8.5h14M7 12.5h14M3 16.5h13M8 20.5h11"/>',
  },
  OTHER: {
    d: '<circle cx="12" cy="12" r="9.2"/><path d="M12 7.5v6M12 16.4v.3"/>',
  },
};

/* Colour per hazard: water blues, ocean teals, storm violets, fire ambers,
 * seismic magenta. Related hazards sit in related hues, but no two that can
 * appear side by side share one. */
const HAZARD_COLORS = {
  FLOOD: '#3d9bec', CLOUD_BURST: '#2b7fd4', HEAVY_RAIN: '#54acdd',
  STORM_SURGE: '#1fb0ae', HIGH_WAVE: '#25c7bf', TSUNAMI: '#0d9aa5',
  CYCLONE: '#7d6bf8', THUNDERSTORM: '#9280ea', LIGHTNING: '#e3b622',
  EARTHQUAKE: '#c065d8', LANDSLIDE: '#c4743d', AVALANCHE: '#93bcdc',
  FOREST_FIRE: '#f4692a', HEATWAVE: '#ec4f2c', DROUGHT: '#cf9530',
  COLDWAVE: '#5fd0ec', DUST_STORM: '#ad8b4c', FOG: '#94a1af',
  GALE_WIND: '#63b492', OTHER: '#7d8794',
};

const SEVERITY_RANK = { INFO: 0, MINOR: 1, MODERATE: 2, SEVERE: 3, EXTREME: 4 };

function hazardSvg(hazard, size = 18, color = null) {
  const spec = HAZARD_ICONS[hazard] || HAZARD_ICONS.OTHER;
  const stroke = color || HAZARD_COLORS[hazard] || HAZARD_COLORS.OTHER;
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"
    fill="${spec.fill ? stroke : 'none'}" stroke="${stroke}" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round" style="color:${stroke}">${spec.d}</svg>`;
}
