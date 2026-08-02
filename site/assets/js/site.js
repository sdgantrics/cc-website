// Construction Conversations — shared page behavior

// Toggle inline audio players. Audio src is set on first open so 58
// players don't preload on page load.
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
      if (b) b.textContent = '▶ Play episode';
    }
  });
  player.classList.toggle('open', opening);
  if (opening) {
    audio.play();
    btn.textContent = '✕ Close player';
  } else {
    audio.pause();
    btn.textContent = '▶ Play episode';
  }
});

// Episode search (episodes page only); supports ?q= prefill from nav links
var search = document.getElementById('ep-search');
if (search) {
  var q = new URLSearchParams(window.location.search).get('q');
  if (q) search.value = q;
  var cards = Array.prototype.slice.call(document.querySelectorAll('#ep-list .ep-card'));
  var count = document.getElementById('ep-count');
  var update = function () {
    var q = search.value.trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (c) {
      var hit = !q || c.textContent.toLowerCase().indexOf(q) !== -1;
      c.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    count.textContent = shown + ' of ' + cards.length + ' episodes';
  };
  search.addEventListener('input', update);
  update();
}
