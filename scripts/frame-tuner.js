/* Outil de mesure visuelle : Ctrl+Maj+L. Aucun réglage n'est enregistré. */
(() => {
  const selector = '.night-metric, .batch-card, .night-metrics, .night-dossier, .sale-record, .machine-card, .raffle, .stats-top article, .stats-grid > .panel, .panel, .register-panel, .council-panel';
  const styles = document.createElement('style');
  styles.textContent = `
    #frame-tuner { position:fixed;top:16px;right:16px;z-index:2147483647;width:min(310px,calc(100vw - 32px));padding:16px;border:1px solid #d5ad70;border-radius:14px;background:#0b1419f2;color:#f1dfc0;box-shadow:0 12px 42px #0009;font:13px/1.4 system-ui,sans-serif;backdrop-filter:blur(16px) }
    #frame-tuner * { box-sizing:border-box }
    #frame-tuner strong { display:block;margin-bottom:5px;font:600 17px Georgia,serif }
    #frame-tuner p { margin:5px 0 12px;color:#c9b798 }
    #frame-tuner .ft-row { display:flex;gap:8px;align-items:end;margin:10px 0 }
    #frame-tuner label { flex:1;color:#d2c19f }
    #frame-tuner input { display:block;width:100%;margin-top:3px;padding:7px 8px;border:1px solid #ac895a;border-radius:6px;background:#17232a;color:#fff;font:inherit }
    #frame-tuner button { min-height:35px;padding:6px 9px;border:1px solid #a88552;border-radius:6px;background:#263039;color:#f6deb6;cursor:pointer;font:inherit }
    #frame-tuner button:hover,#frame-tuner button:focus-visible { background:#4b3928;outline:2px solid #e1bc81;outline-offset:1px }
    #frame-tuner .ft-actions { display:flex;gap:7px;flex-wrap:wrap }
    #frame-tuner .ft-hint { font-size:11px }
    #frame-tuner-outline { position:fixed;z-index:2147483645;border:2px solid #f7c775;box-shadow:0 0 0 2px #101820,0 0 18px #efbd6b66;pointer-events:none;display:none }
    #frame-tuner-handle { position:fixed;z-index:2147483646;width:26px;height:26px;border:2px solid #f9deac;border-radius:7px;background:#a67735;box-shadow:0 2px 10px #0009;cursor:nwse-resize;display:none;touch-action:none }
    #frame-tuner-handle::after { content:'↘';display:grid;place-items:center;color:#111a1f;font:700 18px system-ui }
  `;
  let panel, outline, handle, selected, observer, active = false;
  const changes = new Map();

  function labelFor(el) {
    const type = el.classList.contains('night-metric') ? 'Bulle indicateur'
      : el.classList.contains('batch-card') ? 'Cadre du lot'
      : el.classList.contains('night-metrics') ? 'Groupe des indicateurs'
      : el.classList.contains('night-dossier') ? 'Cadre dossier'
      : el.classList.contains('machine-card') ? 'Cadre machine'
      : el.classList.contains('raffle') ? 'Cadre tombola' : 'Panneau';
    const siblings = [...document.querySelectorAll(selector)].filter(node => node.className === el.className);
    return `${type}${siblings.length > 1 ? ` ${siblings.indexOf(el) + 1}` : ''}`;
  }

  function placeOutline() {
    if (!selected || !selected.isConnected || !active) { if (outline) outline.style.display = handle.style.display = 'none'; return; }
    const r = selected.getBoundingClientRect();
    Object.assign(outline.style, {display:'block',left:`${r.left}px`,top:`${r.top}px`,width:`${r.width}px`,height:`${r.height}px`});
    Object.assign(handle.style, {display:'block',left:`${r.right - 13}px`,top:`${r.bottom - 13}px`});
    panel.querySelector('[data-ft-name]').textContent = labelFor(selected);
    panel.querySelector('[data-ft-width]').value = Math.round(r.width);
    panel.querySelector('[data-ft-height]').value = Math.round(r.height);
  }

  function select(el) {
    observer?.disconnect();
    selected = el;
    if (el) observer.observe(el);
    placeOutline();
  }

  function setSize(width, height) {
    if (!selected) return;
    const w = Math.max(80, Math.round(Number(width) || selected.getBoundingClientRect().width));
    const h = Math.max(60, Math.round(Number(height) || selected.getBoundingClientRect().height));
    if (!changes.has(selected)) changes.set(selected, {width:selected.style.width,height:selected.style.height,maxWidth:selected.style.maxWidth,minHeight:selected.style.minHeight});
    Object.assign(selected.style, {width:`${w}px`,height:`${h}px`,maxWidth:'none',minHeight:'0px'});
    placeOutline();
  }

  async function copy() {
    if (!changes.size) { panel.querySelector('[data-ft-status]').textContent = 'Redimensionne au moins un cadre.'; return; }
    const lines = [`Écran : ${innerWidth} × ${innerHeight} px`];
    for (const el of changes.keys()) {
      if (!el.isConnected) continue;
      const r = el.getBoundingClientRect();
      lines.push(`${labelFor(el)} : ${Math.round(r.width)} × ${Math.round(r.height)} px`);
    }
    const text = lines.join('\n');
    try { await navigator.clipboard.writeText(text); panel.querySelector('[data-ft-status]').textContent = 'Mesures copiées. Colle-les dans la conversation.'; }
    catch { window.prompt('Copie ces mesures :', text); }
  }

  function reset() {
    for (const [el, old] of changes) if (el.isConnected) Object.assign(el.style, old);
    changes.clear();
    select(null);
    panel.querySelector('[data-ft-status]').textContent = 'Dimensions d’origine rétablies.';
  }

  function onClick(e) {
    if (panel.contains(e.target) || handle.contains(e.target)) return;
    const target = e.target.closest(selector);
    if (!target) return;
    e.preventDefault(); e.stopPropagation();
    select(target);
  }

  function open() {
    if (active || document.body.classList.contains('on-entry') || document.querySelector('main')?.hidden) return;
    active = true;
    document.head.append(styles);
    panel = document.createElement('aside');
    panel.id = 'frame-tuner';
    panel.setAttribute('aria-label', 'Réglage des cadres');
    panel.innerHTML = `<strong>Dimensions des cadres</strong><p data-ft-name>Clique sur un cadre ou une bulle.</p><div class="ft-row"><label>Largeur (px)<input data-ft-width type="number" min="80" step="1"></label><label>Hauteur (px)<input data-ft-height type="number" min="60" step="1"></label><button type="button" data-ft-apply>Appliquer</button></div><div class="ft-actions"><button type="button" data-ft-copy>Copier les mesures</button><button type="button" data-ft-reset>Réinitialiser</button><button type="button" data-ft-close>Fermer</button></div><p class="ft-hint" data-ft-status>Tire la poignée dorée en bas à droite du cadre sélectionné. Les changements sont temporaires.</p>`;
    outline = document.createElement('div'); outline.id = 'frame-tuner-outline';
    handle = document.createElement('div'); handle.id = 'frame-tuner-handle';
    document.body.append(panel, outline, handle);
    observer = new ResizeObserver(placeOutline);
    panel.querySelector('[data-ft-apply]').onclick = () => setSize(panel.querySelector('[data-ft-width]').value, panel.querySelector('[data-ft-height]').value);
    panel.querySelector('[data-ft-copy]').onclick = copy;
    panel.querySelector('[data-ft-reset]').onclick = reset;
    panel.querySelector('[data-ft-close]').onclick = close;
    panel.querySelectorAll('input').forEach(input => input.addEventListener('keydown', e => { if (e.key === 'Enter') setSize(panel.querySelector('[data-ft-width]').value, panel.querySelector('[data-ft-height]').value); }));
    handle.addEventListener('pointerdown', e => {
      if (!selected) return;
      e.preventDefault();
      const r = selected.getBoundingClientRect(), startX = e.clientX, startY = e.clientY;
      handle.setPointerCapture(e.pointerId);
      const move = event => setSize(r.width + event.clientX - startX, r.height + event.clientY - startY);
      const stop = () => {handle.removeEventListener('pointermove', move);handle.removeEventListener('pointerup', stop);handle.removeEventListener('pointercancel', stop);};
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', stop);
      handle.addEventListener('pointercancel', stop);
    });
    document.addEventListener('click', onClick, true);
    window.addEventListener('scroll', placeOutline, {passive:true});
    window.addEventListener('resize', placeOutline);
  }

  function close() {
    if (!active) return;
    reset(); observer.disconnect(); active = false;
    document.removeEventListener('click', onClick, true);
    window.removeEventListener('scroll', placeOutline);
    window.removeEventListener('resize', placeOutline);
    panel.remove(); outline.remove(); handle.remove(); styles.remove();
    panel = outline = handle = selected = null;
  }

  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.shiftKey && e.code === 'KeyL') { e.preventDefault(); active ? close() : open(); }
  });
  if (new URLSearchParams(location.search).has('cadres')) {
    const waitForDashboard = () => {
      if (document.body.classList.contains('on-entry') || document.querySelector('main')?.hidden) return;
      watcher.disconnect(); open();
    };
    const watcher = new MutationObserver(waitForDashboard);
    const start = () => { watcher.observe(document.body, {subtree:true,attributes:true,attributeFilter:['class','hidden']}); waitForDashboard(); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
    else start();
  }
})();
