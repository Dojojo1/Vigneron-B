/* GSAP Core : une entrée légère et quelques gouttes sur le verre du tableau de bord. */
(() => {
  'use strict';
  if (!window.gsap) return;
  // Les gouttes n'ont pas besoin de suivre les écrans à 120/144 Hz.
  window.gsap.ticker.fps(60);
  const content = document.querySelector('#content');
  if (!content) return;

  const entry = document.querySelector('#entry-screen');
  const entryPanel = entry?.querySelector('.entry-panel');
  let entryVisible = false;
  const entryLoops = [];
  const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
  if (entryPanel && !motionPreference.matches) {
    [13, 87, 18, 82].forEach((left, index) => {
      const drop = document.createElement('span');
      drop.className = 'entry-moving-drop';
      drop.setAttribute('aria-hidden', 'true');
      drop.style.left = `${left}%`;
      drop.style.top = `${18 + index % 2 * 24}%`;
      entryPanel.append(drop);
      const tween = window.gsap.fromTo(drop,
        {y: -8, opacity: 0},
        {y: 120 + index * 20, opacity: .7, duration: 4 + index * .55,
          ease: 'none', repeat: -1, repeatDelay: 1.8, delay: index * .8,
          paused: true});
      entryLoops.push(tween);
    });
  }
  const syncEntry = () => {
    const visible = !!entry && !entry.hidden && document.body.classList.contains('on-entry');
    const moving = visible && !document.hidden && !motionPreference.matches
      && !document.documentElement.classList.contains('heritage-light-mode');
    entryLoops.forEach(tween => moving ? tween.resume() : tween.pause());
    if (!visible) { entryVisible = false; return; }
    if (entryVisible) return;
    entryVisible = true;
    const targets = entry.querySelectorAll('.entry-brand, .entry-panel-shell, .entry-signature');
    if (motionPreference.matches) {
      window.gsap.set(targets, {clearProps: 'transform,opacity'});
      return;
    }
    window.gsap.fromTo(targets,
      {y: 12, opacity: 0},
      {y: 0, opacity: 1, duration: .72,
        stagger: .12, ease: 'power2.out',
        clearProps: 'transform,opacity'});
  };
  document.addEventListener('heritage:domain-visibility', syncEntry);
  document.addEventListener('visibilitychange', syncEntry);
  document.addEventListener('heritage:light-mode', syncEntry);
  motionPreference.addEventListener('change', syncEntry);
  syncEntry();

  const media = window.gsap.matchMedia();
  media.add('(prefers-reduced-motion: no-preference)', () => {
    const seen = new WeakSet();
    const loops = new Set();
    const animatedDrops = new Set();
    const cardsInView = new WeakSet();
    const cardObserver = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) cardsInView.add(entry.target);
      else cardsInView.delete(entry.target);
      for (const tween of loops) {
        if (tween.data?.closest('.night-metric, .batch-card') === entry.target) {
          if (!document.hidden && !document.documentElement.classList.contains('heritage-light-mode') && entry.isIntersecting) tween.resume();
          else tween.pause();
        }
      }
    }), {rootMargin: '80px'});
    const visible = () => loops.forEach(tween => {
      const card = tween.data?.closest('.night-metric, .batch-card');
      if (!document.hidden && !document.documentElement.classList.contains('heritage-light-mode') && card && cardsInView.has(card)) tween.resume();
      else tween.pause();
    });

    const update = () => {
      const removedCards = new Set();
      for (const tween of loops) {
        if (!tween.data?.isConnected) {
          const card = tween.data?.closest('.night-metric, .batch-card');
          if (card) removedCards.add(card);
          animatedDrops.delete(tween.data);
          tween.kill(); loops.delete(tween);
        }
      }
      removedCards.forEach(card => cardObserver.unobserve(card));
      if (!document.body.classList.contains('dashboard-active')) return;
      const cards = [...content.querySelectorAll('.night-metric, .batch-card')].filter(card => !seen.has(card));
      if (!cards.length) return;
      cards.forEach(card => {
        seen.add(card);
        const surface = card.classList.contains('batch-card') ? card.querySelector('.cut-inner') : card;
        if (!surface) return;
        cardObserver.observe(card);
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
          timeline.pause();
          loops.add(timeline);
        });
      });
      window.gsap.fromTo(cards,
        {y: 8, opacity: .25},
        {y: 0, opacity: 1, duration: .55, stagger: .07, ease: 'power3.out', clearProps: 'transform,opacity'});
    };

    const relevantCard = node => node.nodeType === Node.ELEMENT_NODE &&
      (node.matches('.night-metric, .batch-card') || node.querySelector('.night-metric, .batch-card'));
    const observer = new MutationObserver(records => {
      if (records.some(record => [...record.addedNodes, ...record.removedNodes].some(relevantCard))) update();
    });
    observer.observe(content, {childList: true, subtree: true});
    document.addEventListener('visibilitychange', visible);
    document.addEventListener('heritage:light-mode', visible);
    update();
    return () => {
      observer.disconnect();
      cardObserver.disconnect();
      document.removeEventListener('visibilitychange', visible);
      document.removeEventListener('heritage:light-mode', visible);
      loops.forEach(tween => tween.kill());
      animatedDrops.forEach(drop => drop.remove());
    };
  });
})();
