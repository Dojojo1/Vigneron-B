/* GSAP Core: une entrée courte pour les indicateurs du tableau de bord.
   Le cadran du cycle conserve intégralement sa propre animation. */
(() => {
  'use strict';
  if (!window.gsap) return;

  const seen = new WeakSet();
  const motion = window.gsap.matchMedia();
  motion.add('(prefers-reduced-motion: no-preference)', () => {
    const content = document.querySelector('#content');
    if (!content) return;

    const reveal = () => {
      const cards = [...content.querySelectorAll('.night-metric')].filter(card => !seen.has(card));
      if (!cards.length) return;
      cards.forEach(card => seen.add(card));
      window.gsap.fromTo(cards,
        { y: 10, opacity: 0 },
        { y: 0, opacity: 1, duration: .56, stagger: .075, ease: 'power3.out',
          clearProps: 'transform,opacity' });
    };

    const observer = new MutationObserver(reveal);
    observer.observe(content, { childList: true, subtree: true });
    reveal();
    return () => observer.disconnect();
  });
})();
