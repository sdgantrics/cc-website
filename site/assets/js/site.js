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
  var el = e.target.closest('a[data-event], button[data-event]');
  if (el) plausible(el.dataset.event);
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
  var update = function () {
    var term = search.value.trim().toLowerCase();
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
