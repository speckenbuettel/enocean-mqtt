/* Render live/table tooltips outside the scrolling table's clipping boundary. */
(() => {
  let anchor = null;
  let panel = null;
  let closeTimer = null;

  function hide() {
    clearTimeout(closeTimer);
    if (anchor) anchor.removeAttribute('aria-describedby');
    if (panel) panel.remove();
    anchor = null;
    panel = null;
  }

  function show(target) {
    clearTimeout(closeTimer);
    if (target === anchor) return;
    hide();
    const source = target.querySelector('.tooltip-panel');
    if (!source) return;
    anchor = target;
    panel = source.cloneNode(true);
    panel.classList.add('tooltip-floating');
    panel.id = 'busmonitor-floating-tooltip';
    panel.style.visibility = 'hidden';
    document.body.append(panel);
    anchor.setAttribute('aria-describedby', panel.id);

    // Prefer word boundaries in protocol labels, keeping the actual text intact.
    panel.querySelectorAll('.tooltip-key, .tooltip-value').forEach((element) => {
      const parts = element.textContent.split('_');
      element.replaceChildren();
      parts.forEach((part, index) => {
        if (index) element.append('_', document.createElement('wbr'));
        element.append(part);
      });
    });

    const margin = 12;
    const gap = 8;
    const rect = anchor.getBoundingClientRect();
    const bounds = panel.getBoundingClientRect();
    const width = document.documentElement.clientWidth;
    const height = document.documentElement.clientHeight;
    const below = height - rect.bottom - margin - gap;
    const above = rect.top - margin - gap;
    const top = bounds.height <= below || below >= above
      ? rect.bottom + gap : rect.top - bounds.height - gap;
    panel.style.left = `${Math.max(margin, Math.min(rect.left, width - bounds.width - margin))}px`;
    panel.style.top = `${Math.max(margin, Math.min(top, height - bounds.height - margin))}px`;
    panel.style.visibility = 'visible';
    panel.addEventListener('pointerenter', () => clearTimeout(closeTimer));
    panel.addEventListener('pointerleave', () => { closeTimer = setTimeout(hide, 150); });
  }

  document.addEventListener('pointerover', (event) => {
    const target = event.target.closest?.('#telegramBody .tooltip');
    if (target) show(target);
  });
  document.addEventListener('pointerout', (event) => {
    if (anchor && anchor.contains(event.target) && !anchor.contains(event.relatedTarget)) {
      closeTimer = setTimeout(hide, 150);
    }
  });
  document.addEventListener('focusin', (event) => {
    const target = event.target.closest?.('#telegramBody .tooltip');
    if (target) show(target);
  });
  document.addEventListener('focusout', (event) => {
    if (anchor && anchor.contains(event.target)) hide();
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') hide(); });
  document.addEventListener('scroll', (event) => {
    if (!panel || !panel.contains(event.target)) hide();
  }, true);
  window.addEventListener('resize', hide);
  new MutationObserver(() => { if (anchor && !anchor.isConnected) hide(); })
    .observe(document.getElementById('telegramBody'), { childList: true });
})();
