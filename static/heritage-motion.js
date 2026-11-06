/* GSAP Core : une entrée légère et quelques gouttes sur le verre du tableau de bord. */
(() => {
  'use strict';
  if (!window.gsap) return;
  const content = document.querySelector('#content');
  if (!content) return;

  const media = window.gsap.matchMedia();
  document.documentElement.classList.add('heritage-full-motion');
  media.add('all', () => {
    const seen = new WeakSet();
    const loops = new Set();
    const animatedDrops = new Set();
    const visible = () => loops.forEach(tween => document.hidden ? tween.pause() : tween.resume());

    const update = () => {
      for (const tween of loops) {
        if (!tween.data?.isConnected) {
          tween.kill(); loops.delete(tween);
        }
      }
      if (!document.body.classList.contains('dashboard-active')) return;
      const cards = [...content.querySelectorAll('.night-metric, .batch-card')].filter(card => !seen.has(card));
      if (!cards.length) return;
      cards.forEach(card => {
        seen.add(card);
        const surface = card.classList.contains('batch-card') ? card.querySelector('.cut-inner') : card;
        if (!surface) return;
        const isLot = card.classList.contains('batch-card');
        const positions = isLot ? [4, 95, 8, 97, 91, 3] : [7, 93, 14, 88];
        const drops = positions.map((left, i) => {
          const drop = document.createElement('span');
          drop.className = 'glass-drop';
          drop.setAttribute('aria-hidden', 'true');
          drop.style.left = `${left}%`;
          drop.style.top = `${isLot ? 7 + i * 4 : 9 + i * 7}%`;
          drop.style.width = `${5 + (i * 3) % 5}px`;
          drop.style.height = `${8 + (i * 4) % 7}px`;
          surface.append(drop);
          animatedDrops.add(drop);
          return drop;
        });
        drops.forEach((drop, i) => {
          const travel = () => surface.clientHeight * (isLot ? .42 + i % 3 * .1 : .4 + i % 2 * .13);
          const timeline = window.gsap.timeline({
            repeat: -1, repeatDelay: isLot ? 1.7 : 2.3,
            delay: i * (isLot ? .55 : .8) + .4,
            repeatRefresh: true, data: drop
          });
          timeline.fromTo(drop,
            {y: -8, opacity: 0, scale: .7},
            {y: 0, opacity: .8, scale: 1, duration: .2, ease: 'power1.out'}
          ).to(drop, {
            y: 3, duration: .55 + i * .08, ease: 'power1.out'
          }).to(drop, {
            y: travel, x: i % 2 ? 2 : -2, opacity: .72,
            duration: isLot ? 3.2 + i * .16 : 2.5 + i * .17,
            ease: 'power2.in'
          }).to(drop, {
            y: () => travel() + 14, opacity: 0, scale: .8,
            duration: .28, ease: 'power2.in'
          });
          if (document.hidden) timeline.pause();
          loops.add(timeline);
        });
      });
      window.gsap.fromTo(cards,
        {y: 8, opacity: .25},
        {y: 0, opacity: 1, duration: .55, stagger: .07, ease: 'power3.out', clearProps: 'transform,opacity'});
    };

    const observer = new MutationObserver(update);
    observer.observe(content, {childList: true, subtree: true});
    document.addEventListener('visibilitychange', visible);
    update();
    return () => {
      observer.disconnect();
      document.removeEventListener('visibilitychange', visible);
      loops.forEach(tween => tween.kill());
      animatedDrops.forEach(drop => drop.remove());
    };
  });
})();
