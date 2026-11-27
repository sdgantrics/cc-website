// Archive search. Pagefind is imported the first time a search box is used,
// and only the word fragments for that query are fetched. Nothing here sends
// the query text to analytics: events carry its length, or a filter name.

(function () {
  var input = document.getElementById('archive-q') || document.getElementById('ep-search');
  var out = document.getElementById('archive-out');
  var filterHost = document.getElementById('archive-filters');
  if (!input || !out) return;

  // Pagefind has no synonym list. Short tokens are also prefix matches
  // ("co" hits "construction"), so abbreviations are rewritten to the
  // canonical phrase and the short form is added as an exact-token search.
  var SYNONYMS = [
    { short: ['co'], long: 'change order', rewrite: true },
    { short: ['rfi', 'rfis'], long: 'request for information', rewrite: true },
    { short: ['t&m', 't & m'], long: 'time and materials', rewrite: false },
    { short: ['super', 'supers'], long: 'superintendent', rewrite: true },
    { short: ['gc'], long: 'general contractor', rewrite: true },
    { short: ['vdc'], long: 'virtual design and construction', rewrite: false },
    { short: ['bim'], long: 'building information modeling', rewrite: false },
    { short: ['pay app', 'pay apps'], long: 'pay application', rewrite: false }
  ];

  var TYPE_ORDER = ['Episode', 'Roundtable', 'Lesson', 'Tool', 'Article'];
  var ROLE_ORDER = ['Super', 'PM', 'Exec', 'Founder'];
  var selected = { type: '', role: '', path: '', guest: '', year: '' };
  var filterCatalog = null;
  var pagefindPromise = null;
  var timer = 0;
  var token = 0;
  var lastQuery = null;
  var lastZero = '';
  var shown = 8;
  var lastItems = null;
  var lastRaw = '';

  window.plausible = window.plausible || function () {
    (window.plausible.q = window.plausible.q || []).push(arguments);
  };

  function norm(s) {
    return String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
  }

  function escRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function phraseSource(phrase) {
    var parts = phrase.split(' ');
    var last = parts.pop();
    var head = parts.map(escRe).join('\\s+');
    var tail = escRe(last) + '(?:s|es)?';
    var body = (head ? head + '\\s+' : '') + tail;
    // Punctuation counts as a boundary, so "Exhibit 12." and "exhibit 12?" match.
    return '(^|[^A-Za-z0-9])(' + body + ')(?=[^A-Za-z0-9]|$)';
  }

  function hasPhrase(q, phrase) {
    return new RegExp(phraseSource(phrase), 'i').test(q);
  }

  function replacePhrase(q, phrase, repl) {
    return q.replace(new RegExp(phraseSource(phrase), 'gi'), function (_m, pre) {
      return pre + repl;
    });
  }

  function planQueries(raw) {
    var primary = norm(raw);
    var extras = [];
    var seen = {};
    function add(q, exact) {
      q = norm(q);
      if (!q) return;
      var key = (exact ? '"' : '') + q;
      if (seen[key] || key === primary || key === '"' + primary + '"') return;
      seen[key] = 1;
      extras.push({ q: q, exact: exact });
    }
    SYNONYMS.forEach(function (group) {
      var shorts = group.short.slice().sort(function (a, b) { return b.length - a.length; });
      var hitShort = '';
      shorts.forEach(function (s) {
        if (!hitShort && hasPhrase(primary, s)) hitShort = s;
      });
      if (hitShort) {
        if (group.rewrite) {
          primary = norm(replacePhrase(primary, hitShort, group.long));
          add(hitShort, hitShort.indexOf(' ') === -1);
        } else {
          add(group.long, false);
        }
      } else if (hasPhrase(primary, group.long)) {
        var back = group.short[0];
        add(back, group.rewrite && back.indexOf(' ') === -1);
      }
    });
    // Unquoted search so every matching section comes back. Phrase checks
    // happen on the excerpts, because a quoted query keeps only one hit
    // per page and would hide a later transcript moment.
    var plans = [{ q: primary, exact: false }];
    extras.forEach(function (e) {
      if (e.q !== primary) plans.push(e);
      else if (e.exact) plans.push(e);
    });
    var dedup = [];
    var seenPlan = {};
    plans.forEach(function (p) {
      var key = (p.exact ? 'e:' : 'b:') + p.q;
      if (seenPlan[key]) return;
      seenPlan[key] = 1;
      dedup.push(p);
    });
    return dedup.slice(0, 4);
  }

  function loadPagefind() {
    if (!pagefindPromise) {
      var base = new URL('pagefind/', document.baseURI).href;
      pagefindPromise = import(base + 'pagefind.js').then(function (mod) {
        return mod.options({ basePath: base, excerptLength: 28 }).then(function () { return mod; });
      });
    }
    return pagefindPromise;
  }

  function filtersArg() {
    var f = {};
    if (selected.type) f.type = selected.type;
    if (selected.role) f.role = selected.role;
    if (selected.path) f.path = selected.path;
    if (selected.guest) f.guest = selected.guest;
    if (selected.year) f.year = selected.year;
    return f;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function parseTitle(title) {
    var parts = String(title || '').split(' %% ');
    if (parts.length < 2) {
      return { label: parts[0] || '', guest: '', slug: '', year: '', roles: [], paths: [], seconds: '' };
    }
    return {
      label: parts[0] || '',
      guest: parts[1] || '',
      slug: parts[2] || '',
      year: parts[3] || '',
      roles: (parts[4] || '').split(',').filter(Boolean),
      paths: (parts[5] || '').split(';').filter(Boolean),
      seconds: parts[6] || ''
    };
  }

  function stemPhrase(phrase) {
    var parts = norm(phrase).split(' ');
    if (!parts.length) return '';
    var last = parts[parts.length - 1];
    if (last.length > 3 && /s$/.test(last) && !/ss$/.test(last)) {
      parts[parts.length - 1] = last.replace(/es$/, '').replace(/s$/, '');
    }
    return parts.join(' ');
  }

  function hasPhraseIn(text, phrase) {
    var stemmed = stemPhrase(phrase);
    if (!stemmed) return false;
    return new RegExp(phraseSource(stemmed), 'i').test(norm(text));
  }

  function plain(s) {
    return String(s || '').replace(/<[^>]+>/g, ' ');
  }

  function passes(info) {
    if (selected.role && info.roles.length && info.roles.indexOf(selected.role) === -1) return false;
    if (selected.guest && info.guest && info.guest !== selected.guest) return false;
    if (selected.year && info.year && info.year !== selected.year) return false;
    if (selected.path && info.paths.length && info.paths.indexOf(selected.path) === -1) return false;
    return true;
  }

  function clock(sec) {
    sec = Math.max(0, sec | 0);
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    if (h) return h + ':' + pad(m) + ':' + pad(s);
    return pad(m) + ':' + pad(s);
  }

  function secondsOf(url, info) {
    var m = /#(?:t=|t-|c-|ch-|q-)(\d+)/.exec(url || '');
    if (m) return parseInt(m[1], 10);
    if (info && /^\d+$/.test(info.seconds || '')) return parseInt(info.seconds, 10);
    return null;
  }

  function slugFrom(url, info) {
    if (info && info.slug) return info.slug;
    var m = /episodes\/((?:ep|ran)-[^./?#]+)/.exec(url || '');
    return m ? m[1] : '';
  }

  function epLabel(slug) {
    var m = /^ep-(\d+)$/.exec(slug || '');
    if (m) {
      var n = String(parseInt(m[1], 10));
      while (n.length < 3) n = '0' + n;
      return 'EP ' + n;
    }
    if (/^ran-/.test(slug || '')) return 'ROUNDTABLE';
    return '';
  }

  function pathOnly(url) {
    var rewritten = String(url || '').replace(/#(t|c|ch|q)-(\d+)\b/, '#t=$2');
    return rewritten.replace(/^https?:\/\/[^/]+/i, '');
  }

  function pageType(data) {
    var types = data.filters && data.filters.type;
    if (types && types.length) return types[0];
    return (data.meta && data.meta.kind) || 'Page';
  }

  function subScore(sub) {
    var locs = sub.weighted_locations || [];
    var s = 0;
    for (var i = 0; i < locs.length; i++) s += Number(locs[i].balanced_score || locs[i].weight || 0);
    return s || locs.length || 0;
  }

  function maxWeight(sub) {
    var locs = sub.weighted_locations || [];
    var m = 0;
    for (var i = 0; i < locs.length; i++) m = Math.max(m, Number(locs[i].weight || 0));
    return m;
  }

  // Transcript paragraphs stay under lesson cards and chapter titles even
  // when a page mentions the words many times.
  function bandOf(anchorId) {
    if (/^(t|c)-\d+$/.test(anchorId)) return 2;
    if (/^l\d+$/.test(anchorId) || /^ch-\d+$/.test(anchorId)) return 0;
    if (/^q-\d+$/.test(anchorId)) return 1;
    return 1;
  }

  function trackSearch(raw, count) {
    var q = raw.trim();
    if (!q) return;
    var len = String(q.length);
    if (q !== lastQuery) {
      lastQuery = q;
      plausible('Search', { props: { length: len } });
    }
    var zeroKey = q + '\n' + JSON.stringify(selected);
    if (count === 0) {
      if (zeroKey !== lastZero) {
        lastZero = zeroKey;
        plausible('Search No Results', { props: { length: len } });
      }
    } else {
      lastZero = '';
    }
  }

  function showMessage(text) {
    out.hidden = false;
    out.innerHTML = '<p class="archive-status stamp">' + esc(text) + '</p>';
  }

  function filterBox() {
    return document.getElementById('archive-filter-body') || filterHost;
  }

  function renderFilters() {
    var box = filterBox();
    if (!filterHost || !box || !filterCatalog) return;
    filterHost.hidden = false;
    var html = '';
    function chips(key, label, values) {
      if (!values.length) return;
      html += '<div class="search-filter-row"><span class="stamp dim">' + esc(label) + '</span>';
      html += '<button type="button" class="filter' + (selected[key] ? '' : ' active') + '" data-filter="' + key + '" data-value="">Any</button>';
      values.forEach(function (v) {
        html += '<button type="button" class="filter' + (selected[key] === v ? ' active' : '') + '" data-filter="' + key + '" data-value="' + esc(v) + '">' + esc(v) + '</button>';
      });
      html += '</div>';
    }
    function ordered(key, prefer) {
      var bag = filterCatalog[key] || {};
      var values = Object.keys(bag);
      values.sort(function (a, b) {
        var ia = prefer.indexOf(a);
        var ib = prefer.indexOf(b);
        if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
        return a.localeCompare(b);
      });
      return values;
    }
    chips('type', 'Type', ordered('type', TYPE_ORDER));
    chips('role', 'Role', ordered('role', ROLE_ORDER));
    chips('path', 'Path', ordered('path', []));
    var years = ordered('year', []).sort(function (a, b) { return b.localeCompare(a); });
    var guests = ordered('guest', []);
    if (years.length || guests.length) {
      html += '<div class="search-filter-row">';
      if (years.length) {
        html += '<label class="stamp dim">Year <select data-filter="year" aria-label="Filter by year"><option value="">Any</option>';
        years.forEach(function (y) {
          html += '<option value="' + esc(y) + '"' + (selected.year === y ? ' selected' : '') + '>' + esc(y) + '</option>';
        });
        html += '</select></label>';
      }
      if (guests.length) {
        html += '<label class="stamp dim">Guest <select data-filter="guest" aria-label="Filter by guest"><option value="">Any</option>';
        guests.forEach(function (g) {
          html += '<option value="' + esc(g) + '"' + (selected.guest === g ? ' selected' : '') + '>' + esc(g) + '</option>';
        });
        html += '</select></label>';
      }
      html += '</div>';
    }
    box.innerHTML = html;
  }

  function hitHtml(item) {
    var info = item.info;
    var sec = item.seconds;
    var slug = slugFrom(item.url, info);
    var type = item.type;
    var guest = info.guest || item.guest || '';
    var fromMoment = /^(t|c|ch)-\d+$/.test(item.anchorId);
    var when = fromMoment && sec != null ? clock(sec) : '';
    var kicker = [type.toUpperCase(), epLabel(slug), guest, item.date, when].filter(Boolean).join(' · ');
    var heading = info.label || item.pageTitle || 'Result';
    var chapter = '';
    if (type === 'Episode' || type === 'Roundtable') {
      if (/^(t|c|ch|q)-\d+$/.test(item.anchorId)) chapter = info.label;
      heading = item.pageTitle || heading;
    } else if (type === 'Article') {
      if (info.label && item.pageTitle && info.label !== item.pageTitle) chapter = info.label;
      heading = item.pageTitle || heading;
    }
    var href = item.href;
    var play = '';
    if (fromMoment && sec != null && slug) {
      var playHref = 'episodes/' + slug + '.html#t=' + sec;
      play = '<a class="hit-play" href="' + esc(playHref) + '" data-event="Search Play From Here">Play from here</a>';
      if (/episodes\//.test(href)) href = playHref;
    }
    var titleClass = (type === 'Lesson' || type === 'Tool' || type === 'Article') ? 'hit-title hit-title-text' : 'hit-title';
    return (
      '<article class="archive-hit" tabindex="-1" data-type="' + esc(type) + '">' +
        '<p class="stamp hit-kicker">' + esc(kicker) + '</p>' +
        '<h2 class="' + titleClass + '"><a href="' + esc(href) + '">' + esc(heading) + '</a></h2>' +
        (chapter ? '<p class="hit-chapter">' + esc(chapter) + '</p>' : '') +
        (item.excerpt ? '<p class="hit-excerpt">' + item.excerpt + '</p>' : '') +
        play +
      '</article>'
    );
  }

  function render(items, raw) {
    trackSearch(raw, items.length);
    if (!items.length) {
      showMessage('Nothing in the archive matches that.');
      return;
    }
    var slice = items.slice(0, shown);
    var more = items.length > slice.length
      ? '<button type="button" class="btn btn-ghost archive-more">Show more</button>'
      : '';
    out.hidden = false;
    out.innerHTML = '<p class="stamp archive-count">' + items.length + (items.length === 1 ? ' match' : ' matches') + '</p>' +
      slice.map(hitHtml).join('') + more;
  }

  function collect(pages, phrases) {
    var items = [];
    var seenHref = {};
    pages.forEach(function (page) {
      var data = page.data;
      var type = pageType(data);
      var meta = data.meta || {};
      var subs = data.sub_results || [];
      var anchored = subs.filter(function (s) { return s.anchor && s.anchor.id; });
      var use = anchored.length ? anchored : subs;
      use.forEach(function (sub) {
        var anchorId = (sub.anchor && sub.anchor.id) || '';
        var info = parseTitle(sub.title || '');
        if (!passes(info)) return;
        if (phrases && phrases.length) {
          var blob = plain(info.label + ' ' + (sub.excerpt || '') + ' ' + (sub.plain_excerpt || ''));
          var hit = false;
          for (var p = 0; p < phrases.length; p++) {
            if (hasPhraseIn(blob, phrases[p])) { hit = true; break; }
          }
          if (!hit) return;
        }
        var url = sub.url || data.url || '';
        var sec = secondsOf(url, info);
        var href = pathOnly(url);
        if (sec != null && /#(t|c|ch|q)-\d+/.test(url)) href = pathOnly(url.replace(/#(t|c|ch|q)-\d+/, '#t=' + sec));
        if (/^l\d+$/.test(anchorId)) href = pathOnly(url);
        if (seenHref[href]) return;
        seenHref[href] = 1;
        items.push({
          type: type,
          info: info,
          anchorId: anchorId,
          url: url,
          href: href,
          seconds: sec,
          excerpt: sub.excerpt || '',
          pageTitle: meta.title || '',
          guest: meta.guest || '',
          date: meta.date || '',
          band: bandOf(anchorId, maxWeight(sub)),
          priority: page.priority,
          subScore: subScore(sub),
          pageScore: page.score
        });
      });
    });
    items.sort(function (a, b) {
      if (a.band !== b.band) return a.band - b.band;
      if (a.priority !== b.priority) return a.priority - b.priority;
      if (b.subScore !== a.subScore) return b.subScore - a.subScore;
      return b.pageScore - a.pageScore;
    });
    return items;
  }

  function run() {
    var raw = input.value;
    var my = ++token;
    window.clearTimeout(timer);
    if (!norm(raw)) {
      out.hidden = true;
      out.innerHTML = '';
      if (filterHost && !filterCatalog) filterHost.hidden = true;
      if (window.history && window.history.replaceState && document.getElementById('archive-q')) {
        var clean = new URL(window.location.href);
        clean.searchParams.delete('q');
        window.history.replaceState(null, '', clean.pathname + clean.search);
      }
      return;
    }
    timer = window.setTimeout(function () {
      showMessage('Searching the archive…');
        var plans = planQueries(raw);
        var phrases = plans.map(function (p) { return p.q; });
        var filters = filtersArg();
      loadPagefind().then(function (mod) {
        if (!filterCatalog) {
          return mod.filters().then(function (f) {
            filterCatalog = f || {};
            renderFilters();
            return mod;
          });
        }
        return mod;
      }).then(function (mod) {
        return Promise.all(plans.map(function (p) {
          var q = p.exact ? '"' + p.q + '"' : p.q;
          return mod.search(q, { filters: filters });
        })).then(function (searches) {
          var best = new Map();
          searches.forEach(function (res, i) {
            (res.results || []).forEach(function (r) {
              var prev = best.get(r.id);
              if (!prev || i < prev.priority || (i === prev.priority && r.score > prev.score)) {
                best.set(r.id, { result: r, priority: i, score: r.score });
              }
            });
          });
          var ranked = Array.from(best.values()).sort(function (a, b) {
            if (a.priority !== b.priority) return a.priority - b.priority;
            return b.score - a.score;
          }).slice(0, 40);
          return Promise.all(ranked.map(function (page) {
            return page.result.data().then(function (data) {
              return { data: data, priority: page.priority, score: page.score };
            });
          }));
        });
      }).then(function (pages) {
        if (my !== token) return;
        if (document.getElementById('archive-q')) {
          var url = new URL(window.location.href);
          url.searchParams.set('q', raw.trim());
          window.history.replaceState(null, '', url.pathname + url.search);
        }
        lastItems = collect(pages, phrases);
        lastRaw = raw;
        render(lastItems, lastRaw);
      }).catch(function () {
        if (my !== token) return;
        showMessage('Search is unavailable. Build the index with Pagefind, then reload.');
      });
    }, 180);
  }

  filterHost && filterHost.addEventListener('click', function (e) {
    var btn = e.target.closest('button[data-filter]');
    if (!btn) return;
    var key = btn.getAttribute('data-filter');
    var value = btn.getAttribute('data-value') || '';
    if (!Object.prototype.hasOwnProperty.call(selected, key)) return;
    selected[key] = value;
    shown = 8;
    plausible('Search Filter', { props: { filter: key, value: value || 'any' } });
    renderFilters();
    run();
  });

  filterHost && filterHost.addEventListener('change', function (e) {
    var el = e.target;
    if (!el || !el.getAttribute || !el.getAttribute('data-filter')) return;
    var key = el.getAttribute('data-filter');
    if (!Object.prototype.hasOwnProperty.call(selected, key)) return;
    selected[key] = el.value || '';
    shown = 8;
    plausible('Search Filter', { props: { filter: key, value: el.value || 'any' } });
    run();
  });

  out.addEventListener('click', function (e) {
    if (e.target.closest('.archive-more')) {
      shown += 12;
      if (lastItems) render(lastItems, lastRaw);
      return;
    }
    var hit = e.target.closest('.archive-hit');
    if (!hit || e.target.closest('.hit-play')) return;
    if (e.target.closest('a')) {
      plausible('Search Result Click', { props: { type: hit.getAttribute('data-type') || 'Page' } });
    }
  });

  input.addEventListener('input', function () {
    shown = 8;
    run();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Enter' && e.key !== 'Escape') return;
    var hits = Array.prototype.slice.call(out.querySelectorAll('.archive-hit'));
    var inSearch = e.target === input || out.contains(e.target) || (filterHost && filterHost.contains(e.target));
    if (!inSearch || !hits.length) return;
    if (e.key === 'Escape') {
      input.focus();
      return;
    }
    var i = hits.findIndex(function (h) { return h.classList.contains('is-active') || h.contains(document.activeElement); });
    if (e.key === 'Enter' && e.target === input) {
      e.preventDefault();
      var link = hits[0].querySelector('h2 a');
      if (link) link.click();
      return;
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (e.target !== input && !out.contains(e.target)) return;
    e.preventDefault();
    var next = i;
    if (e.key === 'ArrowDown') next = i < 0 ? 0 : Math.min(hits.length - 1, i + 1);
    else next = i <= 0 ? 0 : i - 1;
    hits.forEach(function (h) { h.classList.remove('is-active'); });
    hits[next].classList.add('is-active');
    var title = hits[next].querySelector('h2 a');
    if (title) title.focus();
  });

  var preset = new URLSearchParams(window.location.search).get('q');
  if (preset && !input.value) input.value = preset;
  if (norm(input.value)) run();
})();
