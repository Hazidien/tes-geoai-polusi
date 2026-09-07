const map = L.map('map').setView([-7.25, 112.75], 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap contributors' }).addTo(map);

map.pm.addControls({
  position: 'topleft', drawPolygon: true, drawRectangle: true, drawCircle: false,
  drawMarker: false, drawCircleMarker: false, drawPolyline: false, editMode: true,
  dragMode: false, cutPolygon: false, removalMode: true
});

let aoiLayer = null;
let resultLayer = null;
let uploadedLayer = null;
let timeSeriesChart = null;
let latestTimeSeriesData = null;
let geotiffUrl = null;
const el = (id) => document.getElementById(id);

const pollutantNames = {
  CO: 'Carbon Monoxide (CO)', NO2: 'Nitrogen Dioxide (NO₂)', SO2: 'Sulfur Dioxide (SO₂)'
};

function formatValue(value) { return Number(value).toExponential(4); }
function formatThreshold(value) { return value == null ? '—' : Number(value).toExponential(3); }

function setLevel(level) {
  const badge = el('level');
  badge.textContent = level || '—';
  badge.className = 'level-badge';
  if (level) badge.classList.add(level.toLowerCase() === 'good' ? 'good' : level.toLowerCase());
}

function closeChart() {
  el('chart-panel').hidden = true;
  el('show-chart').hidden = !latestTimeSeriesData;
  if (timeSeriesChart) { timeSeriesChart.destroy(); timeSeriesChart = null; }
}

function renderTimeSeries(data) {
  const series = data.time_series || [];
  latestTimeSeriesData = data;
  if (!series.length) {
    closeChart();
    el('show-chart').hidden = true;
    return;
  }

  const labels = series.map((item) => item.date.slice(0, 7));
  const values = series.map((item) => item.value);
  el('chart-title').textContent = `${pollutantNames[data.variable]} time series`;
  el('chart-subtitle').textContent = series.length === 1
    ? `Monthly mean over the selected AOI • ${data.unit} • 1 month`
    : `Monthly mean over the selected AOI • ${data.unit}`;
  el('chart-panel').hidden = false;
  el('show-chart').hidden = true;
  if (timeSeriesChart) timeSeriesChart.destroy();

  timeSeriesChart = new Chart(el('time-series-chart'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: data.variable,
        data: values,
        tension: 0.25,
        fill: false,
        pointRadius: 4,
        pointHoverRadius: 6,
        borderWidth: 2,
        spanGaps: true
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (context) => `${formatValue(context.parsed.y)} ${data.unit}` } }
      },
      scales: {
        x: { title: { display: true, text: 'Period' }, offset: series.length === 1 },
        y: {
          title: { display: true, text: data.unit },
          ticks: { callback: (value) => Number(value).toExponential(2) },
          beginAtZero: false
        }
      }
    }
  });
}

function setAoiLayer(layer) {
  if (aoiLayer) map.removeLayer(aoiLayer);
  aoiLayer = layer;
  if (aoiLayer) aoiLayer.addTo(map);
}

function clearResults() {
  if (resultLayer) map.removeLayer(resultLayer);
  resultLayer = null;
  el('results').hidden = true;
  setLevel(null);
  geotiffUrl = null;
  el('geotiff').disabled = true;
  latestTimeSeriesData = null;
  el('show-chart').hidden = true;
  closeChart();
}

el('start-app').onclick = () => el('welcome').classList.add('hidden');
el('close-chart').onclick = closeChart;
el('show-chart').onclick = () => {
  if (latestTimeSeriesData) renderTimeSeries(latestTimeSeriesData);
};

map.on('pm:create', (e) => {
  setAoiLayer(e.layer);
  if (uploadedLayer) { map.removeLayer(uploadedLayer); uploadedLayer = null; }
  el('upload-status').textContent = 'Drawn AOI selected on the map.';
});

el('shp-upload').onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const status = el('upload-status');
  status.textContent = 'Uploading and reading shapefile…';
  const formData = new FormData();
  formData.append('file', file);
  try {
    const response = await fetch('/api/aoi/upload', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Shapefile upload failed.');
    const geojson = L.geoJSON(data.geometry, { style: { weight: 2, fillOpacity: 0.08 } });
    if (uploadedLayer) map.removeLayer(uploadedLayer);
    uploadedLayer = geojson.addTo(map);
    setAoiLayer(L.geoJSON(data.geometry, { style: { weight: 2, fillOpacity: 0.05 } }));
    map.fitBounds(uploadedLayer.getBounds(), { padding: [30, 30] });
    status.textContent = `${data.filename}: ${data.feature_count} polygon feature(s) loaded. Temporary AOI only.`;
  } catch (error) {
    status.textContent = error.message;
    event.target.value = '';
  }
};

el('clear').onclick = () => {
  if (aoiLayer) map.removeLayer(aoiLayer);
  if (uploadedLayer) map.removeLayer(uploadedLayer);
  aoiLayer = null; uploadedLayer = null;
  clearResults();
  el('shp-upload').value = '';
  el('upload-status').textContent = 'Required: .shp + .shx + .dbf + .prj inside the ZIP. Max 20 MB.';
  el('status').textContent = 'Draw a polygon or rectangle on the map.';
};

el('pdf').onclick = () => {
  if (el('results').hidden) {
    el('status').textContent = 'Run an analysis first, then export the result to PDF.';
    return;
  }
  window.print();
};

el('geotiff').onclick = () => {
  if (!geotiffUrl) return;
  window.open(geotiffUrl, '_blank', 'noopener');
};

el('run').onclick = async () => {
  const status = el('status');
  if (!aoiLayer) return void (status.textContent = 'Please draw an AOI or upload a Shapefile ZIP first.');
  const start = el('start').value;
  const end = el('end').value;
  const variable = el('variable').value;
  if (!start || !end) return void (status.textContent = 'Start and end dates are required.');
  if (end <= start) return void (status.textContent = 'End date must be after start date.');

  status.textContent = `Processing Sentinel-5P ${variable} in Google Earth Engine…`;
  el('run').disabled = true;
  clearResults();

  const body = {
    module: 'air_pollution', variable, aoi: aoiLayer.toGeoJSON().geometry,
    start_date: start, end_date: end, aggregation: el('aggregation').value
  };

  try {
    const response = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Analysis failed');

    el('value').textContent = formatValue(data.value);
    el('unit').textContent = data.unit;
    el('images').textContent = data.image_count;
    el('dates').textContent = `${data.start_date} → ${data.end_date}`;
    const classification = data.classification || {};
    setLevel(classification.level);
    el('classification').textContent = classification.level ? `Relative interpretation: ${classification.level}` : 'Relative interpretation unavailable.';
    const thresholds = classification.thresholds || {};
    el('thresholds').textContent = `AOI thresholds — P33: ${formatThreshold(thresholds.p33)} • P66: ${formatThreshold(thresholds.p66)} ${data.unit}`;
    el('note').textContent = data.note;
    el('results').hidden = false;

    if (resultLayer) map.removeLayer(resultLayer);
    if (data.map?.tile_url) resultLayer = L.tileLayer(data.map.tile_url, { opacity: 0.65 }).addTo(map);
    geotiffUrl = data.downloads?.geotiff_url || null;
    el('geotiff').disabled = !geotiffUrl;
    renderTimeSeries(data);
    status.textContent = `${pollutantNames[data.variable]} analysis complete.`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    el('run').disabled = false;
  }
};

el('start').value = '2025-01-01';
el('end').value = '2025-12-31';
