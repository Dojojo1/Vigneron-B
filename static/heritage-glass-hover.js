(() => {
  'use strict';
  if (!matchMedia('(hover: hover) and (pointer: fine)').matches) return;
  const content = document.querySelector('#content');
  if (!content) return;

  const filter = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  filter.setAttribute('aria-hidden', 'true');
  filter.setAttribute('class', 'heritage-water-filter');
  filter.innerHTML = '<filter id="heritage-water-refraction" x="-20%" y="-20%" width="140%" height="140%"><feTurbulence type="fractalNoise" baseFrequency="0.025 0.038" numOctaves="2" seed="7" result="ripples"/><feDisplacementMap in="SourceGraphic" in2="ripples" scale="12" xChannelSelector="R" yChannelSelector="G"/></filter>';
  document.body.append(filter);

  const seen = new WeakSet();
  const attach = () => {
    content.querySelectorAll('.night-metrics .night-metric, .batch-card, .sale-record').forEach(card => {
      if (seen.has(card)) return;
      seen.add(card);
      const surface = card.classList.contains('sale-record') ? card.querySelector('summary.cut-inner')
        : card.classList.contains('batch-card') ? card.querySelector('.cut-inner') : card;
      if (!surface) return;
      const layer = document.createElement('span');
      layer.className = 'heritage-water-layer';
      layer.setAttribute('aria-hidden', 'true');
      surface.append(layer);

      card.addEventListener('pointerenter', event => {
        if (event.pointerType === 'touch') return;
        card.classList.add('water-hover');
      });
      card.addEventListener('pointerleave', () => card.classList.remove('water-hover'));
    });
  };
  new MutationObserver(attach).observe(content, {childList: true, subtree: true});
  attach();
})();
