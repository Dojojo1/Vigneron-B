(() => {
  'use strict';
  const selector = '#content button:not(:disabled):not(.icon-button):not(.text-link), .hero-actions button:not(:disabled), dialog .button:not(:disabled), #entry-screen .button:not(:disabled)';
  const canAnimate = button => button && !['absolute', 'fixed', 'sticky'].includes(getComputedStyle(button).position);
  const eligible = target => {
    const button = target.closest(selector);
    return canAnimate(button) ? button : null;
  };
  const attach = () => document.querySelectorAll(selector).forEach(button => {
    if (canAnimate(button)) button.classList.add('heritage-motion-button');
  });
  attach();
  const content = document.querySelector('#content');
  if (content) new MutationObserver(records => {
    if (records.some(record => [...record.addedNodes].some(node =>
      node.nodeType === Node.ELEMENT_NODE && (node.matches(selector) || node.querySelector(selector))))) attach();
  }).observe(content, { childList: true, subtree: true });

  document.addEventListener('pointerover', event => {
    const button = eligible(event.target);
    if (button) button.classList.add('heritage-motion-button');
  }, { passive: true });

  document.addEventListener('pointerdown', event => {
    const button = eligible(event.target);
    if (!button || event.pointerType === 'touch' && event.isPrimary === false) return;
    button.classList.add('heritage-motion-button');
    const bounds = button.getBoundingClientRect();
    const drop = document.createElement('span');
    drop.className = 'heritage-click-drop';
    drop.setAttribute('aria-hidden', 'true');
    drop.style.setProperty('--drop-x', `${event.clientX - bounds.left}px`);
    drop.style.setProperty('--drop-y', `${event.clientY - bounds.top}px`);
    button.append(drop);
    drop.addEventListener('animationend', () => drop.remove(), { once: true });
  });
})();
