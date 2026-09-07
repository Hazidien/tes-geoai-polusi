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
let timeSeriesChart = null;

const el = (id) => document.getElementById(id);

const pollutantNames = {
  CO: 'Carbon Monoxide (CO)',
  NO2: 'Nitrogen Dioxide (NO₂)',
  SO2: 'Sulfur Dioxide (SO₂)'
};

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
  if (level) {
    const normalized = level.toLowerCase();
    badge.classList.add(normalized === 'good' ? 'good' : normalized);
  }
}

function showWelcome() {
  el('welcome').classList.remove('hidden');
}

function hideWelcome() {
  el('welcome').classList.add('hidden');
}

function closeChart() {
  el('chart-panel').hidden = true;
  if (timeSeriesChart) {
    timeSeriesChart.destroy();
    timeSeriesChart = null;
  }
}

function renderTimeSeries(data) {
  const series = data.time_series || [];
  if (!series.length) {
    closeChart();
    return;
  }

  const labels = series.map((item) => item.date.slice(0, 7));
  const values = series.map((item) => item.value);
  const title = `${pollutantNames[data.variable]} time series`;

  el('chart-title').textContent = title;
  el('chart-subtitle').textContent = `Monthly mean over the selected AOI • ${data.unit}`;
  el('chart-panel').hidden = false;

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
        pointRadius: 3,
        pointHoverRadius: 5,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => `${formatValue(context.parsed.y)} ${data.unit}`
          }
        }
      },
      scales: {
        x: { title: { display: true, text: 'Period' } },
        y: { title: { display: true, text: data.unit } }
      }
    }
  });
}

el('start-app').onclick = hideWelcome;
el('close-chart').onclick = closeChart;

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
  closeChart();
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
  const variable = el('variable').value;

  if (!start || !end) {
    status.textContent = 'Start and end dates are required.';
    return;
  }

  if (end <= start) {
    status.textContent = 'End date must be after start date.';
    return;
  }

  status.textContent = `Processing Sentinel-5P ${variable} in Google Earth Engine…`;
  el('run').disabled = true;
  closeChart();

  const body = {
    module: 'air_pollution',
    variable,
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
    el('thresholds').textContent = `AOI thresholds — P33: ${formatThreshold(thresholds.p33)} • P66: ${formatThreshold(thresholds.p66)} ${data.unit}`;
    el('note').textContent = data.note;
    el('results').hidden = false;

    if (resultLayer) map.removeLayer(resultLayer);
    if (data.map?.tile_url) {
      resultLayer = L.tileLayer(data.map.tile_url, { opacity: 0.65 }).addTo(map);
    }

    renderTimeSeries(data);
    status.textContent = `${pollutantNames[data.variable]} analysis complete.`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    el('run').disabled = false;
  }
};

showWelcome();
