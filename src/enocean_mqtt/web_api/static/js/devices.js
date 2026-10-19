const managementUrl = '/api/v1/device-management';
const state = { physical: [], virtual: [], unknown: [], foreign: [], gateways: [], canWrite: false };

const elements = {
  status: document.getElementById('deviceRegistryStatus'),
  statusText: document.getElementById('deviceRegistryStatusText'),
  message: document.getElementById('deviceMessage'),
  search: document.getElementById('deviceSearch'),
  typeFilter: document.getElementById('deviceTypeFilter'),
  stateFilter: document.getElementById('deviceStateFilter'),
  physicalBody: document.getElementById('physicalDevicesBody'),
  virtualBody: document.getElementById('virtualDevicesBody'),
  unknownBody: document.getElementById('unknownDevicesBody'),
  physicalDialog: document.getElementById('physicalDeviceDialog'),
  physicalForm: document.getElementById('physicalDeviceForm'),
  physicalTitle: document.getElementById('physicalDialogTitle'),
  virtualDialog: document.getElementById('virtualDeviceDialog'),
  virtualForm: document.getElementById('virtualDeviceForm'),
  virtualTitle: document.getElementById('virtualDialogTitle'),
  importFile: document.getElementById('deviceImportFile'),
};

function cookieValue(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  for (const item of document.cookie.split(';')) {
    const value = item.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return '';
}

async function apiJson(url, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(!['GET', 'HEAD', 'OPTIONS'].includes(method)
        ? { 'X-CSRF-Token': cookieValue('enocean_web_csrf') }
        : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `HTTP ${response.status}`);
  }
  return payload;
}

function setStatus(text, level = 'neutral') {
  elements.status.classList.remove('ok', 'neutral', 'problem', 'warn');
  elements.status.classList.add(level);
  elements.statusText.textContent = text;
}

function setMessage(text = '', level = '') {
  elements.message.textContent = text;
  elements.message.className = `device-message${level ? ` ${level}` : ''}`;
}

function text(value, fallback = '—') {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function relativeTime(value) {
  if (!value) return 'never';
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return text(value);
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

function node(tag, className = '', value = null) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== null) element.textContent = value;
  return element;
}

function cell(value, className = '') {
  const td = node('td', className);
  if (value instanceof Node) td.append(value);
  else td.textContent = text(value);
  return td;
}

function identityCell(primary, secondary) {
  const wrapper = node('span');
  wrapper.append(node('span', 'device-primary', text(primary)));
  wrapper.append(node('span', 'device-secondary device-mono', text(secondary)));
  return wrapper;
}

function telegramCell(telegram, fallback = '—') {
  const raw = telegram?.raw_telegram || telegram?.data || fallback;
  const span = node('span', 'device-telegram device-mono', text(raw));
  span.title = text(raw, '');
  return span;
}

function receiversText(receivers) {
  if (!Array.isArray(receivers) || receivers.length === 0) return 'not confirmed';
  return receivers.map((item) => item.receiver).filter(Boolean).join(', ') || 'not confirmed';
}

function actionButton(label, action, kind, id, className = '') {
  const button = node('button', `device-button ${className}`.trim(), label);
  button.type = 'button';
  button.dataset.action = action;
  button.dataset.kind = kind;
  button.dataset.id = id;
  button.disabled = !state.canWrite;
  return button;
}

function actionCell(buttons) {
  const wrapper = node('div', 'device-row-actions');
  wrapper.append(...buttons);
  return wrapper;
}

function emptyRow(body, columns, label) {
  const row = body.insertRow();
  const td = row.insertCell();
  td.colSpan = columns;
  td.className = 'device-empty';
  td.textContent = label;
}

function matchesSearch(values) {
  const query = elements.search.value.trim().toLowerCase();
  return !query || values.some((value) => String(value || '').toLowerCase().includes(query));
}

function matchesState(item, kind) {
  const filter = elements.stateFilter.value;
  if (filter === 'all') return true;
  if (filter === 'active') return kind === 'unknown' || Boolean(item.active);
  if (filter === 'inactive') return kind !== 'unknown' && !item.active;
  if (filter === 'enabled') return item.enabled !== false;
  if (filter === 'disabled') return item.enabled === false;
  if (filter === 'bidirectional') return kind === 'physical' && Boolean(item.tx_capable);
  return true;
}

function renderPhysical() {
  elements.physicalBody.replaceChildren();
  const devices = state.physical
    .filter((item) => matchesSearch([item.device_name, item.device_id, item.alias, item.eep, item.profile, item.manufacturer, item.model]))
    .filter((item) => matchesState(item, 'physical'))
    .filter((item) => !(state.foreign || []).some((foreign) => foreign.sender_id === item.device_id))
    .sort((a, b) => text(a.device_name).localeCompare(text(b.device_name)));
  document.getElementById('physicalPanelCount').textContent = `${devices.length} devices`;
  if (devices.length === 0) return emptyRow(elements.physicalBody, 8, 'No physical devices match the current filters.');

  devices.forEach((device) => {
    const row = elements.physicalBody.insertRow();
    row.append(cell(identityCell(device.device_name, device.device_id)));
    row.append(cell(identityCell(device.registry_profile, device.alias)));
    row.append(cell(device.communication));
    row.append(cell(node('span', `device-status ${device.active ? 'ok' : ''}`, device.enabled === false ? 'disabled' : (device.active ? 'active' : 'inactive'))));
    row.append(cell(relativeTime(device.last_telegram?.timestamp)));
    row.append(cell(telegramCell(device.last_telegram)));
    row.append(cell(receiversText(device.teach_in_receivers)));
    const actions = [actionButton('Edit', 'edit', 'physical', device.device_id)];
    if (device.tx_capable) actions.push(actionButton('Teach-in', 'teach-in', 'physical', device.device_id));
    if (device.tx_capable) actions.push(actionButton('Confirm receiver', 'confirm', 'physical', device.device_id));
    actions.push(actionButton('Delete', 'delete', 'physical', device.device_id, 'danger'));
    row.append(cell(actionCell(actions)));
  });
}

function renderVirtual() {
  elements.virtualBody.replaceChildren();
  const devices = state.virtual
    .filter((item) => matchesSearch([item.metadata?.device_name, item.virtual_device_id, item.sender_id, item.eep, item.profile, ...(item.channels || [])]))
    .filter((item) => matchesState(item, 'virtual'))
    .filter((item) => !(state.foreign || []).some((foreign) => foreign.sender_id === item.sender_id))
    .sort((a, b) => text(a.metadata?.device_name || a.virtual_device_id).localeCompare(text(b.metadata?.device_name || b.virtual_device_id)));
  document.getElementById('virtualPanelCount').textContent = `${devices.length} devices`;
  if (devices.length === 0) return emptyRow(elements.virtualBody, 8, 'No virtual devices match the current filters.');

  devices.forEach((device) => {
    const row = elements.virtualBody.insertRow();
    row.append(cell(identityCell(device.metadata?.device_name || device.virtual_device_id, device.virtual_device_id)));
    row.append(cell(device.sender_id, 'device-mono'));
    row.append(cell(device.registry_profile));
    row.append(cell((device.channels || []).join(', ')));
    row.append(cell(node('span', `device-status ${device.enabled !== false ? 'ok' : ''}`, device.enabled === false ? 'disabled' : 'enabled')));
    row.append(cell(telegramCell(device.last_telegram)));
    row.append(cell(receiversText(device.teach_in_receivers)));
    row.append(cell(actionCell([
      actionButton('Edit', 'edit', 'virtual', device.virtual_device_id),
      actionButton('Teach-in', 'teach-in', 'virtual', device.virtual_device_id),
      actionButton('Confirm receiver', 'confirm', 'virtual', device.virtual_device_id),
      actionButton('Delete', 'delete', 'virtual', device.virtual_device_id, 'danger'),
    ])));
  });
}

function renderUnknown() {
  elements.unknownBody.replaceChildren();
  const devices = state.unknown
    .filter((item) => matchesSearch([item.sender_id, item.rorg, item.last_data, item.last_raw_telegram]))
    .filter((item) => matchesState(item, 'unknown'))
    .sort((a, b) => text(a.sender_id).localeCompare(text(b.sender_id)));
  document.getElementById('unknownPanelCount').textContent = `${devices.length} recent devices`;
  if (devices.length === 0) return emptyRow(elements.unknownBody, 8, 'No unknown devices match the current filters.');

  devices.forEach((device) => {
    const row = elements.unknownBody.insertRow();
    row.append(cell(device.sender_id, 'device-mono'));
    row.append(cell(device.rorg));
    row.append(cell(device.telegrams));
    row.append(cell(relativeTime(device.first_seen)));
    row.append(cell(relativeTime(device.last_seen)));
    row.append(cell(device.last_rssi_dbm === null ? '—' : `${device.last_rssi_dbm} dBm`));
    row.append(cell(telegramCell({ raw_telegram: device.last_raw_telegram, data: device.last_data })));
    row.append(cell(actionCell([
      actionButton('Register as device', 'capture', 'unknown', device.sender_id),
      actionButton('Register as gateway', 'capture-gateway', 'unknown', device.sender_id),
    ])));
  });
}

function renderPanels() {
  const selected = elements.typeFilter.value;
  document.querySelectorAll('[data-panel]').forEach((panel) => {
    panel.hidden = selected !== 'all' && panel.dataset.panel !== selected;
  });
  renderPhysical();
  renderVirtual();
  renderUnknown();
  if (typeof renderGateways === 'function') renderGateways();
}

function setWritableControls() {
  ['reloadDevicesButton', 'newPhysicalDeviceButton', 'newVirtualDeviceButton', 'importDevicesButton', 'newGatewayButton']
    .forEach((id) => { document.getElementById(id).disabled = !state.canWrite; });
}

async function loadProfiles() {
  try {
    const payload = await apiJson(`${managementUrl}/profiles`);
    const list = document.getElementById('deviceProfiles');
    list.replaceChildren(...(payload.profiles || []).map((profile) => {
      const option = document.createElement('option');
      option.value = profile;
      return option;
    }));
  } catch (error) {
    console.warn('Could not load profiles', error);
  }
}

async function loadDevices() {
  setStatus('Loading', 'neutral');
  try {
    const payload = await apiJson(managementUrl);
    state.physical = payload.physical_devices || [];
    state.virtual = payload.virtual_devices || [];
    state.unknown = payload.unknown_devices || [];
    state.canWrite = Boolean(payload.can_write);
    state.foreign = payload.foreign_devices || [];
    state.gateways = payload.gateways || [];
    if (typeof migrateForeignDevices === 'function') await migrateForeignDevices();
    document.getElementById('physicalCount').textContent = payload.counts?.devices ?? 0;
    document.getElementById('unknownCount').textContent = payload.counts?.unknown_devices ?? 0;
    document.getElementById('virtualCount').textContent = payload.counts?.virtual_devices ?? 0;
    document.getElementById('activeCount').textContent = payload.counts?.active_devices ?? 0;
    setStatus(payload.status === 'ok' ? 'Registry loaded' : 'Registry warnings', payload.status === 'ok' ? 'ok' : 'warn');
    setWritableControls();
    renderPanels();
    if (!state.canWrite) setMessage('Administrator privileges are required to change the registry.');
    else if ((payload.issues || []).length) setMessage(`${payload.issues.length} registry warning(s) reported.`, 'warning');
    else setMessage('');
  } catch (error) {
    setStatus('Unavailable', 'problem');
    setMessage(error.message, 'error');
  }
}

function formValue(form, name) { return form.elements.namedItem(name); }
function optional(value) { const normalized = String(value || '').trim(); return normalized || null; }

function openPhysicalDialog(device = null, unknown = null) {
  const form = elements.physicalForm;
  form.reset();
  form._device = device;
  elements.physicalTitle.textContent = device ? 'Edit device' : (unknown ? 'Register unknown device' : 'New device');
  formValue(form, 'device_id').value = device?.device_id || unknown?.sender_id || '';
  formValue(form, 'device_id').readOnly = Boolean(device);
  formValue(form, 'device_name').value = device?.device_name || '';
  formValue(form, 'alias').value = device?.alias || '';
  formValue(form, 'eep').value = device?.eep || '';
  formValue(form, 'profile').value = device?.profile || '';
  formValue(form, 'communication').value = device?.communication || 'unidirectional';
  formValue(form, 'tx_eep').value = device?.tx_eep || '';
  formValue(form, 'tx_profile').value = device?.tx_profile || '';
  formValue(form, 'manufacturer').value = device?.manufacturer || '';
  formValue(form, 'model').value = device?.model || '';
  formValue(form, 'description').value = device?.description || '';
  formValue(form, 'floor').value = device?.metadata?.floor || '';
  formValue(form, 'room').value = device?.metadata?.room || '';
  formValue(form, 'equipment_id').value = device?.metadata?.equipment_id || '';
  formValue(form, 'enabled').checked = device?.enabled !== false;
  formValue(form, 'enocean_secure').checked = Boolean(device?.enocean_secure);
  elements.physicalDialog.showModal();
}

function openVirtualDialog(device = null) {
  const form = elements.virtualForm;
  form.reset();
  form._device = device;
  elements.virtualTitle.textContent = device ? 'Edit virtual device' : 'New virtual device';
  formValue(form, 'device_name').value = device?.metadata?.device_name || device?.virtual_device_id || '';
  formValue(form, 'eep').value = device?.eep || '';
  formValue(form, 'profile').value = device?.profile || '';
  formValue(form, 'channels').value = (device?.channels || []).join(', ');
  formValue(form, 'description').value = device?.description || '';
  formValue(form, 'enabled').checked = device?.enabled !== false;
  elements.virtualDialog.showModal();
}

async function savePhysical(event) {
  event.preventDefault();
  const form = elements.physicalForm;
  const existing = form._device;
  const metadata = { ...(existing?.metadata || {}) };
  ['floor', 'room', 'equipment_id'].forEach((name) => {
    const value = optional(formValue(form, name).value);
    if (value) metadata[name] = value;
    else delete metadata[name];
  });
  const payload = {
    device_id: formValue(form, 'device_id').value.trim().toUpperCase(),
    device_name: formValue(form, 'device_name').value.trim(),
    alias: optional(formValue(form, 'alias').value),
    description: optional(formValue(form, 'description').value),
    manufacturer: optional(formValue(form, 'manufacturer').value),
    model: optional(formValue(form, 'model').value),
    communication: formValue(form, 'communication').value,
    eep: optional(formValue(form, 'eep').value),
    profile: optional(formValue(form, 'profile').value),
    tx_eep: optional(formValue(form, 'tx_eep').value),
    tx_profile: optional(formValue(form, 'tx_profile').value),
    sender_id: existing?.sender_id || null,
    enocean_secure: formValue(form, 'enocean_secure').checked,
    enabled: formValue(form, 'enabled').checked,
    metadata,
  };
  try {
    await apiJson(existing ? `${managementUrl}/physical/${encodeURIComponent(existing.device_id)}` : `${managementUrl}/physical`, { method: existing ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    elements.physicalDialog.close();
    setMessage('Device saved.');
    await loadDevices();
  } catch (error) { setMessage(error.message, 'error'); }
}

async function saveVirtual(event) {
  event.preventDefault();
  const form = elements.virtualForm;
  const existing = form._device;
  const metadata = { ...(existing?.metadata || {}) };
  const deviceName = optional(formValue(form, 'device_name').value);
  if (deviceName) metadata.device_name = deviceName;
  else delete metadata.device_name;
  const payload = {
    ...(existing ? { virtual_device_id: existing.virtual_device_id } : {}),
    eep: formValue(form, 'eep').value.trim(),
    profile: optional(formValue(form, 'profile').value),
    channels: formValue(form, 'channels').value.split(',').map((value) => value.trim()).filter(Boolean),
    description: optional(formValue(form, 'description').value),
    enabled: formValue(form, 'enabled').checked,
    metadata,
  };
  try {
    await apiJson(existing ? `${managementUrl}/virtual/${encodeURIComponent(existing.virtual_device_id)}` : `${managementUrl}/virtual`, { method: existing ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    elements.virtualDialog.close();
    setMessage('Virtual device saved.');
    await loadDevices();
  } catch (error) { setMessage(error.message, 'error'); }
}

async function confirmReceiver(kind, id) {
  const receiver = window.prompt('Receiver name confirmed by the user:');
  if (!receiver?.trim()) return;
  await apiJson(`${managementUrl}/${kind}/${encodeURIComponent(id)}/teach-in-confirmations`, { method: 'POST', body: JSON.stringify({ receiver: receiver.trim() }) });
  setMessage(`Teach-in for ${id} manually confirmed for receiver “${receiver.trim()}”.`);
  await loadDevices();
}

async function handleTableAction(button) {
  const { action, kind, id } = button.dataset;
  const collection = kind === 'physical' ? state.physical : (kind === 'virtual' ? state.virtual : state.unknown);
  const item = collection.find((entry) => (entry.device_id || entry.virtual_device_id || entry.sender_id) === id);
  if (!item) return;
  try {
    if (action === 'edit') return kind === 'physical' ? openPhysicalDialog(item) : openVirtualDialog(item);
    if (action === 'capture') return openPhysicalDialog(null, item);
    if (action === 'capture-gateway') return openGatewayDialog(null, item);
    if (action === 'confirm') return await confirmReceiver(kind, id);
    if (action === 'teach-in') {
      if (!window.confirm(`Send teach-in telegram for ${id}?`)) return;
      await apiJson(`${managementUrl}/${kind}/${encodeURIComponent(id)}/teach-in`, { method: 'POST', body: '{}' });
      setMessage(`Teach-in telegram for ${id} sent.`);
      if (window.confirm('Was the teach-in successful and should the receiver be recorded?')) await confirmReceiver(kind, id);
      return;
    }
    if (action === 'delete') {
      if (!window.confirm(`Delete ${id} from the registry?`)) return;
      await apiJson(`${managementUrl}/${kind}/${encodeURIComponent(id)}`, { method: 'DELETE' });
      setMessage(`${id} deleted.`);
      await loadDevices();
    }
  } catch (error) { setMessage(error.message, 'error'); }
}

async function importCsv(file) {
  const csvContent = await file.text();
  try {
    const preview = await apiJson(`${managementUrl}/import/preview`, { method: 'POST', body: JSON.stringify({ csv: csvContent }) });
    const errors = (preview.messages || []).filter((item) => item.level === 'error').length;
    const summary = `${preview.created} new, ${preview.updated} updated, ${errors} error(s), ${preview.total_after_import} total after import.`;
    if (!window.confirm(`Import preview:\n${summary}\n\nContinue?`)) return;
    await apiJson(`${managementUrl}/import`, { method: 'POST', body: JSON.stringify({ csv: csvContent }) });
    setMessage(`CSV import completed: ${summary}`);
    await loadDevices();
  } catch (error) { setMessage(error.message, 'error'); }
  finally { elements.importFile.value = ''; }
}

document.addEventListener('click', (event) => {
  const close = event.target.closest('[data-close-dialog]');
  if (close) close.closest('dialog')?.close();
  const action = event.target.closest('[data-action]');
  if (action) handleTableAction(action);
});
elements.search.addEventListener('input', renderPanels);
elements.typeFilter.addEventListener('change', renderPanels);
elements.stateFilter.addEventListener('change', renderPanels);
elements.physicalForm.addEventListener('submit', savePhysical);
elements.virtualForm.addEventListener('submit', saveVirtual);
document.getElementById('newPhysicalDeviceButton').addEventListener('click', () => openPhysicalDialog());
document.getElementById('newVirtualDeviceButton').addEventListener('click', () => openVirtualDialog());
document.getElementById('reloadDevicesButton').addEventListener('click', async () => { try { await apiJson(`${managementUrl}/reload`, { method: 'POST', body: '{}' }); await loadDevices(); } catch (error) { setMessage(error.message, 'error'); } });
document.getElementById('importDevicesButton').addEventListener('click', () => elements.importFile.click());
elements.importFile.addEventListener('change', () => { if (elements.importFile.files[0]) importCsv(elements.importFile.files[0]); });
document.getElementById('exportDevicesButton').addEventListener('click', () => { window.location.href = `${managementUrl}/export/devices.csv`; });
document.getElementById('exportUnknownButton').addEventListener('click', () => { window.location.href = `${managementUrl}/export/unknown-devices.csv`; });

loadProfiles();
loadDevices();
