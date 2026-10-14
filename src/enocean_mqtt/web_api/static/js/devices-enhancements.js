/* Registry-driven controls and sortable tables for Device Management. */

const deviceEnhancementState = {
  options: null,
  sort: {
    physical: { index: 0, direction: 'asc' },
    virtual: { index: 0, direction: 'asc' },
    unknown: { index: 0, direction: 'asc' },
  },
};

function deviceAliasFromName(value) {
  return String(value || '')
    .trim().toLowerCase()
    .replaceAll('ä', 'ae').replaceAll('ö', 'oe').replaceAll('ü', 'ue').replaceAll('ß', 'ss')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[\s-]+/g, '_').replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function registryOption(value, label = null) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = label || value;
  return option;
}

function registrySelect(form, name, entries, allowBlank = true) {
  const current = form.elements.namedItem(name);
  if (!current) return null;
  if (current.tagName === 'SELECT' && current.dataset.registryDriven === 'true') return current;
  const select = document.createElement('select');
  select.name = name;
  select.className = current.className;
  select.dataset.registryDriven = 'true';
  select.required = current.required;
  if (allowBlank) select.append(registryOption('', '—'));
  entries.forEach((entry) => {
    const id = typeof entry === 'string' ? entry : entry.id;
    const description = typeof entry === 'string' ? '' : entry.description;
    select.append(registryOption(id, description ? `${id} — ${description}` : id));
  });
  const value = current.value;
  current.replaceWith(select);
  if ([...select.options].some((item) => item.value === value)) select.value = value;
  return select;
}

function registryDatalist(id, values) {
  let list = document.getElementById(id);
  if (!list) {
    list = document.createElement('datalist');
    list.id = id;
    document.body.append(list);
  }
  list.replaceChildren(...values.map((value) => registryOption(value)));
}

function applyProtocolBinding(form) {
  const options = deviceEnhancementState.options;
  if (!options || !form) return;
  const eep = String(form.elements.namedItem('eep')?.value || '').trim().toUpperCase();
  const profile = String(form.elements.namedItem('profile')?.value || '').trim() || eep;
  const definitions = [...(options.eeps || []), ...(options.profiles || [])];
  const definition = definitions.find((item) => item.id === profile) || definitions.find((item) => item.id === eep);
  const selected = new Set([eep, profile].filter(Boolean).map((value) => value.toLowerCase()));
  const mapping = (options.controller_mappings || []).find(
    (item) => selected.has(String(item.device_eep || '').trim().toLowerCase()),
  );
  const communication = form.elements.namedItem('communication');
  const txEep = form.elements.namedItem('tx_eep');
  const txProfile = form.elements.namedItem('tx_profile');

  if (mapping) {
    const sender = String(mapping.sender_eep || '').trim();
    communication.value = 'bidirectional_eep_pair';
    txEep.value = /^[0-9A-F]{2}-[0-9A-F]{2}-[0-9A-F]{2}$/i.test(sender) ? sender.toUpperCase() : '';
    txProfile.value = sender;
    return;
  }
  communication.value = String(definition?.direction || '').toLowerCase() === 'bidirectional'
    ? 'bidirectional_eep'
    : 'unidirectional';
  txEep.value = '';
  txProfile.value = '';
}

function validatePhysicalDeviceForm(form) {
  if (!form) return;
  const currentId = String(form._device?.device_id || '').trim().toUpperCase();
  const nameInput = form.elements.namedItem('device_name');
  const equipmentInput = form.elements.namedItem('equipment_id');
  const aliasInput = form.elements.namedItem('alias');
  const name = String(nameInput?.value || '').trim().toLowerCase();
  const equipment = String(equipmentInput?.value || '').trim().toLowerCase();
  const alias = deviceAliasFromName(nameInput?.value || '');
  const others = (state.physical || []).filter(
    (device) => String(device.device_id || '').trim().toUpperCase() !== currentId,
  );

  const duplicateName = name && others.some((device) => String(device.device_name || '').trim().toLowerCase() === name);
  const duplicateEquipment = equipment && others.some(
    (device) => String(device.metadata?.equipment_id || '').trim().toLowerCase() === equipment,
  );
  const duplicateAlias = alias && others.some((device) => String(device.alias || '').trim().toLowerCase() === alias);

  nameInput?.setCustomValidity(duplicateName ? 'Device name is already in use.' : '');
  equipmentInput?.setCustomValidity(duplicateEquipment ? 'Equipment ID is already in use.' : '');
  if (aliasInput) {
    aliasInput.value = alias;
    aliasInput.setCustomValidity(duplicateAlias ? 'Generated alias is already in use.' : '');
  }
}

function enhancePhysicalDeviceForm() {
  const form = document.getElementById('physicalDeviceForm');
  const options = deviceEnhancementState.options;
  if (!form || !options) return;
  const eep = registrySelect(form, 'eep', options.eeps || []);
  const profile = registrySelect(form, 'profile', options.profiles || []);
  const alias = form.elements.namedItem('alias');
  const communication = form.elements.namedItem('communication');
  const txEep = form.elements.namedItem('tx_eep');
  const txProfile = form.elements.namedItem('tx_profile');
  if (alias) alias.readOnly = true;
  if (communication) communication.disabled = true;
  if (txEep) txEep.readOnly = true;
  if (txProfile) txProfile.readOnly = true;

  const suggestions = options.suggestions || {};
  [
    ['manufacturer', 'deviceManufacturers', suggestions.manufacturers || []],
    ['model', 'deviceModels', suggestions.models || []],
    ['floor', 'deviceFloors', suggestions.floors || []],
    ['room', 'deviceRooms', suggestions.rooms || []],
  ].forEach(([name, listId, values]) => {
    registryDatalist(listId, values);
    form.elements.namedItem(name)?.setAttribute('list', listId);
  });

  if (form.dataset.registryEnhanced !== 'true') {
    form.elements.namedItem('device_name')?.addEventListener('input', () => validatePhysicalDeviceForm(form));
    form.elements.namedItem('equipment_id')?.addEventListener('input', () => validatePhysicalDeviceForm(form));
    eep?.addEventListener('change', () => applyProtocolBinding(form));
    profile?.addEventListener('change', () => applyProtocolBinding(form));
    form.addEventListener('submit', () => {
      validatePhysicalDeviceForm(form);
      applyProtocolBinding(form);
    }, { capture: true });
    form.dataset.registryEnhanced = 'true';
  }
  validatePhysicalDeviceForm(form);
  applyProtocolBinding(form);
}

function validateVirtualDeviceProfile(form) {
  const eep = form.elements.namedItem('eep');
  const profile = form.elements.namedItem('profile');
  if (eep) eep.required = !String(profile?.value || '').trim();
}

function enhanceVirtualDeviceForm() {
  const form = document.getElementById('virtualDeviceForm');
  const options = deviceEnhancementState.options;
  if (!form || !options) return;
  registrySelect(form, 'eep', options.eeps || []);
  registrySelect(form, 'profile', options.profiles || []);
  if (form.dataset.virtualProfileValidation !== 'true') {
    form.addEventListener('change', () => validateVirtualDeviceProfile(form));
    form.dataset.virtualProfileValidation = 'true';
  }
  validateVirtualDeviceProfile(form);
}

async function loadRegistryOptions() {
  try {
    deviceEnhancementState.options = await apiJson(`${managementUrl}/options`);
    enhancePhysicalDeviceForm();
    enhanceVirtualDeviceForm();
  } catch (error) {
    console.warn('Could not load device registry options', error);
  }
}

function rowDevice(kind, row) {
  if (kind === 'physical') {
    const id = row.cells[0]?.querySelector('.device-secondary')?.textContent?.trim().toUpperCase();
    return (state.physical || []).find((item) => String(item.device_id || '').toUpperCase() === id);
  }
  if (kind === 'virtual') {
    const id = row.cells[0]?.querySelector('.device-secondary')?.textContent?.trim().toLowerCase();
    return (state.virtual || []).find((item) => String(item.virtual_device_id || '').toLowerCase() === id);
  }
  const id = row.cells[0]?.textContent?.trim().toUpperCase();
  return (state.unknown || []).find((item) => String(item.sender_id || '').toUpperCase() === id);
}

function physicalValue(item, index) {
  return [item?.device_name, item?.registry_profile, item?.communication,
    item?.enabled === false ? -1 : (item?.active ? 1 : 0), item?.last_telegram?.timestamp_unix ?? 0,
    item?.last_telegram?.raw_telegram || item?.last_telegram?.data,
    (item?.teach_in_receivers || []).map((entry) => entry.receiver).join(', ')][index] ?? '';
}
function virtualValue(item, index) {
  return [item?.metadata?.device_name || item?.virtual_device_id, item?.sender_id, item?.registry_profile,
    (item?.channels || []).join(', '), item?.enabled === false ? 0 : 1,
    item?.last_telegram?.timestamp_unix ?? item?.last_telegram?.raw_telegram ?? '',
    (item?.teach_in_receivers || []).map((entry) => entry.receiver).join(', ')][index] ?? '';
}
function unknownValue(item, index) {
  return [item?.sender_id, item?.rorg, Number(item?.telegrams || 0), Date.parse(item?.first_seen || '') || 0,
    Date.parse(item?.last_seen || '') || 0, Number(item?.last_rssi_dbm ?? -999),
    item?.last_raw_telegram || item?.last_data][index] ?? '';
}
function compareDeviceValues(left, right) {
  if (typeof left === 'number' && typeof right === 'number') return left - right;
  return String(left ?? '').localeCompare(String(right ?? ''), undefined, { numeric: true, sensitivity: 'base' });
}

function sortDeviceTable(kind) {
  const body = document.getElementById(`${kind}DevicesBody`);
  if (!body || body.rows.length < 2) return;
  const currentRows = [...body.rows].filter((row) => !row.querySelector('.device-empty'));
  const rows = [...currentRows];
  const setting = deviceEnhancementState.sort[kind];
  const value = kind === 'physical' ? physicalValue : kind === 'virtual' ? virtualValue : unknownValue;
  rows.sort((left, right) => {
    const result = compareDeviceValues(value(rowDevice(kind, left), setting.index), value(rowDevice(kind, right), setting.index));
    return setting.direction === 'asc' ? result : -result;
  });
  if (!rows.some((row, index) => row !== currentRows[index])) return;
  rows.forEach((row) => body.append(row));
}

function installDeviceTableSorting() {
  ['physical', 'virtual', 'unknown'].forEach((kind) => {
    const body = document.getElementById(`${kind}DevicesBody`);
    const table = body?.closest('table');
    if (!table) return;
    const headers = [...table.tHead.rows[0].cells];
    headers.forEach((header, index) => {
      if (index === headers.length - 1) return;
      header.classList.add('device-sortable');
      header.tabIndex = 0;
      header.setAttribute('role', 'button');
      header.setAttribute('aria-sort', index === 0 ? 'ascending' : 'none');
      const activate = () => {
        const setting = deviceEnhancementState.sort[kind];
        if (setting.index === index) setting.direction = setting.direction === 'asc' ? 'desc' : 'asc';
        else Object.assign(setting, { index, direction: 'asc' });
        headers.forEach((item) => {
          item.removeAttribute('data-sort-direction');
          item.setAttribute('aria-sort', 'none');
        });
        header.dataset.sortDirection = setting.direction;
        header.setAttribute('aria-sort', setting.direction === 'asc' ? 'ascending' : 'descending');
        sortDeviceTable(kind);
      };
      header.addEventListener('click', activate);
      header.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
      });
    });
    headers[0].dataset.sortDirection = 'asc';
  });

  const originalRenderPanels = renderPanels;
  renderPanels = function enhancedRenderPanels() {
    originalRenderPanels();
    sortDeviceTable('physical');
    sortDeviceTable('virtual');
    sortDeviceTable('unknown');
  };
}

if (typeof openPhysicalDialog === 'function') {
  const originalOpenPhysicalDialog = openPhysicalDialog;
  openPhysicalDialog = function enhancedOpenPhysicalDialog(device = null, unknown = null) {
    originalOpenPhysicalDialog(device, unknown);
    enhancePhysicalDeviceForm();
    const form = document.getElementById('physicalDeviceForm');
    const deviceId = form?.elements.namedItem('device_id');
    if (deviceId) deviceId.readOnly = Boolean(device);
    validatePhysicalDeviceForm(form);
    applyProtocolBinding(form);
  };
}
if (typeof openVirtualDialog === 'function') {
  const originalOpenVirtualDialog = openVirtualDialog;
  openVirtualDialog = function enhancedOpenVirtualDialog(device = null) {
    originalOpenVirtualDialog(device);
    enhanceVirtualDeviceForm();
  };
}

installDeviceTableSorting();
loadRegistryOptions();
