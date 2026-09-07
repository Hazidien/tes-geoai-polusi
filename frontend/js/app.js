const map = L.map('map').setView([-7.25, 112.75], 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors'
}).addTo(map);

map.pm.addControls({
  position: 'topleft',
  drawPolygon: true,
  drawRectangle: true,
  drawCircle: false,
  drawMarker: false,
  drawCircleMarker: false,
  drawPolyline: false,
  editMode: true,
  dragMode: false,
  cutPolygon: false,
  removalMode: true
});

let aoiLayer = null;
let resultLayer = null;

const el = (id) => document.getElementById(id);

function formatValue(value) {
  return Number(value).toExponential(4);
}

function formatThreshold(value) {
  return value == null ? '—' : Number(value).toExponential(3);
}

function setLevel(level) {
  const badge = el('level');
  badge.textContent = level || '—';
  badge.className = 'level-badge';
  if (level) badge.classList.add(level.toLowerCase().replace(' ', '-'));
}

function showWelcome() {
  el('welcome').classList.remove('hidden');
}

function hideWelcome() {
  el('welcome').classList.add('hidden');
}

el('start-app').onclick = hideWelcome;

map.on('pm:create', (e) => {
  if (aoiLayer) map.removeLayer(aoiLayer);
  aoiLayer = e.layer;
  aoiLayer.addTo(map);
});

el('clear').onclick = () => {
  if (aoiLayer) map.removeLayer(aoiLayer);
  aoiLayer = null;
  if (resultLayer) map.removeLayer(resultLayer);
  resultLayer = null;
  el('results').hidden = true;
  setLevel(null);
  el('status').textContent = 'Draw a polygon or rectangle on the map.';
};

el('pdf').onclick = () => {
  if (el('results').hidden) {
    el('status').textContent = 'Run an analysis first, then export the result to PDF.';
    return;
  }
  window.print();
};

el('run').onclick = async () => {
  const status = el('status');

  if (!aoiLayer) {
    status.textContent = 'Please draw an AOI first.';
    return;
  }

  const start = el('start').value;
  const end = el('end').value;

  if (!start || !end) {
    status.textContent = 'Start and end dates are required.';
    return;
  }

  if (end <= start) {
    status.textContent = 'End date must be after start date.';
    return;
  }

  status.textContent = 'Processing Sentinel-5P CO in Google Earth Engine…';
  el('run').disabled = true;

  const body = {
    module: 'air_pollution',
    variable: 'CO',
    aoi: aoiLayer.toGeoJSON().geometry,
    start_date: start,
    end_date: end,
    aggregation: el('aggregation').value
  };

  try {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Analysis failed');

    el('value').textContent = formatValue(data.value);
    el('unit').textContent = data.unit;
    el('images').textContent = data.image_count;
    el('dates').textContent = `${data.start_date} → ${data.end_date}`;

    const classification = data.classification || {};
    setLevel(classification.level);
    el('classification').textContent = classification.level
      ? `Relative interpretation: ${classification.level}`
      : 'Relative interpretation unavailable.';

    const thresholds = classification.thresholds || {};
    el('thresholds').textContent = `AOI thresholds — P25: ${formatThreshold(thresholds.p25)} • P50: ${formatThreshold(thresholds.p50)} • P75: ${formatThreshold(thresholds.p75)} ${data.unit}`;
    el('note').textContent = data.note;
    el('results').hidden = false;

    if (resultLayer) map.removeLayer(resultLayer);
    if (data.map?.tile_url) {
      resultLayer = L.tileLayer(data.map.tile_url, { opacity: 0.65 }).addTo(map);
    }

    status.textContent = 'Analysis complete.';
  } catch (error) {
    status.textContent = error.message;
  } finally {
    el('run').disabled = false;
  }
};

// The application opens with a short project introduction.
showWelcome();
