/* Hazard icon set.
 *
 * One shared 24x24 grid, 1.7 stroke weight, round caps. Designed as a family
 * so the map reads as one system. Each hazard is distinguishable by SHAPE
 * alone, not only colour, so the map stays legible in greyscale and for
 * colour-blind users - severity is carried separately by the marker ring.
 */
const HAZARD_ICONS = {
  FLOOD: '<path d="M2 16c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/><path d="M2 20.5c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/><path d="M6 11V5.5A1.5 1.5 0 0 1 7.5 4h9A1.5 1.5 0 0 1 18 5.5V11"/><path d="M9.5 11V7.5h5V11"/>',
  CYCLONE: '<path d="M12 12c0-3.3 2.7-6 6-6M12 12c3.3 0 6 2.7 6 6M12 12c0 3.3-2.7 6-6 6M12 12c-3.3 0-6-2.7-6-6"/><circle cx="12" cy="12" r="2.2"/>',
  EARTHQUAKE: '<path d="M2 12h3l2.5-6 3 12 3-9 2.5 6 2-3h4"/><path d="M4 18.5h16"/>',
  FOREST_FIRE: '<path d="M12 22c3.9 0 6.5-2.6 6.5-6 0-3.6-3-5.4-4.2-8.6C13.6 5 13.8 3 13.8 2c-2 1.2-4.6 3.6-4.6 7 0 1.6.6 2.6.6 3.4 0 1-.8 1.8-1.7 1.8-1 0-1.6-.8-1.6-2.2-1.2 1.3-1 3-1 4C5.5 19.4 8.1 22 12 22Z"/>',
  LANDSLIDE: '<path d="M2 20h20"/><path d="M3 20 11 6l4 6"/><circle cx="16.5" cy="14.5" r="1.6"/><circle cx="20" cy="17.5" r="1.3"/><circle cx="12.5" cy="17" r="1.1"/>',
  AVALANCHE: '<path d="M2 20h20"/><path d="M4 20 12 4l8 16"/><path d="M8.5 12.5c1.5 1.2 2.5-.8 4 .4s2.2-.7 3.4.4"/>',
  CLOUD_BURST: '<path d="M7 15a4 4 0 0 1 .5-8 5.5 5.5 0 0 1 10.4 1.6A3.6 3.6 0 0 1 17.5 15"/><path d="M9 18l-1 3M12.5 18l-1 3M16 18l-1 3"/><path d="M12 17.5v4"/>',
  FLOOD_URBAN: '<path d="M2 18c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2"/>',
  STORM_SURGE: '<path d="M2 19c3 0 3-2.5 6-2.5s3 2.5 6 2.5 3-2.5 6-2.5"/><path d="M3 13.5c4-6 8.5-8 13-8-1.5 2.5-1.5 5.5 0 8Z"/>',
  HIGH_WAVE: '<path d="M2 18.5c3 0 3-2 6-2s3 2 6 2 3-2 6-2"/><path d="M2 12.5c2-5 6.5-7.5 11-7.5-2 3-2 6.5 0 9.5"/>',
  TSUNAMI: '<path d="M2 20c3 0 3-2 6-2s3 2 6 2 3-2 6-2"/><path d="M2 15c0-7 5-11 11-11-3 3.5-3.5 8-1 11.5"/><path d="M17 8.5c2 .5 3.5 2 4.5 3.5"/>',
  DUST_STORM: '<path d="M2 8h11a2.5 2.5 0 1 0-2.5-2.5"/><path d="M2 12h15a2.5 2.5 0 1 1-2.5 2.5"/><path d="M2 16h9"/><path d="M4 20h11"/>',
  THUNDERSTORM: '<path d="M7 14a4 4 0 0 1 .5-8 5.5 5.5 0 0 1 10.4 1.6A3.6 3.6 0 0 1 17.5 14"/><path d="M13 12.5 9.5 18h3.2L11 22.5"/>',
  LIGHTNING: '<path d="M13.5 2 5 13.5h5.5L9 22l9-12h-5.5z"/>',
  HEAVY_RAIN: '<path d="M7 14.5a4 4 0 0 1 .5-8A5.5 5.5 0 0 1 17.9 8 3.6 3.6 0 0 1 17.5 14.5"/><path d="M8 17.5 6.8 21M12 17.5 10.8 21M16 17.5 14.8 21"/>',
  HEATWAVE: '<circle cx="12" cy="9.5" r="4"/><path d="M12 2v1.8M12 15.2V17M19.5 9.5h-1.8M6.3 9.5H4.5M17.3 4.2l-1.3 1.3M8 13.5l-1.3 1.3M17.3 14.8 16 13.5M8 5.5 6.7 4.2"/><path d="M3 20c2 0 2-1.5 4-1.5S9 20 11 20s2-1.5 4-1.5S17 20 19 20"/>',
  COLDWAVE: '<path d="M12 2v20M3.5 7l17 10M3.5 17l17-10"/><path d="M9 4.5 12 7l3-2.5M9 19.5 12 17l3 2.5"/>',
  DROUGHT: '<path d="M12 3v11"/><path d="M12 9c0-2.5 2-4.5 4.5-4.5C16.5 7 14.5 9 12 9Z"/><path d="M12 12c0-2.5-2-4.5-4.5-4.5C7.5 10 9.5 12 12 12Z"/><path d="M3 18h18M5 21.5h14"/>',
  FOG: '<path d="M3 9h13M6 13h15M3 17h12M8 21h11"/>',
  GALE_WIND: '<path d="M2 7h12a3 3 0 1 0-3-3"/><path d="M2 12h16a3 3 0 1 1-3 3"/><path d="M2 17h9a2.5 2.5 0 1 1-2.5 2.5"/>',
  OTHER: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.2v.3"/>',
};

/* Colour per hazard. Chosen for contrast against the dark map ground and to
 * keep related hazards in related hues (water blues, fire ambers, seismic
 * violets) without any two adjacent hues colliding. */
const HAZARD_COLORS = {
  FLOOD: '#3b9ae1', CLOUD_BURST: '#2f7fd1', HEAVY_RAIN: '#4aa8d8',
  STORM_SURGE: '#2bb3b3', HIGH_WAVE: '#25c2c2', TSUNAMI: '#0e9ba3',
  CYCLONE: '#7b6ef6', THUNDERSTORM: '#8f7ce8', LIGHTNING: '#c9a227',
  EARTHQUAKE: '#b061d8', LANDSLIDE: '#c2703f', AVALANCHE: '#8fb6d6',
  FOREST_FIRE: '#ef6c2e', HEATWAVE: '#e8562f', DROUGHT: '#c9922e',
  COLDWAVE: '#5fc8e8', DUST_STORM: '#a8894f', FOG: '#8d99a6',
  GALE_WIND: '#6fae8c', OTHER: '#7d8794',
};

const SEVERITY_RANK = { INFO: 0, MINOR: 1, MODERATE: 2, SEVERE: 3, EXTREME: 4 };

function hazardSvg(hazard, size = 18, color = null) {
  const paths = HAZARD_ICONS[hazard] || HAZARD_ICONS.OTHER;
  const stroke = color || HAZARD_COLORS[hazard] || HAZARD_COLORS.OTHER;
  const filled = hazard === 'LIGHTNING' || hazard === 'FOREST_FIRE';
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="${filled ? stroke : 'none'}"
    stroke="${stroke}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}
