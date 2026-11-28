// Contech Pitch to Jobsite Translator.
// Static: the tagline is hashed in the browser. Nothing is sent anywhere.
// site.js fires plausible(name) for clicks on [data-event] and does not take
// props, so Share is three event names: Download, Copy, LinkedIn.
// Translator Paste is not a click, so it is queued the same way, once.

(function () {
  var dataEl = document.getElementById('translator-data');
  var ask = document.getElementById('t-ask');
  var resultEl = document.getElementById('t-result');
  var input = document.getElementById('t-input');
  var go = document.getElementById('t-go');
  if (!dataEl || !ask || !resultEl || !input || !go) return;

  var data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (err) {
    return;
  }
  if (!data || !data.templates || !data.templates.length) return;

  var flag = document.getElementById('t-flag');
  var cardFlag = document.getElementById('t-card-flag');
  if (data.placeholder) {
    if (flag) flag.hidden = false;
    if (cardFlag) cardFlag.hidden = false;
  }

  var sub = document.getElementById('t-subscribe');
  var subUrl = sub ? sub.getAttribute('href') : '';
  var urlEl = sub ? sub.querySelector('.t-url') : null;
  if (urlEl && subUrl) urlEl.textContent = displayUrl(subUrl);

  function displayUrl(url) {
    var out = String(url || '').replace(/:\/\//, '\u0000').replace(/-/g, '\u2011');
    out = out.replace(/([/?&])/g, '\u200b$1');
    return out.replace('\u0000', '://');
  }

  var current = null;
  var pasteFired = false;

  function cleanPitch(s) {
    return String(s || '').replace(/\s+/g, ' ').trim().slice(0, 500);
  }

  function hashPitch(s) {
    var h = 0x811c9dc5;
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  }

  function phraseFrom(s) {
    var words = s.split(' ').filter(Boolean).slice(0, 6);
    var phrase = words.join(' ').replace(/^["'“”]+|["'“”.,!?;:]+$/g, '');
    if (phrase.length > 72) phrase = phrase.slice(0, 69).replace(/\s+\S*$/, '');
    return phrase || 'the pitch';
  }

  function norm(s) {
    return String(s || '')
      .toLowerCase()
      .replace(/-|–|—|\//g, ' ')
      .replace(/[^a-z0-9\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function countHits(text, list) {
    var padded = ' ' + norm(text) + ' ';
    var seen = {};
    var phrases = [];
    (list || []).forEach(function (b) {
      var n = norm(b);
      if (!n || seen[n]) return;
      seen[n] = true;
      phrases.push(n);
    });
    phrases.sort(function (a, b) { return b.length - a.length; });
    var hits = 0;
    phrases.forEach(function (p) {
      var needle = ' ' + p + ' ';
      var from = 0;
      while (from < padded.length) {
        var at = padded.indexOf(needle, from);
        if (at < 0) break;
        hits++;
        padded = padded.slice(0, at) + new Array(needle.length + 1).join(' ') + padded.slice(at + needle.length);
        from = at + needle.length;
      }
    });
    return hits;
  }

  function translate(pitch) {
    var phrase = phraseFrom(pitch);
    var idx = hashPitch(pitch) % data.templates.length;
    var line = String(data.templates[idx]).split('{phrase}').join(phrase);
    var hits = countHits(pitch, data.buzzwords);
    var score = Math.max(0, Math.min(100, hits * 16));
    return { pitch: pitch, phrase: phrase, line: line, score: score, hits: hits };
  }

  function pageUrl(pitch) {
    var u = new URL(window.location.href);
    u.searchParams.set('pitch', pitch);
    u.hash = '';
    return u.toString();
  }

  function syncGo() {
    go.disabled = !cleanPitch(input.value);
  }

  function showAsk() {
    ask.hidden = false;
    resultEl.hidden = true;
    var u = new URL(window.location.href);
    u.searchParams.delete('pitch');
    u.hash = '';
    history.replaceState(null, '', u);
    input.focus();
  }

  function showResult(raw, fromUser) {
    var pitch = cleanPitch(raw);
    if (!pitch) return;
    current = translate(pitch);
    document.getElementById('t-pitch').textContent = '\u201c' + current.pitch + '\u201d';
    document.getElementById('t-line').textContent = current.line;
    document.getElementById('t-score-n').textContent = String(current.score);
    document.getElementById('t-fill').style.width = current.score + '%';
    var meter = document.getElementById('t-meter');
    if (meter) meter.setAttribute('aria-valuenow', String(current.score));
    var linked = document.getElementById('t-linkedin');
    if (linked) {
      linked.href = 'https://www.linkedin.com/sharing/share-offsite/?url=' + encodeURIComponent(pageUrl(pitch));
    }
    history.replaceState(null, '', pageUrl(pitch));
    ask.hidden = true;
    resultEl.hidden = false;
    if (fromUser) {
      var head = document.getElementById('t-heard');
      if (head) head.focus();
    }
  }

  input.addEventListener('paste', function () {
    if (pasteFired) return;
    pasteFired = true;
    if (window.plausible) window.plausible('Translator Paste');
  });
  input.addEventListener('input', syncGo);
  go.addEventListener('click', function () { showResult(input.value, true); });

  document.getElementById('t-again').addEventListener('click', showAsk);

  document.getElementById('t-copy').addEventListener('click', function () {
    if (!current) return;
    var btn = document.getElementById('t-copy');
    var url = pageUrl(current.pitch);
    var label = 'Copy link';
    var mark = function () {
      btn.textContent = 'Copied';
      window.setTimeout(function () { btn.textContent = label; }, 1600);
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

  document.getElementById('t-download').addEventListener('click', function () {
    if (!current) return;
    drawCard().then(function (canvas) {
      canvas.toBlob(function (blob) {
        if (!blob) return;
        var a = document.createElement('a');
        var href = URL.createObjectURL(blob);
        a.href = href;
        a.download = 'what-the-super-hears.png';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.setTimeout(function () { URL.revokeObjectURL(href); }, 2000);
      }, 'image/png');
    });
  });

  var params = new URLSearchParams(window.location.search);
  var initial = cleanPitch(params.get('pitch') || '');
  if (initial) {
    input.value = initial;
    showResult(initial, false);
  }
  syncGo();

  function fontReady() {
    if (!document.fonts || !document.fonts.load) return Promise.resolve();
    return Promise.all([
      document.fonts.load('400 72px Anton'),
      document.fonts.load('400 32px Archivo'),
      document.fonts.load('500 22px "DM Mono"')
    ]).then(function () { return document.fonts.ready; }).catch(function () {});
  }

  function wrap(ctx, text, max) {
    var words = String(text || '').split(/\s+/).filter(Boolean);
    var lines = [];
    var line = '';
    function pushChars(word) {
      var buf = '';
      for (var i = 0; i < word.length; i++) {
        var test = buf + word.charAt(i);
        if (ctx.measureText(test).width > max && buf) {
          lines.push(buf);
          buf = word.charAt(i);
        } else {
          buf = test;
        }
      }
      return buf;
    }
    for (var w = 0; w < words.length; w++) {
      var word = words[w];
      if (ctx.measureText(word).width > max) {
        if (line) { lines.push(line); line = ''; }
        line = pushChars(word);
        continue;
      }
      var next = line ? line + ' ' + word : word;
      if (ctx.measureText(next).width > max && line) {
        lines.push(line);
        line = word;
      } else {
        line = next;
      }
    }
    if (line) lines.push(line);
    return lines.length ? lines : [''];
  }

  function wrapUrl(ctx, url, max) {
    var bits = String(url || '').split(/(?=[?&])/);
    var lines = [];
    var line = '';
    bits.forEach(function (bit) {
      if (!bit) return;
      var next = line + bit;
      if (line && ctx.measureText(next).width > max) {
        lines.push(line);
        line = bit;
      } else {
        line = next;
      }
    });
    if (line) lines.push(line);
    var out = [];
    lines.forEach(function (ln) {
      if (ctx.measureText(ln).width > max) out = out.concat(wrap(ctx, ln, max));
      else out.push(ln);
    });
    return out.length ? out : [''];
  }

  function fillHazard(ctx, y, w, h) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, y, w, h);
    ctx.clip();
    ctx.fillStyle = '#0B0F12';
    ctx.fillRect(0, y, w, h);
    ctx.strokeStyle = '#F68B4F';
    ctx.lineWidth = 13;
    var step = 13 * Math.SQRT2 * 2;
    ctx.beginPath();
    for (var i = -h; i < w + h; i += step) {
      ctx.moveTo(i, y);
      ctx.lineTo(i - h, y + h);
    }
    ctx.stroke();
    ctx.restore();
  }

  function cardCopy() {
    var flagEl = document.getElementById('t-card-flag');
    var ctaEl = document.querySelector('#t-subscribe .btn');
    return {
      brand: document.getElementById('t-brand').textContent.trim(),
      flag: flagEl && !flagEl.hidden ? flagEl.textContent.trim() : '',
      kicker: document.getElementById('t-heard').textContent.trim(),
      pitch: document.getElementById('t-pitch').textContent.trim(),
      line: document.getElementById('t-line').textContent.trim(),
      score: current ? current.score : 0,
      joke: document.getElementById('t-joke').textContent.trim(),
      cta: ctaEl ? ctaEl.textContent.trim() : 'Subscribe to Construction Briefs',
      url: subUrl,
      foot: document.getElementById('t-gantrics').textContent.trim()
    };
  }

  function drawCard() {
    return fontReady().then(function () {
      var copy = cardCopy();
      var W = 1200;
      var pad = 72;
      var inner = W - pad * 2;
      var canvas = document.createElement('canvas');
      canvas.width = W;
      canvas.height = 400;
      var ctx = canvas.getContext('2d');

      function measure() {
        var y = 28 + 48;
        ctx.font = '500 18px "DM Mono", monospace';
        y += 28;
        if (copy.flag) y += 36;
        ctx.font = '400 68px Anton, sans-serif';
        var title = wrap(ctx, copy.kicker.toUpperCase(), inner);
        y += title.length * 74 + 16;
        ctx.font = '400 28px Archivo, sans-serif';
        var pitch = wrap(ctx, copy.pitch, inner);
        y += pitch.length * 40 + 12;
        ctx.font = '500 32px Archivo, sans-serif';
        var line = wrap(ctx, copy.line, inner);
        y += line.length * 46 + 28;
        y += 36 + 22 + 28;
        y += 28 + 72;
        ctx.font = '500 20px "DM Mono", monospace';
        var urlLines = wrapUrl(ctx, copy.url, inner);
        y += urlLines.length * 30 + 28;
        y += 32 + 56;
        return { title: title, pitch: pitch, line: line, urlLines: urlLines, height: y };
      }

      var layout = measure();
      canvas.height = layout.height;
      ctx = canvas.getContext('2d');
      ctx.fillStyle = '#0B0F12';
      ctx.fillRect(0, 0, W, layout.height);
      fillHazard(ctx, 0, W, 18);
      fillHazard(ctx, layout.height - 18, W, 18);

      var y = 18 + 48;
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#F68B4F';
      ctx.font = '500 18px "DM Mono", monospace';
      ctx.fillText(copy.brand.toUpperCase(), pad, y);
      y += 28;
      if (copy.flag) {
        ctx.fillStyle = '#9AA1AA';
        ctx.font = '500 16px "DM Mono", monospace';
        ctx.fillText(copy.flag.toUpperCase(), pad, y);
        y += 36;
      }
      ctx.fillStyle = '#FCFCFC';
      ctx.font = '400 68px Anton, sans-serif';
      layout.title.forEach(function (ln) {
        ctx.fillText(ln, pad, y);
        y += 74;
      });
      y += 16;
      ctx.fillStyle = '#B7BBC0';
      ctx.font = '400 28px Archivo, sans-serif';
      layout.pitch.forEach(function (ln) {
        ctx.fillText(ln, pad, y);
        y += 40;
      });
      y += 12;
      ctx.fillStyle = '#FCFCFC';
      ctx.font = '500 32px Archivo, sans-serif';
      layout.line.forEach(function (ln) {
        ctx.fillText(ln, pad, y);
        y += 46;
      });
      y += 28;
      ctx.fillStyle = '#9AA1AA';
      ctx.font = '500 18px "DM Mono", monospace';
      ctx.fillText('BUZZWORD LOAD', pad, y + 8);
      ctx.fillStyle = '#FCFCFC';
      ctx.font = '400 42px Anton, sans-serif';
      var scoreText = String(copy.score);
      var scoreW = ctx.measureText(scoreText).width;
      ctx.font = '500 16px "DM Mono", monospace';
      var suffix = ' / 100';
      var suffixW = ctx.measureText(suffix).width;
      ctx.font = '400 42px Anton, sans-serif';
      ctx.fillText(scoreText, W - pad - suffixW - scoreW - 8, y);
      ctx.fillStyle = '#9AA1AA';
      ctx.font = '500 16px "DM Mono", monospace';
      ctx.fillText(suffix, W - pad - suffixW, y + 16);
      y += 56;
      ctx.fillStyle = '#232C33';
      ctx.fillRect(pad, y, inner, 16);
      ctx.strokeStyle = '#3A444C';
      ctx.lineWidth = 1;
      ctx.strokeRect(pad + 0.5, y + 0.5, inner - 1, 15);
      ctx.fillStyle = '#F68B4F';
      ctx.fillRect(pad, y, Math.round(inner * (copy.score / 100)), 16);
      y += 28;
      ctx.fillStyle = '#6E767E';
      ctx.font = '500 16px "DM Mono", monospace';
      ctx.fillText(copy.joke.toUpperCase(), pad, y);
      y += 40;
      var btnH = 64;
      ctx.font = '700 22px Archivo, sans-serif';
      var cta = copy.cta.toUpperCase();
      var ctaW = ctx.measureText(cta).width + 56;
      ctx.fillStyle = '#F68B4F';
      ctx.fillRect(pad, y, ctaW, btnH);
      ctx.fillStyle = '#0B0F12';
      ctx.fillText(cta, pad + 28, y + 20);
      y += btnH + 18;
      ctx.fillStyle = '#B7BBC0';
      ctx.font = '500 20px "DM Mono", monospace';
      layout.urlLines.forEach(function (ln) {
        ctx.fillText(ln, pad, y);
        y += 30;
      });
      y += 28;
      ctx.fillStyle = '#6E767E';
      ctx.font = '500 16px "DM Mono", monospace';
      ctx.fillText(copy.foot.toUpperCase(), pad, y);
      return canvas;
    });
  }
})();
