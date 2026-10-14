const STATUS_CLASSES = ['ok', 'warn', 'neutral', 'problem'];
let discoveredCommands = new Set();
let commandDispatchAvailable = false;
let commandAuthorization = false;
let dashboardInterfaces = [];
let selectedInterfaceId = null;

function setText(id, value, fallback = 'n/a') {
  const element = document.getElementById(id);
  if (element) element.textContent = value === null || value === undefined || value === '' ? fallback : String(value);
}

function setStatus(id, value, stateClass = 'neutral') {
  const element = document.getElementById(id);
  if (!element) return;
  for (const className of STATUS_CLASSES) element.classList.remove(className);
  element.classList.add(stateClass);
  const valueNode = element.querySelector('span:last-child');
  if (valueNode) valueNode.textContent = String(value ?? 'n/a');
}

function classForStatus(value) {
  const normalized = String(value ?? '').toLowerCase();
  if (['running', 'connected', 'operational'].includes(normalized)) return 'ok';
  if (['disabled', 'replay', 'degraded'].includes(normalized)) return 'warn';
  if (['offline', 'unavailable', 'disconnected', 'failed'].includes(normalized)) return 'problem';
  return 'neutral';
}

function number(value) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatRate(value) { return number(value).toFixed(1); }
function formatInteger(value) { return Math.round(number(value)).toLocaleString(); }
function formatHexPairs(value) {
  if (!value) return null;
  const compact = String(value).replaceAll(' ', '');
  return compact.match(/.{1,2}/g)?.join(' ') ?? compact;
}

function formatDuration(seconds) {
  const total = Math.max(0, number(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days} d ${hours} h`;
  if (hours > 0) return `${hours} h ${minutes} min`;
  return `${minutes} min`;
}

function formatBytes(value) {
  const bytes = number(value);
  if (!bytes) return 'n/a';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}

function formatRelativeTimestamp(timestamp) {
  if (!timestamp) return 'n/a';
  const numeric = Number(timestamp);
  const date = Number.isFinite(numeric) ? new Date(numeric * 1000) : new Date(timestamp);
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (!Number.isFinite(seconds)) return 'n/a';
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

function cookieValue(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split('; ').find((entry) => entry.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : '';
}

function updateOverallHealth(health) {
  const element = document.getElementById('systemHealth');
  if (!element) return;
  for (const className of STATUS_CLASSES) element.classList.remove(className);
  element.classList.add(health.level ?? 'neutral');
  setText('systemHealthText', health.label);
  const details = document.getElementById('healthDetails');
  if (details) {
    details.replaceChildren(...(health.checks ?? []).map((check) => {
      const row = document.createElement('div');
      row.className = 'health-check';
      const label = document.createElement('span');
      label.textContent = check.label;
      const value = document.createElement('span');
      value.className = `health-check-value ${check.state}`;
      value.textContent = check.value;
      row.append(label, value);
      return row;
    }));
  }
}

function showSelectedInterface() {
  const selected = dashboardInterfaces.find((item) => item.interface_id === selectedInterfaceId) ?? dashboardInterfaces[0];
  if (!selected) {
    setText('enoceanInterfaceValue', null);
    setText('enoceanBaseId', null);
    setText('enoceanRx', null);
    setText('enoceanTx', null);
    return;
  }
  selectedInterfaceId = selected.interface_id;
  setText('enoceanInterfaceValue', selected.interface_id);
  setText('enoceanBaseId', selected.base_id);
  setText('enoceanRx', selected.rx_enabled ? 'enabled' : 'disabled');
  setText('enoceanTx', selected.tx_enabled ? 'enabled' : 'disabled');
}

function updateInterfaceSelector(enocean) {
  dashboardInterfaces = Array.isArray(enocean.interfaces) ? enocean.interfaces : [];
  const select = document.getElementById('enoceanInterfaceSelect');
  const value = document.getElementById('enoceanInterfaceValue');
  if (!dashboardInterfaces.some((item) => item.interface_id === selectedInterfaceId)) {
    selectedInterfaceId = enocean.interface_id ?? dashboardInterfaces.find((item) => item.connected)?.interface_id ?? dashboardInterfaces[0]?.interface_id ?? null;
  }
  if (select) {
    select.replaceChildren(...dashboardInterfaces.map((item) => {
      const option = document.createElement('option');
      option.value = item.interface_id;
      option.textContent = item.interface_id;
      option.selected = item.interface_id === selectedInterfaceId;
      return option;
    }));
    select.hidden = dashboardInterfaces.length <= 1;
  }
  if (value) value.hidden = dashboardInterfaces.length > 1;
  showSelectedInterface();
  updateCommandButtons();
}

function updateDashboard(payload) {
  const system = payload.system ?? {};
  const enocean = payload.enocean ?? {};
  const mqtt = payload.mqtt ?? {};
  const sqlite = payload.sqlite ?? {};
  const metrics = payload.metrics ?? {};
  const registry = payload.device_registry ?? {};
  commandAuthorization = payload.runtime_commands?.authorized === true;
  updateCommandButtons();

  updateOverallHealth(payload.overall_health ?? {});
  setStatus('systemStatus', system.status, classForStatus(system.status));
  setText('version', system.version);
  setText('uptime', formatDuration(system.uptime_seconds));
  setText('runtimeMode', system.runtime_mode);
  setText('memory', system.memory_rss_mb == null ? null : `${number(system.memory_rss_mb).toFixed(1)} MiB`);
  setText('apiStatus', system.api_enabled ? (system.api_operational ? 'operational' : 'unavailable') : 'disabled');
  setText('webUiStatus', system.web_ui_enabled ? (system.web_ui_operational ? 'operational' : 'unavailable') : 'disabled');

  setStatus('enoceanStatus', enocean.status, classForStatus(enocean.status));
  setText('enoceanInterfaces', formatInteger(enocean.interfaces_total));
  updateInterfaceSelector(enocean);

  setStatus('mqttStatus', mqtt.status, classForStatus(mqtt.status));
  const mqttEndpoint = mqtt.host && mqtt.port ? `${mqtt.host}:${mqtt.port}` : mqtt.host;
  const mqttLoad = mqtt.message_load ?? {};
  setText('mqttEndpoint', mqttEndpoint);
  setText('mqttUptime', formatDuration(mqtt.uptime_seconds));
  setText('mqttReconnects', formatInteger(mqtt.reconnects));
  setText('mqttPublished15m', formatInteger(mqttLoad.published));
  setText('mqttReceived15m', formatInteger(mqttLoad.received));

  const sqliteState = !sqlite.enabled ? 'disabled' : (sqlite.operational ? 'operational' : 'unavailable');
  setStatus('sqliteStatus', sqliteState, !sqlite.enabled ? 'neutral' : classForStatus(sqliteState));
  setText('sqliteRecords', sqlite.enabled ? formatInteger(sqlite.records) : null);
  setText('sqliteLastWrite', sqlite.enabled ? formatRelativeTimestamp(sqlite.last_write_unix) : null);
  setText('sqliteSize', sqlite.enabled ? formatBytes(sqlite.database_size_bytes) : null);
  setText('sqliteOldestTelegram', sqlite.enabled ? formatRelativeTimestamp(sqlite.oldest_telegram_unix) : null);
  setText('sqliteTelegramLimit', sqlite.enabled ? (number(sqlite.max_telegrams) > 0 ? formatInteger(sqlite.max_telegrams) : 'unlimited') : null);

  setText('rxRate', formatRate(metrics.rx_per_minute));
  setText('txRate', formatRate(metrics.tx_per_minute));
  setText('rxTotal', `${formatInteger(metrics.rx_total)} total`);
  setText('txTotal', `${formatInteger(metrics.tx_total)} total`);
  setText('decodedTotal', formatInteger(metrics.decoded_total));
  setText('errorCount', formatInteger(metrics.decode_errors_total));
  const formattedRawRx = formatHexPairs(metrics.last_raw_rx);
  setText('lastRawRx', formattedRawRx);
  setText(
    'lastRawRxTooltip',
    formattedRawRx
      ? `Raw telegram: ${formattedRawRx}\n\nDecoded:\n${metrics.last_raw_rx_decoded ?? 'Decode unavailable'}`
      : null,
  );
  setText('lastSender', metrics.last_sender_id);
  setText('lastSenderName', metrics.last_sender_name, 'unknown');

  setText('registeredDeviceCount', formatInteger(registry.physical));
  setText('virtualDeviceCount', formatInteger(registry.virtual));
  setText('activeRegistryCount', formatInteger(metrics.active_devices_total));
  setText('unknownDeviceCount', formatInteger(registry.unknown));
  setText('foreignDeviceCount', formatInteger(registry.foreign));
  setText('registryReload', registry.last_reload ? `reloaded ${formatRelativeTimestamp(registry.last_reload)}` : null);
}

async function loadDashboard() {
  try {
    const response = await fetch('/api/v1/ui/dashboard', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Dashboard summary returned ${response.status}`);
    updateDashboard(await response.json());
  } catch (error) {
    console.warn('Failed to update dashboard', error);
    setStatus('systemStatus', 'unavailable', 'problem');
    updateOverallHealth({ level: 'problem', label: 'Dashboard data unavailable', checks: [] });
  }
}

async function loadCommands() {
  try {
    const response = await fetch('/api/v1/runtime/commands', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Command discovery returned ${response.status}`);
    const payload = await response.json();
    discoveredCommands = new Set((payload.commands ?? []).map((command) => command.name));
    commandDispatchAvailable = payload.dispatch?.http_available === true;
    updateCommandButtons();
  } catch (error) {
    commandDispatchAvailable = false;
    updateCommandButtons();
    setText('commandAvailability', 'unavailable');
  }
}

function updateCommandButtons() {
  const buttons = [...document.querySelectorAll('[data-command]')];
  for (const button of buttons) {
    button.disabled = !commandDispatchAvailable || !commandAuthorization || !discoveredCommands.has(button.dataset.command)
      || (button.dataset.command.startsWith('interface.') && !selectedInterfaceId);
  }
  if (!commandDispatchAvailable) setText('commandAvailability', 'unavailable');
  else if (!commandAuthorization) setText('commandAvailability', 'admin required');
  else setText('commandAvailability', 'available');
}

async function executeCommand(button) {
  const command = button.dataset.command;
  const commandPayload = {};
  if (command.startsWith('interface.')) {
    if (!selectedInterfaceId) { setText('commandResult', 'Select an EnOcean interface first.'); return; }
    commandPayload.interface_id = selectedInterfaceId;
  }
  if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) return;
  button.disabled = true;
  setText('commandResult', `Executing ${command}…`);
  try {
    const response = await fetch(`/api/v1/runtime/commands/${encodeURIComponent(command)}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': cookieValue('enocean_web_csrf'),
      },
      body: JSON.stringify(commandPayload),
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = typeof payload.detail === 'string'
        ? payload.detail
        : [payload.detail?.message, payload.detail?.error].filter(Boolean).join(': ');
      throw new Error(detail || `Command returned ${response.status}`);
    }
    setText('commandResult', `${command}: ${payload.status ?? 'accepted'}`);
  } catch (error) {
    setText('commandResult', `${command}: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

for (const button of document.querySelectorAll('[data-command]')) {
  button.addEventListener('click', () => executeCommand(button));
}
document.getElementById('enoceanInterfaceSelect')?.addEventListener('change', (event) => {
  selectedInterfaceId = event.target.value;
  showSelectedInterface();
  updateCommandButtons();
});
loadDashboard();
loadCommands();
window.setInterval(loadDashboard, 10000);
