const configurationGrid = document.getElementById('configurationGrid');
const configurationStatus = document.getElementById('configurationStatus');
const configurationStatusText = document.getElementById('configurationStatusText');
const configurationMessage = document.getElementById('configurationMessage');
const saveConfigurationButton = document.getElementById('saveConfigurationButton');
const restartGatewayButton = document.getElementById('restartGatewayButton');

let originalConfig = null;
let draftConfig = null;
let configurationSchema = null;
let canWrite = false;
let dirty = false;
let pendingMqttPassword = '';
let pendingPushoverTokens = {};

const configurationGroups = [
  {
    key: 'application',
    label: 'Application',
    description: 'Application and Paths',
    sections: ['application', 'paths'],
  },
  {
    key: 'enocean',
    label: 'EnOcean',
    description: 'EnOcean and Metrics',
    sections: ['enocean', 'metrics'],
  },
  {
    key: 'mqtt',
    label: 'MQTT',
    description: 'MQTT, Topics, Gateway and Publish Defaults',
    sections: ['mqtt', 'topics', 'gateway', 'publish_defaults'],
  },
  { key: 'sqlite', label: 'SQLite', description: 'Telegram persistence', sections: ['sqlite'] },
  { key: 'api', label: 'API', description: 'Web API and authentication', sections: ['web_api'] },
  { key: 'logging', label: 'Logging', description: 'Runtime logging', sections: ['logging'] },
  { key: 'notifications', label: 'Notifications', description: 'Pushover messages', sections: ['notifications'] },
];

const configurationGroupStorageKey = 'enocean-mqtt.settings.open-groups';
const groupKeyBySection = new Map(
  configurationGroups.flatMap((group) => group.sections.map((section) => [section, group.key])),
);

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
  const csrfHeaders = ['GET', 'HEAD', 'OPTIONS'].includes(method)
    ? {}
    : { 'X-CSRF-Token': cookieValue('enocean_web_csrf') };

  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...csrfHeaders,
      ...(options.headers || {}),
    },
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    const message = typeof detail === 'string'
      ? detail
      : detail?.message || `${url}: HTTP ${response.status}`;
    const error = new Error(message);
    error.payload = payload;
    throw error;
  }
  return payload;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function setStatus(label, state = 'neutral') {
  if (!configurationStatus || !configurationStatusText) return;
  configurationStatus.classList.remove('ok', 'neutral', 'problem', 'warn');
  configurationStatus.classList.add(state);
  configurationStatusText.textContent = label;
}

function setMessage(message = '', className = '') {
  if (!configurationMessage) return;
  configurationMessage.textContent = message;
  configurationMessage.classList.remove('configuration-error', 'configuration-warning');
  if (className) configurationMessage.classList.add(className);
}

function pathParts(path) {
  return String(path).split('.').filter(Boolean);
}

function setPathValue(root, path, value) {
  const parts = pathParts(path);
  let target = root;
  for (let index = 0; index < parts.length - 1; index += 1) {
    target = target[parts[index]];
  }
  target[parts.at(-1)] = value;
}

function canonical(value) {
  return JSON.stringify(value);
}

function updateDirtyState() {
  dirty = canonical(draftConfig) !== canonical(originalConfig) || pendingMqttPassword !== ''
    || Object.keys(pendingPushoverTokens).length > 0;
  if (saveConfigurationButton) saveConfigurationButton.disabled = !canWrite || !dirty;
  if (restartGatewayButton) restartGatewayButton.disabled = !canWrite || dirty;

  if (!canWrite) {
    setStatus('Read only', 'neutral');
    setMessage('Administrator privileges are required to change settings.');
  } else if (dirty) {
    setStatus('Unsaved changes', 'warn');
    setMessage('Changes have not been saved.', 'configuration-warning');
  } else {
    setStatus('Valid', 'ok');
    setMessage('');
  }
}

function createControl(node) {
  if (node.control === 'pushover-secret') {
    const input = document.createElement('input');
    input.className = 'configuration-control';
    input.type = 'password';
    input.autocomplete = 'new-password';
    input.placeholder = node.configured ? '••••••••' : `Enter ${node.label}`;
    input.value = pendingPushoverTokens[node.secret_name] || '';
    input.disabled = !canWrite;
    input.addEventListener('input', () => {
      if (input.value.trim()) pendingPushoverTokens[node.secret_name] = input.value.trim();
      else delete pendingPushoverTokens[node.secret_name];
      updateDirtyState();
    });
    return input;
  }
  if (node.control === 'password-secret') {
    const input = document.createElement('input');
    input.className = 'configuration-control';
    input.type = 'password';
    input.autocomplete = 'new-password';
    input.placeholder = node.configured ? '••••••••' : 'Enter MQTT password';
    input.disabled = !canWrite;
    input.addEventListener('input', () => {
      pendingMqttPassword = input.value;
      updateDirtyState();
    });
    return input;
  }

  if (node.control === 'default-interface') {
    const interfaces = draftConfig?.enocean?.interfaces || [];
    const select = document.createElement('select');
    select.className = 'configuration-control';
    select.disabled = !canWrite || interfaces.length < 2;
    interfaces.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.interface_id || '';
      option.textContent = item.interface_id || '(unnamed interface)';
      option.selected = option.value === draftConfig.enocean.default_interface;
      select.append(option);
    });
    select.addEventListener('change', () => {
      draftConfig.enocean.default_interface = select.value;
      updateDirtyState();
    });
    return select;
  }

  if (node.type === 'boolean') {
    const label = document.createElement('label');
    label.className = 'configuration-switch';

    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = Boolean(node.value);
    input.disabled = !canWrite;
    input.dataset.path = node.path;
    input.setAttribute('aria-label', node.label);

    const track = document.createElement('span');
    track.className = 'configuration-switch-track';

    input.addEventListener('change', () => {
      setPathValue(draftConfig, node.path, input.checked);
      updateDirtyState();
    });

    label.append(input, track);
    return label;
  }

  if (node.type === 'array') {
    const textarea = document.createElement('textarea');
    textarea.className = 'configuration-json';
    textarea.value = JSON.stringify(node.value, null, 2);
    textarea.disabled = !canWrite;
    textarea.dataset.path = node.path;
    textarea.addEventListener('change', () => {
      try {
        const value = JSON.parse(textarea.value);
        if (!Array.isArray(value)) throw new Error('Value must be a JSON array');
        textarea.setCustomValidity('');
        setPathValue(draftConfig, node.path, value);
        updateDirtyState();
      } catch (error) {
        textarea.setCustomValidity(error.message);
        textarea.reportValidity();
      }
    });
    return textarea;
  }

  if (node.control === 'select') {
    const select = document.createElement('select');
    select.className = 'configuration-control';
    select.disabled = !canWrite;
    select.dataset.path = node.path;
    (node.options || []).forEach((optionValue) => {
      const option = document.createElement('option');
      option.value = optionValue;
      option.textContent = optionValue;
      option.selected = optionValue === node.value;
      select.append(option);
    });
    select.addEventListener('change', () => {
      setPathValue(draftConfig, node.path, select.value);
      updateDirtyState();
    });
    return select;
  }

  const input = document.createElement('input');
  input.className = 'configuration-control';
  input.disabled = !canWrite;
  input.dataset.path = node.path;

  if (node.type === 'integer' || node.type === 'number') {
    input.type = 'number';
    input.step = node.type === 'integer' ? '1' : 'any';
    input.value = node.value ?? '';
  } else {
    input.type = 'text';
    input.value = node.value ?? '';
  }

  input.addEventListener('input', () => {
    let value = input.value;
    if (node.type === 'integer') {
      value = input.value === '' ? null : Number.parseInt(input.value, 10);
    } else if (node.type === 'number') {
      value = input.value === '' ? null : Number(input.value);
    } else if (node.type === 'nullable') {
      const trimmed = input.value.trim();
      value = trimmed === ''
        ? null
        : (/^-?\d+(\.\d+)?$/.test(trimmed) ? Number(trimmed) : input.value);
    }
    setPathValue(draftConfig, node.path, value);
    updateDirtyState();
  });

  if (/^enocean\.interfaces\.\d+\.interface_id$/.test(node.path)) {
    input.addEventListener('change', () => {
      normalizeDefaultInterface();
      renderConfiguration();
      updateDirtyState();
    });
  }

  return input;
}

function interfaceTemplate(interfaces) {
  const existingIds = new Set(interfaces.map((item) => item.interface_id));
  let index = interfaces.length + 1;
  while (existingIds.has(`interface_${index}`)) index += 1;
  return {
    interface_id: `interface_${index}`,
    enabled: false,
    tx_enabled: false,
    type: 'serial_esp3',
    device: '/dev/ttyUSB0',
    base_id: null,
    baudrate: 57600,
    timeout_seconds: 1.0,
    reconnect: { enabled: true, initial_delay_seconds: 5, max_delay_seconds: 60 },
    network_bridge: { enabled: false, host: '0.0.0.0', port: 7000, ser2net_binary: '/usr/sbin/ser2net' },
  };
}

function normalizeDefaultInterface() {
  const interfaces = draftConfig?.enocean?.interfaces || [];
  const ids = interfaces.map((item) => item.interface_id).filter(Boolean);
  if (interfaces.length === 1) {
    draftConfig.enocean.default_interface = interfaces[0].interface_id || null;
  } else if (!ids.includes(draftConfig.enocean.default_interface)) {
    draftConfig.enocean.default_interface = ids[0] || null;
  }
}

function appendInterfaceEditor(container) {
  const editor = document.createElement('div');
  editor.className = 'configuration-interface-editor';
  const interfaces = draftConfig.enocean.interfaces;

  interfaces.forEach((item, index) => {
    const card = document.createElement('section');
    card.className = 'configuration-interface-card';
    const header = document.createElement('div');
    header.className = 'configuration-interface-header';
    const title = document.createElement('h3');
    title.textContent = item.interface_id || `Interface ${index + 1}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'configuration-icon-button danger';
    remove.textContent = '🗑';
    remove.title = 'Delete interface';
    remove.disabled = !canWrite;
    remove.addEventListener('click', () => {
      interfaces.splice(index, 1);
      normalizeDefaultInterface();
      renderConfiguration();
      updateDirtyState();
    });
    header.append(title, remove);
    card.append(header);

    const fields = document.createElement('div');
    fields.className = 'configuration-fields';
    Object.entries(item).forEach(([key, value]) => {
      const path = `enocean.interfaces.${index}.${key}`;
      const node = { key, path, label: key.replaceAll('_', ' '), value };
      if (typeof value === 'boolean') node.type = 'boolean';
      else if (typeof value === 'number') node.type = Number.isInteger(value) ? 'integer' : 'number';
      else if (value === null) node.type = 'nullable';
      else if (typeof value === 'object') node.type = 'object';
      else node.type = 'string';
      if (key === 'type') { node.control = 'select'; node.options = ['serial_esp3']; }
      if (node.type === 'object') {
        const subgroup = document.createElement('section');
        subgroup.className = 'configuration-subgroup';
        const subtitle = document.createElement('h4');
        subtitle.className = 'configuration-subgroup-title';
        subtitle.textContent = node.label;
        const nested = document.createElement('div');
        nested.className = 'configuration-fields';
        Object.entries(value).forEach(([nestedKey, nestedValue]) => {
          appendScalarField(nested, {
            key: nestedKey,
            path: `${path}.${nestedKey}`,
            label: nestedKey.replaceAll('_', ' '),
            value: nestedValue,
            type: typeof nestedValue === 'boolean' ? 'boolean' : (typeof nestedValue === 'number' ? (Number.isInteger(nestedValue) ? 'integer' : 'number') : 'string'),
          });
        });
        subgroup.append(subtitle, nested);
        fields.append(subgroup);
      } else {
        appendScalarField(fields, node);
      }
    });
    card.append(fields);
    editor.append(card);
  });

  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'configuration-button configuration-add-button';
  add.textContent = '+ Add interface';
  add.disabled = !canWrite;
  add.addEventListener('click', () => {
    interfaces.push(interfaceTemplate(interfaces));
    normalizeDefaultInterface();
    renderConfiguration();
    updateDirtyState();
  });
  editor.append(add);
  container.append(editor);
}

function appendTokenManager(container, node) {
  const manager = document.createElement('div');
  manager.className = 'configuration-token-manager';
  const list = document.createElement('div');
  list.className = 'configuration-token-list';
  (node.tokens || []).forEach((entry) => {
    const row = document.createElement('div');
    row.className = 'configuration-token-row';
    const identity = document.createElement('span');
    identity.textContent = `${entry.name} · ${(entry.roles || []).join(', ')}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'configuration-icon-button danger';
    remove.textContent = '🗑';
    remove.title = `Delete token ${entry.name}`;
    remove.disabled = !canWrite;
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Delete API token “${entry.name}”?`)) return;
      try {
        await apiJson(`/api/v1/config/api-tokens/${encodeURIComponent(entry.name)}`, { method: 'DELETE' });
        await loadConfiguration();
      } catch (error) { setMessage(error.message, 'configuration-error'); }
    });
    row.append(identity, remove);
    list.append(row);
  });

  const form = document.createElement('div');
  form.className = 'configuration-token-form';
  const name = document.createElement('input');
  name.className = 'configuration-control';
  name.placeholder = 'Token name';
  name.disabled = !canWrite;
  const role = document.createElement('select');
  role.className = 'configuration-control';
  role.disabled = !canWrite;
  (node.roles || []).forEach((value) => role.append(new Option(value, value)));
  const create = document.createElement('button');
  create.type = 'button';
  create.className = 'configuration-button';
  create.textContent = '+ Create token';
  create.disabled = !canWrite;
  create.addEventListener('click', async () => {
    try {
      const result = await apiJson('/api/v1/config/api-tokens', {
        method: 'POST', body: JSON.stringify({ name: name.value, role: role.value }),
      });
      window.prompt('Copy this token now. It will not be shown again.', result.token);
      await loadConfiguration();
    } catch (error) { setMessage(error.message, 'configuration-error'); }
  });
  form.append(name, role, create);
  manager.append(list, form);
  container.append(manager);
}

function appendScalarField(container, node) {
  if (node.control === 'interfaces') {
    appendInterfaceEditor(container);
    return;
  }
  if (node.control === 'api-tokens') {
    appendTokenManager(container, node);
    return;
  }
  const row = document.createElement('div');
  row.className = `configuration-field${node.type === 'array' ? ' configuration-json-field' : ''}`;

  const label = document.createElement('label');
  label.className = 'configuration-field-label';
  label.textContent = node.label;

  const control = createControl(node);
  if (control.id) label.htmlFor = control.id;

  row.append(label, control);
  container.append(row);
}

function appendObjectFields(container, node) {
  (node.children || []).forEach((child) => {
    if (child.type !== 'object') {
      appendScalarField(container, child);
      return;
    }

    const subgroup = document.createElement('section');
    subgroup.className = 'configuration-subgroup';

    const title = document.createElement('h3');
    title.className = 'configuration-subgroup-title';
    title.textContent = child.label;
    subgroup.append(title);

    const fields = document.createElement('div');
    fields.className = 'configuration-fields';
    appendObjectFields(fields, child);
    subgroup.append(fields);
    container.append(subgroup);
  });
}

function storedOpenConfigurationGroups() {
  try {
    const value = JSON.parse(window.localStorage.getItem(configurationGroupStorageKey) || 'null');
    if (Array.isArray(value)) return new Set(value);
  } catch (error) {
    console.debug('Could not restore Settings section state', error);
  }
  return new Set(['application']);
}

function currentOpenConfigurationGroups() {
  const renderedGroups = configurationGrid?.querySelectorAll('.configuration-group') || [];
  if (renderedGroups.length === 0) return storedOpenConfigurationGroups();
  return new Set(
    [...renderedGroups]
      .filter((group) => group.open)
      .map((group) => group.dataset.group)
      .filter(Boolean),
  );
}

function saveOpenConfigurationGroups() {
  if (!configurationGrid) return;
  const openGroups = [...configurationGrid.querySelectorAll('.configuration-group')]
    .filter((group) => group.open)
    .map((group) => group.dataset.group)
    .filter(Boolean);
  try {
    window.localStorage.setItem(configurationGroupStorageKey, JSON.stringify(openGroups));
  } catch (error) {
    console.debug('Could not store Settings section state', error);
  }
}

function openConfigurationGroupForPath(path) {
  const sectionKey = pathParts(path)[0];
  const groupKey = groupKeyBySection.get(sectionKey);
  if (!groupKey || !configurationGrid) return;
  const group = configurationGrid.querySelector(`[data-group="${groupKey}"]`);
  if (group) {
    group.open = true;
    saveOpenConfigurationGroups();
  }
}

function createConfigurationSection(section, showHeading) {
  const article = document.createElement('section');
  article.className = 'configuration-section';
  article.dataset.section = section.key;

  if (showHeading) {
    const heading = document.createElement('div');
    heading.className = 'card-heading configuration-section-heading';

    const title = document.createElement('h3');
    title.textContent = section.label;
    heading.append(title);
    article.append(heading);
  }

  const fields = document.createElement('div');
  fields.className = 'configuration-fields';
  if (section.type === 'object') appendObjectFields(fields, section);
  else appendScalarField(fields, section);
  article.append(fields);
  if (section.key === 'notifications') {
    const testButton = document.createElement('button');
    testButton.type = 'button';
    testButton.className = 'configuration-button';
    testButton.textContent = 'Send Pushover test message';
    testButton.disabled = !canWrite;
    testButton.addEventListener('click', async () => {
      if (dirty) {
        setMessage('Save settings before sending a test message.', 'configuration-warning');
        return;
      }
      testButton.disabled = true;
      try {
        await apiJson('/api/v1/notifications/pushover/send', {
          method: 'POST',
          body: JSON.stringify({
            title: (draftConfig.application?.name || 'enocean-mqtt').slice(0, 250),
            message: 'Pushover test message from your EnOcean gateway.',
          }),
        });
        setMessage('Test message accepted by Pushover.');
      } catch (error) {
        setMessage(error.message, 'configuration-error');
      } finally {
        testButton.disabled = !canWrite;
      }
    });
    article.append(testButton);
  }
  return article;
}

function createConfigurationGroup(groupDefinition, sections, openGroups) {
  const group = document.createElement('details');
  group.className = 'compact-card configuration-group';
  group.dataset.group = groupDefinition.key;
  group.open = openGroups.has(groupDefinition.key);

  const summary = document.createElement('summary');
  summary.className = 'configuration-group-summary';

  const title = document.createElement('span');
  title.className = 'configuration-group-title';
  title.textContent = groupDefinition.label;

  const description = document.createElement('span');
  description.className = 'configuration-group-description';
  description.textContent = groupDefinition.description;

  const indicator = document.createElement('span');
  indicator.className = 'configuration-group-indicator';
  indicator.setAttribute('aria-hidden', 'true');

  summary.append(title, description, indicator);

  const content = document.createElement('div');
  content.className = 'configuration-group-content';
  const showSectionHeadings = sections.length > 1;
  sections.forEach((section) => {
    content.append(createConfigurationSection(section, showSectionHeadings));
  });

  group.append(summary, content);
  group.addEventListener('toggle', saveOpenConfigurationGroups);
  return group;
}

function renderConfiguration() {
  if (!configurationGrid || !configurationSchema) return;
  const openGroups = currentOpenConfigurationGroups();
  configurationGrid.replaceChildren();
  const sectionsByKey = new Map(
    (configurationSchema.sections || []).map((section) => [section.key, section]),
  );
  const renderedSectionKeys = new Set();

  configurationGroups.forEach((groupDefinition) => {
    const sections = groupDefinition.sections
      .map((sectionKey) => sectionsByKey.get(sectionKey))
      .filter(Boolean);
    if (sections.length === 0) return;
    sections.forEach((section) => renderedSectionKeys.add(section.key));
    configurationGrid.append(
      createConfigurationGroup(groupDefinition, sections, openGroups),
    );
  });

  const remainingSections = (configurationSchema.sections || [])
    .filter((section) => !renderedSectionKeys.has(section.key));
  if (remainingSections.length > 0) {
    configurationGrid.append(createConfigurationGroup(
      {
        key: 'other',
        label: 'Other',
        description: 'Additional configuration',
        sections: remainingSections.map((section) => section.key),
      },
      remainingSections,
      openGroups,
    ));
  }
}

async function loadConfiguration() {
  setStatus('Loading', 'neutral');
  try {
    const payload = await apiJson('/api/v1/config');
    originalConfig = clone(payload.config || {});
    draftConfig = clone(payload.config || {});
    configurationSchema = payload.schema || { sections: [] };
    canWrite = Boolean(payload.can_write);
    pendingMqttPassword = '';
    pendingPushoverTokens = {};
    normalizeDefaultInterface();
    renderConfiguration();
    updateDirtyState();
  } catch (error) {
    console.warn('Failed to load configuration', error);
    setStatus('Unavailable', 'problem');
    setMessage(error.message, 'configuration-error');
  }
}

async function saveConfiguration() {
  if (!canWrite || !dirty) return;

  setStatus('Saving', 'neutral');
  setMessage('Validating and saving configuration…');
  if (saveConfigurationButton) saveConfigurationButton.disabled = true;

  try {
    const payload = await apiJson('/api/v1/config', {
      method: 'PUT',
      body: JSON.stringify({
        config: draftConfig,
        ...(pendingMqttPassword ? { mqtt_password: pendingMqttPassword } : {}),
        ...pendingPushoverTokens,
      }),
    });

    originalConfig = clone(payload.config || draftConfig);
    draftConfig = clone(originalConfig);
    configurationSchema = payload.schema || configurationSchema;
    dirty = false;
    pendingMqttPassword = '';
    pendingPushoverTokens = {};
    renderConfiguration();
    if (saveConfigurationButton) saveConfigurationButton.disabled = true;
    setStatus('Saved', 'ok');
    if (restartGatewayButton) {
      restartGatewayButton.disabled = false;
      restartGatewayButton.classList.toggle('restart-required', Boolean(payload.restart_required));
    }
    setMessage(
      payload.restart_required
        ? 'Settings saved. Restart required for the new configuration to take effect.'
        : 'Settings saved.'
    );
  } catch (error) {
    console.warn('Failed to save configuration', error);
    setStatus('Invalid', 'problem');
    const validationErrors = error.payload?.detail?.errors;
    if (Array.isArray(validationErrors) && validationErrors.length > 0) {
      const first = validationErrors[0];
      const location = Array.isArray(first.loc) ? first.loc.join('.') : '';
      openConfigurationGroupForPath(location);
      setMessage(`${location ? `${location}: ` : ''}${first.msg || error.message}`, 'configuration-error');
    } else {
      setMessage(error.message, 'configuration-error');
    }
    if (saveConfigurationButton) saveConfigurationButton.disabled = false;
  }
}

async function restartGateway() {
  if (!canWrite) return;
  if (dirty) {
    setMessage('Save or discard the unsaved changes before restarting.', 'configuration-warning');
    return;
  }
  if (!window.confirm('Restart the gateway runtime now?')) return;

  if (restartGatewayButton) restartGatewayButton.disabled = true;
  if (saveConfigurationButton) saveConfigurationButton.disabled = true;
  setStatus('Restarting', 'neutral');
  setMessage('Restarting gateway…');

  try {
    const payload = await apiJson('/api/v1/runtime/commands/gateway.restart', {
      method: 'POST',
      body: '{}',
    });
    if (restartGatewayButton) restartGatewayButton.classList.remove('restart-required');
    setMessage(`Gateway restart ${payload.status || 'accepted'}. The page will reconnect automatically.`);
    window.setTimeout(() => window.location.reload(), 3000);
  } catch (error) {
    console.warn('Failed to restart gateway', error);
    setStatus('Restart failed', 'problem');
    setMessage(error.message, 'configuration-error');
    if (restartGatewayButton) restartGatewayButton.disabled = !canWrite;
  }
}

if (saveConfigurationButton) {
  saveConfigurationButton.addEventListener('click', saveConfiguration);
}

if (restartGatewayButton) {
  restartGatewayButton.addEventListener('click', restartGateway);
}

window.addEventListener('beforeunload', (event) => {
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = '';
});

document.addEventListener('click', (event) => {
  if (!dirty) return;
  const link = event.target.closest('a[href]');
  if (!link) return;
  if (!window.confirm('Discard unsaved configuration changes and leave this page?')) {
    event.preventDefault();
  }
});

loadConfiguration();
