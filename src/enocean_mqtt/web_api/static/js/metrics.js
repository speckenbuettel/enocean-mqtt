const metricsStatus = document.getElementById('metricsStatus');
const metricsStatusText = document.getElementById('metricsStatusText');
const rangeButtons = [...document.querySelectorAll('.metrics-range-button')];

const ACTIVITY_RANGES = {
  '1h': { label: '1 h' },
  '24h': { label: '24 h' },
  '3d': { label: '3 d' },
  '7d': { label: '7 d' },
  '30d': { label: '30 d' },
};

let selectedActivityRange = '24h';
let activityRefreshInProgress = false;

function text(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function number(value, digits = 0) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '\u2013';
  return numeric.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function rate(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '\u2013';
  return number(numeric, numeric < 10 ? 1 : 0);
}

function interval(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '\u2013';
  if (numeric === 0) return '0 s';
  return `${number(numeric, numeric < 10 ? 2 : 1)} s`;
}

function displayLastRx(value) {
  if (value === null || value === undefined || value === '') return '\u2013';
  if (typeof value === 'string') return value;
  if (typeof value === 'object') {
    return value.raw_telegram || value.raw || value.data || JSON.stringify(value);
  }
  return String(value);
}

function setStatus(label, state) {
  if (!metricsStatus || !metricsStatusText) return;
  metricsStatus.classList.remove('ok', 'neutral', 'problem', 'warn');
  metricsStatus.classList.add(state);
  metricsStatusText.textContent = label;
}

async function apiJson(url) {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function renderRorgMetrics(rorg) {
  const body = document.getElementById('rorgBody');
  if (!body) return;
  const entries = Object.entries(rorg || {}).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) {
    body.innerHTML = '<tr><td colspan="3">No RORG metrics available</td></tr>';
    return;
  }
  body.innerHTML = entries.map(([name, item]) => {
    const metric = item && typeof item === 'object' ? item : {};
    return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(number(metric.telegrams_total))}</td><td>${escapeHtml(rate(metric.telegrams_per_minute))}</td></tr>`;
  }).join('');
}

function renderUnknownRorgMetrics(rorg) {
  const body = document.getElementById('unknownRorgBody');
  if (!body) return;
  const entries = Object.entries(rorg || {}).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) {
    body.innerHTML = '<tr><td colspan="4">No unknown-device traffic</td></tr>';
    return;
  }
  body.innerHTML = entries.map(([name, item]) => {
    const metric = item && typeof item === 'object' ? item : {};
    return `<tr><td>${escapeHtml(name)}</td><td>${escapeHtml(number(metric.unique_senders))}</td><td>${escapeHtml(number(metric.telegrams_total))}</td><td>${escapeHtml(rate(metric.telegrams_per_minute))}</td></tr>`;
  }).join('');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function activityLabel(value, compact = false) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (item) => String(item).padStart(2, '0');
  if (compact) return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function chartLabel(index, length, bucket, rangeKey) {
  const step = length > 28 ? 6 : length > 18 ? 4 : 2;
  if (index % step !== 0 && index !== length - 1) return '';
  return activityLabel(bucket.start, rangeKey === '1h');
}

function activityScale(values) {
  const rawMaximum = Math.max(0, ...values.filter(Number.isFinite));
  if (rawMaximum <= 0) return { maximum: 1, ticks: [1, 0] };

  const targetStep = rawMaximum / 4;
  const magnitude = 10 ** Math.floor(Math.log10(targetStep));
  const normalized = targetStep / magnitude;
  const factor = normalized <= 1 ? 1
    : normalized <= 2 ? 2
      : normalized <= 2.5 ? 2.5
        : normalized <= 5 ? 5 : 10;
  const step = Math.max(1, factor * magnitude);
  const maximum = Math.ceil(rawMaximum / step) * step;
  const ticks = [];
  for (let value = maximum; value >= 0; value -= step) {
    ticks.push(Math.max(0, Math.round(value)));
  }
  if (ticks[ticks.length - 1] !== 0) ticks.push(0);
  return { maximum, ticks: [...new Set(ticks)] };
}

function activityChartFrame(bucketMarkup, scale) {
  const tickMarkup = scale.ticks.map((value) => {
    const position = (1 - value / scale.maximum) * 100;
    return `<span class="metric-chart-y-tick" style="--tick-position:${position}">${escapeHtml(number(value))}</span>`;
  }).join('');
  const lineMarkup = scale.ticks.map((value) => {
    const position = (1 - value / scale.maximum) * 100;
    return `<span class="metric-chart-grid-line" style="--tick-position:${position}"></span>`;
  }).join('');
  return `<div class="metric-chart-y-axis" aria-hidden="true">${tickMarkup}</div><div class="metric-chart-plot"><div class="metric-chart-grid-lines" aria-hidden="true">${lineMarkup}</div><div class="metric-chart-buckets">${bucketMarkup}</div></div>`;
}

function renderRxActivityChart(buckets, rangeKey) {
  const chart = document.getElementById('rxChart');
  if (!chart) return;
  if (!Array.isArray(buckets) || buckets.length === 0) {
    chart.innerHTML = '<div class="metric-chart-empty">No activity data available</div>';
    return;
  }

  const values = buckets.flatMap((bucket) => [
    Number(bucket?.rx?.known ?? 0),
    Number(bucket?.rx?.unknown ?? 0),
  ]);
  chart.style.setProperty('--chart-columns', String(buckets.length));
  const scale = activityScale(values);
  const bucketMarkup = buckets.map((bucket, index) => {
    const known = Number(bucket?.rx?.known ?? 0);
    const unknown = Number(bucket?.rx?.unknown ?? 0);
    const label = chartLabel(index, buckets.length, bucket, rangeKey);
    const segments = ['original_telegrams', 'repeated_telegrams', 'unclassified_telegrams'];
    const labels = ['Original', 'Repeated', 'Unclassified'];
    const bar = (category, total) => {
      const counts = segments.map((key) => Number(bucket?.rx?.[key]?.[category] ?? 0));
      // Older API responses have no breakdown; preserve their total as unclassified.
      counts[2] += Math.max(0, total - counts.reduce((sum, value) => sum + value, 0));
      const tooltip = labels.map((name, i) => `${name} ${number(counts[i])}`).join(' | ');
      const height = total / scale.maximum * 100;
      const parts = counts.map((count, i) => `<span class="rx-segment ${segments[i]}" style="height:${total ? count / total * 100 : 0}%"></span>`).join('');
      return `<span class="metric-chart-bar rx-stack ${category}" style="height:${height}%" title="${escapeHtml(`${activityLabel(bucket.start)} | ${category}: ${tooltip}`)}">${parts}</span>`;
    };
    return `<div class="metric-chart-bucket"><div class="metric-chart-bar-area"><div class="metric-chart-bars">${bar('known', known)}${bar('unknown', unknown)}</div></div><div class="metric-chart-label">${escapeHtml(label)}</div></div>`;
  }).join('');
  chart.innerHTML = activityChartFrame(bucketMarkup, scale);
}

function renderTxActivityChart(buckets, rangeKey) {
  const chart = document.getElementById('txChart');
  if (!chart) return;
  if (!Array.isArray(buckets) || buckets.length === 0) {
    chart.innerHTML = '<div class="metric-chart-empty">No activity data available</div>';
    return;
  }

  const values = buckets.map((bucket) => Number(bucket?.tx ?? 0));
  chart.style.setProperty('--chart-columns', String(buckets.length));
  const scale = activityScale(values);
  const bucketMarkup = buckets.map((bucket, index) => {
    const total = Number(bucket?.tx ?? 0);
    const height = total > 0 ? Math.max(2, total / scale.maximum * 100) : 0;
    const label = chartLabel(index, buckets.length, bucket, rangeKey);
    const tooltip = `${activityLabel(bucket.start)} | TX ${number(total)}`;
    return `<div class="metric-chart-bucket" title="${escapeHtml(tooltip)}"><div class="metric-chart-bar-area"><div class="metric-chart-bars"><span class="metric-chart-bar tx" style="height:${height}%"></span></div></div><div class="metric-chart-label">${escapeHtml(label)}</div></div>`;
  }).join('');
  chart.innerHTML = activityChartFrame(bucketMarkup, scale);
}

function renderMetrics(busmonitor, gateway) {
  const rx = busmonitor.rx || {};
  const tx = busmonitor.tx || {};
  const decoder = busmonitor.decoder || {};
  const unknown = busmonitor.unknown_devices || {};
  const devices = gateway.devices || {};

  text('rxRate', rate(rx.telegrams_per_minute));
  text('rxTotal', `${number(rx.telegrams_total)} total`);
  text('txRate', rate(tx.telegrams_per_minute));
  text('txTotal', `${number(tx.telegrams_total)} total`);
  text('decodedTotal', number(decoder.decoded_telegrams_total));
  text('decodeErrors', number(decoder.decode_errors_total));
  text('knownDevices', number(devices.known_devices_total));
  text('unknownDevices', number(unknown.devices_total ?? devices.unknown_devices_total));

  text('rxMeanInterval', interval(rx.telegram_mean_interval_seconds));
  text('rxPeak', rate(rx.peak_telegrams_per_minute));
  text('rxRepeated', number(rx.repeated_telegrams_total));
  text('rxOriginal', number(rx.original_telegrams?.telegrams_total));
  text('rxOriginalRate', rate(rx.original_telegrams?.telegrams_per_minute));
  text('rxRepeatedRate', rate(rx.repeated_telegrams?.telegrams_per_minute));
  text('txMeanInterval', interval(tx.telegram_mean_interval_seconds));
  text('unknownTelegrams', number(unknown.telegrams_total));

  text('activeDevices', number(devices.active_devices_total));
  text('gatewayKnownDevices', number(devices.known_devices_total));
  text('gatewayUnknownDevices', number(devices.unknown_devices_total));
  text('lastSender', gateway.last_sender_id || busmonitor.last_sender_id || '\u2013');
  text('lastRorg', busmonitor.last_rorg || '\u2013');

  text('observationSender', busmonitor.last_sender_id || gateway.last_sender_id || '\u2013');
  text('observationRorg', busmonitor.last_rorg || '\u2013');
  text('lastRx', displayLastRx(busmonitor.last_rx ?? gateway.last_rx));

  renderRorgMetrics(busmonitor.rorg);
  renderUnknownRorgMetrics(unknown.rorg);
}

async function refreshActivity() {
  if (activityRefreshInProgress) return;
  activityRefreshInProgress = true;
  const rangeKey = selectedActivityRange;
  const range = ACTIVITY_RANGES[rangeKey];

  try {
    const payload = await apiJson(`/api/v1/busmonitor/metrics/telegram-activity?range=${encodeURIComponent(rangeKey)}`);
    if (rangeKey !== selectedActivityRange) return;
    const buckets = payload.buckets || [];
    renderRxActivityChart(buckets, rangeKey);
    renderTxActivityChart(buckets, rangeKey);
    text('rxChartRange', range.label);
    text('txChartRange', range.label);
  } catch (error) {
    console.warn('Failed to load telegram activity', error);
    const rxChart = document.getElementById('rxChart');
    const txChart = document.getElementById('txChart');
    if (rxChart) rxChart.innerHTML = '<div class="metric-chart-empty">Activity data unavailable</div>';
    if (txChart) txChart.innerHTML = '<div class="metric-chart-empty">Activity data unavailable</div>';
  } finally {
    activityRefreshInProgress = false;
  }
}

async function refreshMetrics() {
  try {
    const [busmonitor, gateway] = await Promise.all([
      apiJson('/api/v1/gateway/busmonitor-metrics'),
      apiJson('/api/v1/gateway/metrics'),
    ]);

    renderMetrics(busmonitor, gateway);
    setStatus('Collecting', 'ok');
  } catch (error) {
    console.warn('Failed to load EnOcean metrics', error);
    setStatus('Data unavailable', 'problem');
  }
}

for (const button of rangeButtons) {
  button.addEventListener('click', () => {
    const rangeKey = button.dataset.range;
    if (!ACTIVITY_RANGES[rangeKey] || rangeKey === selectedActivityRange) return;
    selectedActivityRange = rangeKey;
    for (const item of rangeButtons) item.classList.toggle('active', item === button);
    refreshActivity();
  });
}

refreshMetrics();
refreshActivity();
setInterval(refreshMetrics, 30000);
setInterval(refreshActivity, 5 * 60 * 1000);
