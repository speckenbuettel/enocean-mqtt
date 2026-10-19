/* External gateways and optional per-channel command profiles. */
const gatewayDialog = document.getElementById('gatewayDialog');
const gatewayForm = document.getElementById('gatewayForm');
const gatewayChannels = document.getElementById('gatewayChannels');

function addGatewayChannel(channel = {}) {
  const row = node('div', 'device-form-grid');
  [['offset', 'Offset', 'number'], ['name', 'Name', 'text'], ['profile', 'Profile', 'text'], ['description', 'Description', 'text']].forEach(([key, label, type]) => {
    const field = node('label', '', label);
    const input = document.createElement('input');
    input.type = type;
    input.dataset.field = key;
    input.value = channel[key] ?? '';
    input.required = key === 'offset';
    if (key === 'offset') { input.min = '0'; input.max = '127'; }
    if (key === 'profile') input.setAttribute('list', 'deviceProfiles');
    field.append(input);
    row.append(field);
  });
  const remove = node('button', 'device-button', 'Remove channel');
  remove.type = 'button';
  remove.addEventListener('click', () => row.remove());
  row.append(remove);
  gatewayChannels.append(row);
}

function openGatewayDialog(gateway = null, unknown = null) {
  gatewayForm.reset();
  document.getElementById('gatewayFormError').textContent = '';
  ['base_id', 'name', 'manufacturer', 'model', 'description', 'sender_count'].forEach((key) => {
    gatewayForm.elements.namedItem(key).value = gateway?.[key] ?? (key === 'sender_count' ? 128 : '');
  });
  gatewayForm.elements.namedItem('base_id').readOnly = Boolean(gateway);
  gatewayForm.dataset.revision = gateway?.revision || '';
  gatewayForm.dataset.sourceSender = unknown?.sender_id || '';
  const source = document.getElementById('gatewaySourceSender');
  source.textContent = '';
  if (!gateway && unknown) {
    const sender = parseInt(unknown.sender_id, 16);
    const standard = /^[A-F0-9]{8}$/i.test(unknown.sender_id) && sender >= 0xFF800000 && sender <= 0xFFFFFFFE;
    gatewayForm.elements.namedItem('base_id').value = standard
      ? (sender - sender % 128).toString(16).toUpperCase().padStart(8, '0') : '';
    source.textContent = `Source sender: ${unknown.sender_id}. ${standard ? `Standard Base-ID block; channel offset ${sender % 128}. Verify against the gateway configuration.` : 'Confirm the gateway Base ID; this sender is outside the standard Base-ID address range.'}`;
  }
  gatewayChannels.replaceChildren();
  (gateway?.channels || []).forEach(addGatewayChannel);
  gatewayDialog.showModal();
}

function renderGateways() {
  const body = document.getElementById('gatewaysBody');
  body.replaceChildren();
  const gateways = state.gateways.filter((item) => matchesSearch([
    item.name, item.base_id, item.manufacturer, item.model,
    ...item.channels.flatMap((channel) => [channel.name, channel.profile]),
    ...(item.observed_channels || []).flatMap((channel) => [channel.sender_id, channel.name]),
  ]));
  document.getElementById('gatewayPanelCount').textContent = `${gateways.length} gateways`;
  gateways.forEach((gateway) => {
    const row = body.insertRow();
    row.append(cell(identityCell(gateway.name, [gateway.manufacturer, gateway.model].filter(Boolean).join(' '))));
    row.append(cell(gateway.base_id, 'device-mono'));
    const end = (parseInt(gateway.base_id, 16) + gateway.sender_count - 1).toString(16).toUpperCase().padStart(8, '0');
    row.append(cell(`${gateway.base_id} – ${end}`));
    row.append(cell(gateway.channels.map((channel) => `${channel.offset}: ${channel.profile || 'No EEP assigned'}`).join(', ') || 'None'));
    const actions = node('div', 'device-row-actions');
    [['Edit', () => openGatewayDialog(gateway)], ['Delete', async () => {
      if (!confirm(`Delete gateway ${gateway.name}? Its sender IDs will be classified individually again.`)) return;
      try {
        await apiJson(`${managementUrl}/gateways/${gateway.base_id}`, { method: 'DELETE' });
        await loadDevices();
      } catch (error) { setMessage(error.message, 'error'); }
    }]].forEach(([label, callback]) => {
      const button = node('button', 'device-button', label);
      button.type = 'button';
      button.disabled = !state.canWrite;
      button.addEventListener('click', callback);
      actions.append(button);
    });
    row.append(cell(actions));
    renderGatewayChannelTable(body, gateway);
  });
  if (!gateways.length) emptyRow(body, 5, 'No gateways match the current filters.');
}

document.getElementById('newGatewayButton').addEventListener('click', () => openGatewayDialog());
document.getElementById('addGatewayChannel').addEventListener('click', () => addGatewayChannel());
gatewayForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(gatewayForm));
  data.sender_count = Number(data.sender_count);
  data.expected_revision = gatewayForm.dataset.revision;
  if (gatewayForm.dataset.sourceSender) data.source_sender_id = gatewayForm.dataset.sourceSender;
  data.channels = Array.from(gatewayChannels.children).map((row) => {
    const value = (key) => row.querySelector(`[data-field="${key}"]`).value.trim();
    return { offset: Number(value('offset')), name: value('name') || null, profile: value('profile') || null, description: value('description') || null };
  });
  try {
    await apiJson(`${managementUrl}/gateways/${encodeURIComponent(data.base_id)}`, {
      method: 'PUT', body: JSON.stringify(data),
    });
    gatewayDialog.close();
    await loadDevices();
  } catch (error) { document.getElementById('gatewayFormError').textContent = error.message; }
});

document.getElementById('newGatewayButton').disabled = !state.canWrite;
renderGateways();

function gatewaySeen(timestamp) {
  return relativeTime(timestamp === null || timestamp === undefined ? null : new Date(timestamp * 1000).toISOString());
}

function gatewayMetricsDetails(metrics) {
  const details = node('details');
  details.append(node('summary', '', `${metrics.rx_telegrams_total || 0} RX`));
  const lines = node('div');
  const labels = {
    rx_telegrams_total: 'Received telegrams', decoded_commands_total: 'Decoded commands',
    decode_errors_total: 'Decode errors', unsupported_telegrams_total: 'Unsupported telegrams',
    unassigned_telegrams_total: 'Without assigned profile', teach_in_telegrams_total: 'Teach-In telegrams',
    other_telegrams_total: 'Other telegrams', original_telegrams_total: 'Original telegrams',
    repeated_telegrams_total: 'Repeated telegrams', unclassified_telegrams_total: 'Repetition unknown',
    configured_channels_total: 'Configured channels', known_channels_total: 'Assigned channels',
    observed_channels_total: 'Observed channels', unknown_channels_total: 'Channels needing a profile',
    active_channels_total: 'Active channels', sender_capacity: 'Sender capacity',
    telegrams_per_minute: 'Recent telegrams/min', peak_telegrams_per_minute: 'Peak telegrams/min',
  };
  for (const [key, value] of Object.entries(metrics)) lines.append(node('div', '', `${labels[key] || key}: ${value}`));
  details.append(lines);
  return details;
}

function renderGatewayChannelTable(body, gateway) {
  const row = body.insertRow();
  const container = row.insertCell();
  container.colSpan = 5;
  const metrics = gateway.metrics || {};
  const received = (gateway.observed_channels || []).filter((channel) => channel.observed);
  const assigned = received.filter((channel) => channel.assignment_status === 'known').length;
  container.append(node('p', '', `${received.length} observed channels · ${assigned} with assigned EEP · ${received.length - assigned} unknown · ${metrics.active_channels_total || 0} active`));
  const source = gateway.observation?.source === 'sqlite_retained'
    ? 'Stored radio history (limited by retention and storage settings)'
    : 'This process only; earlier radio history unavailable';
  container.append(node('p', 'device-secondary', `${source}. Received traffic only, excluding replay. Last seen: ${gatewaySeen(gateway.observation?.last_seen)}.`));
  container.append(node('p', 'device-secondary', `${metrics.configured_channels_total || 0} channels configured in total. Recent traffic (${(gateway.observation?.rate_window_seconds || 3600) / 60} min): ${gateway.rates?.telegrams_per_minute ?? '—'} telegrams/min; peak (${(gateway.observation?.peak_window_seconds || 900) / 60} min window): ${gateway.rates?.peak_telegrams_per_minute ?? '—'} telegrams/min.${gateway.rates?.rate_samples_complete === false ? ' Rate history is incomplete.' : ''}`));
  (gateway.issues || []).forEach((issue) => container.append(node('p', 'device-message warning', issue)));
  container.append(gatewayMetricsDetails(metrics));
  const wrap = node('div', 'device-table-wrap');
  const table = node('table', 'device-table');
  const head = table.createTHead().insertRow();
  ['Sender ID / offset', 'Name / profile', 'Status', 'Telegrams', 'First seen', 'Last seen', 'RSSI', 'Last telegram', 'Actions'].forEach((label) => head.append(node('th', '', label)));
  const channelsBody = table.createTBody();
  const channels = received;
  channels.forEach((channel) => {
    const channelRow = channelsBody.insertRow();
    channelRow.append(cell(identityCell(channel.sender_id, `Offset ${channel.offset}`)));
    channelRow.append(cell(identityCell(channel.name || 'Unassigned', channel.profile || 'No EEP assigned')));
    const status = node('span', '', channel.assignment_status === 'known' ? 'Known channel' : 'Unknown channel');
    status.title = channel.decode_error || channel.decode_status || '';
    const decodeLabels = {
      decoded: 'Decoded', no_profile: 'No profile assigned', invalid_profile: 'Invalid profile',
      malformed_payload: 'Malformed command', unsupported_variant: 'Unsupported command',
      teach_in: 'Teach-In', not_applicable: 'Other radio traffic',
    };
    status.append(node('span', 'device-secondary', `${channel.active ? 'Active' : 'Inactive'} · ${decodeLabels[channel.decode_status] || 'Not decoded'}${channel.profile_source === 'legacy_device' ? ' (legacy profile)' : ''}`));
    channelRow.append(cell(status));
    channelRow.append(cell(gatewayMetricsDetails({ ...channel.metrics,
      telegrams_per_minute: channel.rates?.telegrams_per_minute ?? '—',
      peak_telegrams_per_minute: channel.rates?.peak_telegrams_per_minute ?? '—',
    })));
    channelRow.append(cell(gatewaySeen(channel.first_seen)));
    channelRow.append(cell(gatewaySeen(channel.last_seen)));
    channelRow.append(cell(channel.last_rssi_dbm === null || channel.last_rssi_dbm === undefined ? '—' : `${channel.last_rssi_dbm} dBm`));
    channelRow.append(cell(telegramCell(channel.last_telegram)));
    const button = node('button', 'device-button', channel.configured ? 'Edit channel' : 'Register as gateway channel');
    button.type = 'button';
    button.disabled = !state.canWrite;
    button.addEventListener('click', () => openGatewayChannelDialog(gateway, channel));
    channelRow.append(cell(button));
  });
  if (!channels.length) emptyRow(channelsBody, 9, 'No received channel telegrams in the available observation history.');
  wrap.append(table);
  container.append(wrap);
}

function openGatewayChannelDialog(gateway, channel) {
  const form = document.getElementById('gatewayChannelForm');
  form.reset();
  form._gateway = gateway;
  form._channel = channel;
  ['base_id', 'sender_id', 'offset', 'name', 'profile', 'description'].forEach((key) => {
    form.elements.namedItem(key).value = key === 'base_id' ? gateway.base_id : channel[key] ?? '';
  });
  document.getElementById('gatewayChannelError').textContent = '';
  document.getElementById('gatewayChannelDialog').showModal();
}

document.getElementById('gatewayChannelForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const gateway = form._gateway;
  const channel = form._channel;
  const value = (key) => form.elements.namedItem(key).value.trim() || null;
  const channels = gateway.channels.filter((item) => item.offset !== channel.offset);
  channels.push({ offset: channel.offset, name: value('name'), profile: value('profile'), description: value('description') });
  const payload = Object.fromEntries(['name', 'manufacturer', 'model', 'description', 'sender_count'].map((key) => [key, gateway[key]]));
  payload.channels = channels;
  payload.expected_revision = gateway.revision;
  try {
    await apiJson(`${managementUrl}/gateways/${gateway.base_id}`, { method: 'PUT', body: JSON.stringify(payload) });
    document.getElementById('gatewayChannelDialog').close();
    await loadDevices();
  } catch (error) { document.getElementById('gatewayChannelError').textContent = error.message; }
});
