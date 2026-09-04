/* Additional Device Management behaviour kept separate from the core page logic. */

const UNKNOWN_DISCOVERY_RESET_KEY = 'enocean_mqtt_unknown_devices_reset_at';
const EXTERNAL_SENDER_IDS_KEY = 'enocean_mqtt_external_sender_ids';
const HIDE_EXTERNAL_DEVICES_KEY = 'enocean_mqtt_hide_external_devices';
const HIDE_OWN_SENDER_IDS_KEY = 'enocean_mqtt_hide_own_sender_ids';

let gatewaySenderPools = [];

function storedBoolean(key, fallback) {
  const value = localStorage.getItem(key);
  if (value === null) return fallback;
  return value === 'true';
}

function externalSenderIds() {
  try {
    const value = JSON.parse(localStorage.getItem(EXTERNAL_SENDER_IDS_KEY) || '[]');
    return new Set(Array.isArray(value) ? value.map((item) => String(item).toUpperCase()) : []);
  } catch (_error) {
    return new Set();
  }
}

function setExternalSenderId(senderId, external) {
  const values = externalSenderIds();
  const normalized = String(senderId || '').trim().toUpperCase();
  if (!normalized) return;
  if (external) values.add(normalized);
  else values.delete(normalized);
  localStorage.setItem(EXTERNAL_SENDER_IDS_KEY, JSON.stringify([...values].sort()));
}

function gatewayManagedSenderIds() {
  const senderIds = new Set();
  (state.physical || []).forEach((device) => {
    const senderId = String(device.sender_id || '').trim().toUpperCase();
    if (senderId) senderIds.add(senderId);
  });
  (state.virtual || []).forEach((device) => {
    const senderId = String(device.sender_id || '').trim().toUpperCase();
    if (senderId) senderIds.add(senderId);
  });
  return senderIds;
}

function senderIdInGatewayPool(senderId) {
  const numeric = Number.parseInt(String(senderId || ''), 16);
  if (!Number.isFinite(numeric)) return false;
  return gatewaySenderPools.some((pool) => numeric >= pool.base && numeric <= pool.last);
}

function isOwnSenderId(senderId) {
  const normalized = String(senderId || '').trim().toUpperCase();
  return gatewayManagedSenderIds().has(normalized) || senderIdInGatewayPool(normalized);
}

async function loadGatewaySenderPools() {
  try {
    const payload = await apiJson('/api/v1/ui/dashboard');
    const enocean = payload?.enocean || {};
    const baseIds = new Set();
    if (enocean.base_id) baseIds.add(String(enocean.base_id).trim().toUpperCase());
    (enocean.interfaces || []).forEach((item) => {
      if (item?.base_id) baseIds.add(String(item.base_id).trim().toUpperCase());
    });
    gatewaySenderPools = [...baseIds]
      .map((baseId) => Number.parseInt(baseId, 16))
      .filter(Number.isFinite)
      .map((base) => ({ base, last: base + 0x7F }));
    renderPanels();
  } catch (error) {
    console.warn('Could not load gateway Base IDs for unknown-device filtering', error);
  }
}

function unknownDiscoveryResetAt() {
  const value = Number(localStorage.getItem(UNKNOWN_DISCOVERY_RESET_KEY) || 0);
  return Number.isFinite(value) ? value : 0;
}

function visibleUnknownDevices() {
  const resetAt = unknownDiscoveryResetAt();
  const hiddenExternal = document.getElementById('hideExternalDevices')?.checked ?? false;
  const hiddenOwn = document.getElementById('hideOwnSenderIds')?.checked ?? true;
  const external = externalSenderIds();

  return (state.unknown || []).filter((device) => {
    const senderId = String(device.sender_id || '').trim().toUpperCase();
    if (!senderId) return false;
    if (hiddenOwn && isOwnSenderId(senderId)) return false;
    if (hiddenExternal && external.has(senderId)) return false;
    if (!resetAt) return true;
    const lastSeen = Date.parse(device.last_seen || '');
    return Number.isFinite(lastSeen) && lastSeen >= resetAt;
  });
}

function appendExternalActions() {
  const external = externalSenderIds();
  document.querySelectorAll('#unknownDevicesBody tr').forEach((row) => {
    const senderId = row.cells[0]?.textContent?.trim().toUpperCase();
    if (!senderId || row.querySelector('.device-empty')) return;
    const actions = row.cells[7]?.querySelector('.device-row-actions');
    if (!actions || actions.querySelector('[data-external-toggle]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'device-button';
    button.dataset.externalToggle = senderId;
    button.textContent = external.has(senderId) ? 'Unmark external' : 'Mark external';
    button.disabled = !state.canWrite;
    button.addEventListener('click', () => {
      const currentlyExternal = externalSenderIds().has(senderId);
      setExternalSenderId(senderId, !currentlyExternal);
      renderPanels();
      setMessage(`${senderId} ${currentlyExternal ? 'removed from' : 'marked as'} external devices.`);
    });
    actions.append(button);
    if (external.has(senderId)) row.classList.add('device-external');
  });
}

if (typeof renderUnknown === 'function') {
  const originalRenderUnknown = renderUnknown;
  renderUnknown = function filteredUnknownRender() {
    const allUnknown = state.unknown;
    const visible = visibleUnknownDevices();
    state.unknown = visible;
    try {
      originalRenderUnknown();
      appendExternalActions();
      const counter = document.getElementById('unknownCount');
      if (counter) counter.textContent = String(visible.length);
      const panelCounter = document.getElementById('unknownPanelCount');
      if (panelCounter) panelCounter.textContent = `${visible.length} recent devices`;
    } finally {
      state.unknown = allUnknown;
    }
  };
}

function installUnknownFilters() {
  const hideExternal = document.getElementById('hideExternalDevices');
  const hideOwn = document.getElementById('hideOwnSenderIds');
  if (hideExternal) {
    hideExternal.checked = storedBoolean(HIDE_EXTERNAL_DEVICES_KEY, true);
    hideExternal.addEventListener('change', () => {
      localStorage.setItem(HIDE_EXTERNAL_DEVICES_KEY, String(hideExternal.checked));
      renderPanels();
    });
  }
  if (hideOwn) {
    hideOwn.checked = storedBoolean(HIDE_OWN_SENDER_IDS_KEY, true);
    hideOwn.addEventListener('change', () => {
      localStorage.setItem(HIDE_OWN_SENDER_IDS_KEY, String(hideOwn.checked));
      renderPanels();
    });
  }
}

function installUnknownDeviceReset() {
  const button = document.getElementById('clearUnknownDevicesButton');
  if (!button) return;
  button.addEventListener('click', () => {
    if (!window.confirm('Clear the current unknown-device discovery list? Telegram history will be kept.')) return;
    localStorage.setItem(UNKNOWN_DISCOVERY_RESET_KEY, String(Date.now()));
    renderPanels();
    setMessage('Unknown-device discovery list cleared. Historical telegrams were kept.');
  });
}

function updateTeachInCells() {
  document.querySelectorAll('#physicalDevicesBody tr').forEach((row) => {
    const deviceId = row.cells[0]?.querySelector('.device-secondary')?.textContent?.trim().toUpperCase();
    const device = (state.physical || []).find(
      (item) => String(item.device_id || '').trim().toUpperCase() === deviceId,
    );
    if (!device || device.tx_capable) return;
    if (row.cells[6]) row.cells[6].textContent = '';
  });
}

if (typeof renderPanels === 'function') {
  const previousRenderPanels = renderPanels;
  renderPanels = function taughtInAwareRenderPanels() {
    previousRenderPanels();
    updateTeachInCells();
  };
}

function virtualProfileIdentifier(form) {
  const profile = String(form.elements.namedItem('profile')?.value || '').trim();
  const eep = String(form.elements.namedItem('eep')?.value || '').trim();
  return profile || eep;
}

function selectableVirtualChannels(payload) {
  const definition = payload?.eep || payload?.profile || payload;
  const channels = Array.isArray(definition?.channels) ? definition.channels : [];
  return channels
    .filter((channel) => channel && typeof channel === 'object')
    .filter((channel) => channel.tx?.managed !== true)
    .map((channel) => ({
      name: String(channel.name || '').trim(),
      label: String(channel.display_name || channel.name || '').trim(),
      unit: String(channel.unit || '').trim(),
    }))
    .filter((channel) => channel.name);
}

function ensureVirtualChannelChooser(form) {
  const input = form.elements.namedItem('channels');
  if (!input) return null;
  input.type = 'hidden';
  input.required = false;
  let chooser = document.getElementById('virtualChannelChooser');
  if (!chooser) {
    chooser = document.createElement('div');
    chooser.id = 'virtualChannelChooser';
    chooser.className = 'virtual-channel-chooser';
    input.insertAdjacentElement('afterend', chooser);
  }
  return chooser;
}

function selectedVirtualChannels(form) {
  return String(form.elements.namedItem('channels')?.value || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function syncVirtualChannels(form) {
  const input = form.elements.namedItem('channels');
  const checked = [...document.querySelectorAll('#virtualChannelChooser input[type="checkbox"]:checked')]
    .map((checkbox) => checkbox.value);
  if (input) {
    input.value = checked.join(', ');
    input.setCustomValidity(checked.length ? '' : 'Select at least one channel.');
  }
}

async function renderVirtualChannelChooser(form) {
  const chooser = ensureVirtualChannelChooser(form);
  if (!chooser) return;
  const identifier = virtualProfileIdentifier(form);
  if (!identifier) {
    chooser.replaceChildren();
    chooser.textContent = 'Select an EEP or profile first.';
    return;
  }

  chooser.replaceChildren();
  chooser.textContent = 'Loading channels…';
  try {
    const payload = await apiJson(`/api/v1/eeps/${encodeURIComponent(identifier)}`);
    const channels = selectableVirtualChannels(payload);
    const selected = new Set(selectedVirtualChannels(form));
    chooser.replaceChildren();

    if (!channels.length) {
      chooser.textContent = 'This profile exposes no selectable virtual-device channels.';
      return;
    }

    channels.forEach((channel) => {
      const label = document.createElement('label');
      label.className = 'virtual-channel-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = channel.name;
      checkbox.checked = selected.has(channel.name);
      checkbox.addEventListener('change', () => syncVirtualChannels(form));
      const text = document.createElement('span');
      text.textContent = channel.unit
        ? `${channel.label} (${channel.name}, ${channel.unit})`
        : `${channel.label} (${channel.name})`;
      label.append(checkbox, text);
      chooser.append(label);
    });
    syncVirtualChannels(form);
  } catch (error) {
    chooser.replaceChildren();
    chooser.textContent = `Could not load channels: ${error.message}`;
  }
}

function installVirtualChannelChooser() {
  const form = document.getElementById('virtualDeviceForm');
  if (!form) return;
  ensureVirtualChannelChooser(form);
  form.addEventListener('change', (event) => {
    const name = event.target?.name;
    if (name === 'eep' || name === 'profile') renderVirtualChannelChooser(form);
  });
  form.addEventListener('submit', () => syncVirtualChannels(form), { capture: true });

  if (typeof openVirtualDialog === 'function') {
    const previousOpenVirtualDialog = openVirtualDialog;
    openVirtualDialog = function channelAwareOpenVirtualDialog(device = null) {
      previousOpenVirtualDialog(device);
      queueMicrotask(() => renderVirtualChannelChooser(form));
    };
  }
}

installUnknownFilters();
installUnknownDeviceReset();
installVirtualChannelChooser();
loadGatewaySenderPools();
renderPanels();
