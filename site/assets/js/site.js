// Construction Conversations — shared page behavior

// ---------------------------------------------------------------------------
// Analytics: Plausible event queue stub. Events queue harmlessly until the
// Plausible script (commented in each page <head>) is enabled. Tracked:
// platform link clicks, Start Here plays, newsletter submits, sponsor CTAs —
// anything carrying a data-event attribute.
window.plausible = window.plausible || function () {
  (window.plausible.q = window.plausible.q || []).push(arguments);
};

document.addEventListener('click', function (e) {
  var el = e.target.closest('a[data-event], button[data-event], summary[data-event]');
  if (!el) return;
  // "Transcript Open" counts the disclosure opening, not closing it.
  if (el.tagName === 'SUMMARY') {
    var details = el.parentElement;
    if (details && details.tagName === 'DETAILS' && details.open) return;
  }
  plausible(el.dataset.event);
});

document.addEventListener('submit', function (e) {
  if (e.target.matches('form[data-event]')) plausible(e.target.dataset.event);
});

// Audio play events (Start Here card + episode pages)
document.addEventListener('play', function (e) {
  var audio = e.target;
  if (audio.closest('.start-here')) plausible('Start Here Play');
  else if (audio.closest('.ep-page')) plausible('Episode Page Play');
}, true);

// ---------------------------------------------------------------------------
// Standalone audio elements (episode pages, Start Here card): promote
// data-src to src up front. preload="none" keeps this network-free.
document.querySelectorAll('.ep-page audio[data-src], .start-here audio[data-src]').forEach(function (a) {
  var src = a.dataset.src;
  if (src && src.indexOf('http') === 0) a.src = src;
});

// ---------------------------------------------------------------------------
// Toggle inline audio players on episode cards. Audio src is set on first
// open so 58 players don't touch the network on page load.
document.addEventListener('click', function (e) {
  var btn = e.target.closest('.play-btn');
  if (!btn) return;
  var card = btn.closest('.ep-card');
  var player = card.querySelector('.ep-player');
  var audio = player.querySelector('audio');
  if (!audio.src) audio.src = audio.dataset.src;
  var opening = !player.classList.contains('open');
  // pause any other playing episode
  document.querySelectorAll('.ep-player.open').forEach(function (p) {
    if (p !== player) {
      p.classList.remove('open');
      var a = p.querySelector('audio');
      a.pause();
      var b = p.closest('.ep-card').querySelector('.play-btn');
      if (b) b.textContent = '▶ Play';
    }
  });
  player.classList.toggle('open', opening);
  if (opening) {
    audio.play();
    btn.textContent = '✕ Close';
  } else {
    audio.pause();
    btn.textContent = '▶ Play';
  }
});

// ---------------------------------------------------------------------------
// Episode search (episodes page only); supports ?q= prefill from nav links
var search = document.getElementById('ep-search');
if (search) {
  var q = new URLSearchParams(window.location.search).get('q');
  if (q) search.value = q;
  var cards = Array.prototype.slice.call(document.querySelectorAll('#ep-list .ep-card'));
  var count = document.getElementById('ep-count');
  var ranNote = document.getElementById('ran-note');
  var update = function () {
    var term = search.value.trim().toLowerCase();
    if (ranNote) ranNote.hidden = term.indexOf('reviewed') === -1;
    var shown = 0;
    cards.forEach(function (c) {
      var hit = !term || c.textContent.toLowerCase().indexOf(term) !== -1;
      c.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    count.textContent = shown + ' of ' + cards.length + ' episodes';
  };
  search.addEventListener('input', update);
  update();
}

// ---------------------------------------------------------------------------
// Chapter and transcript timestamps. Chapter Seek / Transcript Seek are
// data-event values, fired by the click listener above.
function seekAudio(audio, seconds, andPlay) {
  if (!audio.src) audio.src = audio.dataset.src;
  var seek = function () {
    var dur = audio.duration;
    var t = seconds;
    if (dur && t > dur) t = dur;
    audio.currentTime = t;
    if (andPlay) audio.play();
    highlightChapter(audio);
  };
  if (audio.readyState >= 1) seek();
  else {
    audio.addEventListener('loadedmetadata', seek, { once: true });
    audio.load();
  }
}

function highlightChapter(audio) {
  var t = audio.currentTime || 0;
  var links = document.querySelectorAll('.chapters a.chapter');
  var current = null;
  for (var i = 0; i < links.length; i++) {
    var start = parseInt(links[i].getAttribute('data-t'), 10);
    if (!isNaN(start) && start <= t) current = links[i];
  }
  for (var j = 0; j < links.length; j++) {
    var on = links[j] === current;
    links[j].classList.toggle('is-current', on);
    if (links[j].parentElement) links[j].parentElement.classList.toggle('is-current', on);
    if (on) links[j].setAttribute('aria-current', 'true');
    else links[j].removeAttribute('aria-current');
  }
}

function prefersReducedMotion() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

// Last paragraph that has started, or the first if the cue is before it.
function paragraphForSecond(sec) {
  var paras = document.querySelectorAll('.transcript .tx-p');
  if (!paras.length) return null;
  var found = paras[0];
  for (var i = 0; i < paras.length; i++) {
    var start = parseInt(paras[i].getAttribute('data-start'), 10);
    if (isNaN(start) || sec < start) break;
    found = paras[i];
  }
  return found;
}

function revealTranscript(sec) {
  var details = document.querySelector('details.transcript');
  if (!details) return;
  details.open = true;
  var target = paragraphForSecond(sec);
  if (!target) return;
  document.querySelectorAll('.transcript .tx-p.is-target').forEach(function (p) {
    p.classList.remove('is-target');
  });
  target.classList.add('is-target');
  var behavior = prefersReducedMotion() ? 'auto' : 'smooth';
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      target.scrollIntoView({ behavior: behavior, block: 'center' });
    });
  });
}

document.addEventListener('click', function (e) {
  var a = e.target.closest('.ep-page a[data-t]');
  if (!a) return;
  var audio = document.querySelector('.ep-page audio');
  if (!audio) return;
  e.preventDefault();
  seekAudio(audio, parseInt(a.dataset.t, 10), true);
});

var pageAudio = document.querySelector('.ep-page audio');
if (pageAudio) {
  pageAudio.addEventListener('timeupdate', function () { highlightChapter(pageAudio); });
  pageAudio.addEventListener('seeked', function () { highlightChapter(pageAudio); });
}

document.addEventListener('click', function (e) {
  var btn = e.target.closest('button.tx-copy');
  if (!btn) return;
  var sec = btn.getAttribute('data-t');
  var url = window.location.href.split('#')[0] + '#t=' + sec;
  var label = btn.getAttribute('aria-label') || 'Copy link to this moment';
  var mark = function () {
    btn.textContent = 'Copied';
    btn.setAttribute('aria-label', 'Copied');
    window.setTimeout(function () {
      btn.textContent = 'Copy link to this moment';
      btn.setAttribute('aria-label', label);
    }, 1600);
  };
  var fallback = function () {
    var ta = document.createElement('textarea');
    ta.value = url;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); mark(); } catch (err) {}
    document.body.removeChild(ta);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(mark).catch(fallback);
  } else {
    fallback();
  }
});

// Deep link: episodes/ep-045.html#t=754 seeks, opens the transcript, scrolls to the paragraph.
function applyTimeHash() {
  var m = /[#&]t=(\d+)/.exec(window.location.hash);
  if (!m) return;
  var sec = parseInt(m[1], 10);
  var audio = document.querySelector('.ep-page audio');
  if (audio) seekAudio(audio, sec, false);
  revealTranscript(sec);
}
applyTimeHash();
window.addEventListener('hashchange', applyTimeHash);

// ---------------------------------------------------------------------------
// Type / category filters (articles, tools) + tool search
document.querySelectorAll('.filters').forEach(function (bar) {
  var list = document.querySelector(bar.dataset.target);
  if (!list) return;
  bar.addEventListener('click', function (e) {
    var btn = e.target.closest('.filter');
    if (!btn) return;
    bar.querySelectorAll('.filter').forEach(function (b) { b.classList.toggle('active', b === btn); });
    var type = btn.dataset.type;
    list.querySelectorAll('[data-type],[data-cat]').forEach(function (c) {
      var v = c.dataset.type !== undefined ? c.dataset.type : c.dataset.cat;
      c.style.display = (!type || v === type || v.split('|').indexOf(type) !== -1) ? '' : 'none';
    });
  });
});
var toolSearch = document.getElementById('tool-search');
if (toolSearch) {
  toolSearch.addEventListener('input', function () {
    var term = toolSearch.value.trim().toLowerCase();
    document.querySelectorAll('#tool-page .tool-card, #tool-page .radar-row').forEach(function (c) {
      c.style.display = (!term || c.textContent.toLowerCase().indexOf(term) !== -1) ? '' : 'none';
    });
  });
}

// Field deck role filter
var roleBar = document.getElementById('role-filter');
if (roleBar) {
  roleBar.addEventListener('click', function (e) {
    var btn = e.target.closest('.filter');
    if (!btn) return;
    roleBar.querySelectorAll('.filter').forEach(function (b) { b.classList.toggle('active', b === btn); });
    var role = btn.dataset.role;
    document.querySelectorAll('.lesson[data-roles]').forEach(function (c) {
      c.style.display = (!role || c.dataset.roles.split(' ').indexOf(role) !== -1) ? '' : 'none';
    });
    document.querySelectorAll('.sit-block').forEach(function (b) {
      var any = Array.prototype.some.call(b.querySelectorAll('.lesson'), function (c) { return c.style.display !== 'none'; });
      b.style.display = any ? '' : 'none';
    });
    if (window.plausible) plausible('Deck Filter: ' + (role || 'All'));
  });
}
