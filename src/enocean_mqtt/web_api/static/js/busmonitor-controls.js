const loadAllButton = document.getElementById('loadAllButton');
const busmonitorModeStatus = document.getElementById('busmonitorModeStatus');

function setBusmonitorModeStatus(text, state = 'ok') {
  if (!busmonitorModeStatus) return;

  busmonitorModeStatus.classList.remove('ok', 'warn', 'neutral', 'problem');
  busmonitorModeStatus.classList.add(state);

  const label = busmonitorModeStatus.querySelector('span:last-child');
  if (label) label.textContent = text;
}

function updateLoadedStatus(prefix = '') {
  if (!status || !body) return;

  const count = body.querySelectorAll('tr').length;
  status.textContent = `${prefix}${count} telegram${count === 1 ? '' : 's'} loaded`;
}

const originalLoadTelegrams = loadTelegrams;
loadTelegrams = async function loadTelegramsWithTotal(append = false) {
  await originalLoadTelegrams(append);

  if (status?.textContent?.startsWith('query failed')) return;
  updateLoadedStatus();
};

async function loadAllTelegrams() {
  if (!loadAllButton) return;

  loadAllButton.disabled = true;
  applyButton.disabled = true;
  loadOlderButton.disabled = true;
  status.textContent = 'loading all telegrams...';

  try {
    nextCursor = null;
    body.innerHTML = '';

    let append = false;
    let pageCount = 0;

    while (true) {
      const params = buildQuery(false);
      params.set('limit', '1000');

      if (nextCursor) {
        params.set('cursor_timestamp', nextCursor.timestamp_unix);
        params.set('cursor_telegram_id', nextCursor.telegram_id);
      }

      const response = await apiFetch(`/api/v1/busmonitor/telegrams?${params.toString()}`);
      if (!response.ok) {
        status.textContent = `query failed (${response.status})`;
        return;
      }

      const payload = await response.json();
      renderRows(payload.telegrams ?? [], append);
      nextCursor = payload.next_cursor;
      append = true;
      pageCount += 1;
      updateLoadedStatus();

      if (!nextCursor) break;

      if (pageCount >= 1000) {
        status.textContent = `${body.querySelectorAll('tr').length} telegrams loaded (safety limit reached)`;
        break;
      }
    }
  } catch (error) {
    console.warn('Failed to load all telegrams', error);
    status.textContent = 'query failed';
  } finally {
    loadAllButton.disabled = false;
    applyButton.disabled = false;
    loadOlderButton.disabled = false;
  }
}

loadAllButton?.addEventListener('click', loadAllTelegrams);

setBusmonitorModeStatus('Bus monitor in Live Mode', 'ok');
