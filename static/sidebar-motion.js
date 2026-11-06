(() => {
  'use strict';
  const nav = document.querySelector('#navigation');
  if (!nav || !matchMedia('(hover: hover) and (pointer: fine)').matches) return;

  const itemFor = target => target.closest('a, .management-navigation > summary');
  nav.addEventListener('pointermove', event => {
    const item = itemFor(event.target);
    if (!item || !nav.contains(item)) return;
    const rect = item.getBoundingClientRect();
    item.style.setProperty('--nav-light-x', `${event.clientX - rect.left}px`);
    item.style.setProperty('--nav-light-y', `${event.clientY - rect.top}px`);
  }, { passive: true });

  nav.addEventListener('pointerdown', event => {
    const item = itemFor(event.target);
    if (!item || !nav.contains(item)) return;
    const rect = item.getBoundingClientRect();
    item.style.setProperty('--nav-light-x', `${event.clientX - rect.left}px`);
    item.style.setProperty('--nav-light-y', `${event.clientY - rect.top}px`);
    item.classList.remove('nav-ripple');
    void item.offsetWidth;
    item.classList.add('nav-ripple');
  });
  nav.addEventListener('animationend', event => {
    if (event.animationName === 'heritage-nav-ripple') event.target.classList.remove('nav-ripple');
  });
})();
