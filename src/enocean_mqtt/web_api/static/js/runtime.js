const statusBox = document.getElementById('systemStatus');
const $ = (id) => document.getElementById(id);
const setText = (id, value) => { if ($(id)) $(id).textContent = value ?? '–'; };
const esc = (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');

function duration(seconds) {
  const n = Number(seconds); if (!Number.isFinite(n)) return '–';
  const d = Math.floor(n / 86400), h = Math.floor((n % 86400) / 3600), m = Math.floor((n % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}
function bytes(value) {
  let n = Number(value); if (!Number.isFinite(n)) return '–';
  const units = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n.toLocaleString(undefined, { maximumFractionDigits: i ? 1 : 0 })} ${units[i]}`;
}
function state(value, good = 'operational', bad = 'unavailable') { return value ? good : bad; }
async function apiJson(url) { const response = await fetch(url, { headers: { Accept: 'application/json' } }); if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }
function setStatus(label, css) { statusBox.classList.remove('ok', 'neutral', 'problem', 'warn'); statusBox.classList.add(css); setText('systemStatusText', label); }

function renderInterfaces(enocean) {
  const items = Array.isArray(enocean?.interfaces) ? enocean.interfaces : [];
  $('interfaceBody').innerHTML = items.length ? items.map((item) => {
    const metrics = item.metrics || {};
    const rx = metrics.rx_packets ?? metrics.packets_received ?? '–';
    const errors = metrics.errors ?? metrics.parse_errors ?? metrics.invalid_packets ?? '–';
    return `<tr><td>${esc(item.interface_id || '–')}</td><td><span class="state ${item.connected ? 'ok' : 'problem'}"><span class="status-dot"></span>${item.connected ? 'connected' : 'disconnected'}</span></td><td>${esc(item.port || '–')}</td><td>${esc(item.base_id || '–')}</td><td>${item.tx_enabled ? 'enabled' : 'disabled'}</td><td>${esc(rx)}</td><td>${esc(errors)}</td></tr>`;
  }).join('') : '<tr><td colspan="7">No interfaces reported</td></tr>';
}

function renderSystem(payload) {
  const health = payload.health || {}, metrics = payload.system_metrics || {}, mqtt = health.mqtt || {};
  const load = mqtt.message_load_15mins || mqtt.message_load || {}, sqlite = health.sqlite || {}, registry = health.device_registry || {};
  const webApi = health.web_api || {}, webUi = health.web_ui || {}, enocean = health.enocean || {};
  const online = payload.status === 'online'; setStatus(online ? 'Running' : 'Unavailable', online ? 'ok' : 'problem');
  setText('serviceUptime', duration(payload.uptime_seconds)); setText('processMemory', health.memory_rss_mb == null ? '–' : `${health.memory_rss_mb} MB`);
  setText('serviceUptimeDetail', duration(payload.uptime_seconds)); setText('processMemoryDetail', health.memory_rss_mb == null ? '–' : `${health.memory_rss_mb} MiB`);
  setText('hostCpu', `${Number(metrics.cpu_percent || 0).toLocaleString(undefined, { maximumFractionDigits: 1 })} %`); setText('hostMemory', `${Number(metrics.memory_percent || 0).toLocaleString(undefined, { maximumFractionDigits: 1 })} %`); setText('diskUsage', `${Number(metrics.disk_percent || 0).toLocaleString(undefined, { maximumFractionDigits: 1 })} %`);
  setText('mqttLoad', Number(load.published || 0) + Number(load.received || 0)); setText('mqttLoadDetail', `${load.published || 0} published · ${load.received || 0} received`);
  setText('runtimeStatus', payload.status); setText('runtimeMode', payload.runtime_mode); setText('runtimeVersion', payload.version); setText('hostUptime', duration(metrics.host_uptime_seconds)); setText('healthTimestamp', health.timestamp_local || health.timestamp_utc || '–');
  setText('mqttStatus', state(mqtt.connected, 'connected', 'disconnected')); setText('mqttBroker', mqtt.host ? `${mqtt.host}:${mqtt.port || '–'}` : '–'); setText('mqttClientId', mqtt.client_id); setText('mqttUptime', duration(mqtt.uptime_seconds)); setText('mqttReconnects', mqtt.reconnects ?? 0); setText('mqttPublished', load.published ?? 0); setText('mqttReceived', load.received ?? 0);
  const interfaces = Array.isArray(enocean.interfaces) ? enocean.interfaces : [], selected = interfaces.find((item) => item.interface_id === enocean.default_interface) || interfaces[0] || {};
  setText('enoceanStatus', state(enocean.connected, 'connected', 'disconnected')); setText('enoceanCount', interfaces.length); setText('enoceanDefault', selected.interface_id || enocean.default_interface); setText('enoceanBaseId', selected.base_id); setText('enoceanRx', selected.connected ? 'enabled' : 'disabled'); setText('enoceanTx', selected.tx_enabled ? 'enabled' : 'disabled');
  setText('sqliteStatus', sqlite.enabled ? state(sqlite.operational) : 'disabled'); setText('sqliteSize', bytes(sqlite.database_size_bytes)); setText('registryDevices', registry.devices_total); setText('registryReload', registry.last_reload); setText('diskFree', bytes(metrics.disk_free_bytes));
  setText('webApiStatus', webApi.enabled ? state(webApi.operational) : 'disabled'); setText('webUiStatus', webUi.enabled ? state(webUi.operational) : 'disabled'); setText('logLevel', payload.logging?.level); setText('logFormat', payload.logging?.format); setText('logDestination', payload.logging?.destination); renderInterfaces(enocean);
}
async function refreshSystem() { try { renderSystem(await apiJson('/api/v1/ui/system')); } catch (error) { console.warn(error); setStatus('Data unavailable', 'problem'); } }
let currentLogEntries = [];
async function refreshLogs() {
  const params = new URLSearchParams({ limit: $('logLimit').value }), level = $('logLevelFilter').value, search = $('logSearch').value.trim();
  if (level) params.set('level', level); if (search) params.set('search', search);
  try {
    const payload = await apiJson(`/api/v1/ui/system/logs?${params}`), entries = payload.entries || [];
    currentLogEntries = entries;
    setText('logMeta', payload.available ? `${entries.length} entries · newest first` : payload.error || 'journal unavailable');
    $('logBody').innerHTML = entries.length ? entries.map((entry) => `<tr><td>${esc(entry.timestamp || '–')}</td><td><span class="log-level level-${esc(entry.level.toLowerCase())}">${esc(entry.level)}</span></td><td>${esc(entry.logger)}</td><td class="log-message">${esc(entry.message)}</td></tr>`).join('') : '<tr><td colspan="4">No matching log entries</td></tr>';
  } catch (error) { console.warn(error); $('logBody').innerHTML = '<tr><td colspan="4">Logs unavailable</td></tr>'; }
}
function downloadLog(format) {
  const quote = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const content = format === 'csv'
    ? ['timestamp,level,logger,message', ...currentLogEntries.map((entry) => [entry.timestamp, entry.level, entry.logger, entry.message].map(quote).join(','))].join('\r\n')
    : currentLogEntries.map((entry) => `${entry.timestamp || '-'} ${entry.level} ${entry.logger}: ${entry.message}`).join('\n');
  const blob = new Blob([format === 'csv' ? `\uFEFF${content}` : content], { type: format === 'csv' ? 'text/csv;charset=utf-8' : 'text/plain;charset=utf-8' });
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `enocean-mqtt-logs-${new Date().toISOString().replaceAll(':', '-')}.${format === 'csv' ? 'csv' : 'txt'}`; link.click(); URL.revokeObjectURL(link.href);
}
let searchTimer; $('refreshLogs').addEventListener('click', refreshLogs); $('logLevelFilter').addEventListener('change', refreshLogs); $('logLimit').addEventListener('change', refreshLogs); $('logSearch').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(refreshLogs, 300); }); $('exportCsv').addEventListener('click', () => downloadLog('csv')); $('exportText').addEventListener('click', () => downloadLog('text'));
refreshSystem(); refreshLogs(); setInterval(refreshSystem, 30000); setInterval(refreshLogs, 30000);
