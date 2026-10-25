'use strict';

// Vidéo fournie par l’utilisateur, avec formats alternatifs et reprise manuelle.
(() => {
  const video = document.querySelector('#estate-smoke');
  const activate = document.querySelector('#activate-smoke');
  if (!video || !activate) return;
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const preferenceKey = 'da-vigneron-smoke-enabled';
  // Le décor démarre par défaut, y compris sur une première visite.
  // Une préférence explicite de désactivation reste prioritaire.
  let initialized = false, userRequested = true, starting = false;
  try { userRequested = localStorage.getItem(preferenceKey) !== 'false'; } catch {}
  video.classList.toggle('motion-requested', userRequested);
  video.muted = true;
  video.defaultMuted = true;
  video.playbackRate = .85;

  function onDomain() {
    return !document.body.classList.contains('on-entry');
  }
  function shouldPlay(entering = false) {
    return userRequested && !document.hidden && (onDomain() || entering);
  }
  function showActivate(label = 'Activer la fumée') {
    activate.textContent = label;
    activate.hidden = !onDomain() || document.hidden;
  }
  function loadSources() {
    if (initialized) return;
    initialized = true;
    video.preload = 'auto';
    for (const [src, type] of [[video.dataset.webm, 'video/webm'], [video.dataset.mp4, 'video/mp4']]) {
      if (!src) continue;
      const source = document.createElement('source');
      source.src = src;
      source.type = type;
      video.append(source);
    }
    video.load();
  }
  function syncPlayback(entering = false) {
    // Les événements du navigateur ne constituent pas une entrée explicite.
    entering = entering === true;
    if (!shouldPlay(entering)) {
      video.autoplay = false;
      video.pause();
      video.dataset.state = motion.matches ? 'reduced-motion' : 'paused';
      if (onDomain() && !document.hidden && motion.matches) showActivate();
      else activate.hidden = true;
      return;
    }
    if (starting || !video.paused) return;
    video.autoplay = true;
    loadSources();
    starting = true;
    video.dataset.state = 'loading';
    video.play().then(() => {
      if (!shouldPlay()) video.pause();
    }).catch(() => {
      video.dataset.state = 'blocked';
      showActivate();
    }).finally(() => { starting = false; });
  }
  video.addEventListener('playing', () => {
    video.classList.add('is-visible');
    video.dataset.state = 'playing';
    activate.hidden = true;
  });
  video.addEventListener('loadeddata', () => {
    // Affiche déjà la première image lorsque le navigateur attend un clic.
    video.classList.add('is-visible');
  });
  video.addEventListener('error', () => {
    video.dataset.state = 'error';
    video.classList.remove('is-visible');
    showActivate('Réessayer la fumée');
  });
  activate.addEventListener('click', () => {
    userRequested = true;
    try { localStorage.setItem(preferenceKey, 'true'); } catch {}
    video.classList.add('motion-requested');
    if (video.error) {
      initialized = false;
      video.replaceChildren();
    }
    syncPlayback();
  });
  document.addEventListener('visibilitychange', syncPlayback);
  window.addEventListener('hashchange', syncPlayback);
  // Le chargement de session ouvre aussi le domaine sans changer le hash.
  window.addEventListener('heritage:domain-visibility', syncPlayback);
  motion.addEventListener('change', syncPlayback);
  document.querySelector('#enter-demo')?.addEventListener('click', () => {
    // Lecture demandée pendant le clic réel, avant l’événement hashchange.
    syncPlayback(true);
  });
  document.addEventListener('pointerdown', event => {
    if (event.target.closest('#activate-smoke')) return;
    if (video.paused && !video.error) syncPlayback();
  }, { passive: true });
  syncPlayback();
})();
