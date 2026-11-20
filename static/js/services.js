/* «Услуги · <объект>» (2026-11-19): every service of the object in one window, saved by «Сохранить» only (2026-11-20).
   Left: «Начисление» — a click starts a NEW service charged so; «Услуги объекта» — the ready ones.
   Right: the chosen service. The server gives the state (svc-state) and takes one service per change. */
(function () {
  'use strict';

  var MODE_ICON = {
    receipt: '<path d="M7 3h10v18l-2.5-1.5L12 21l-2.5-1.5L7 21zM10 8h4M10 12h4"/>',
    fixed: '<path d="M5 9h14M5 15h14"/>',
    area: '<path d="M4 4h16v16H4zM4 4l16 16"/>',
    meters: '<path d="M4 16a8 8 0 1 1 16 0M12 16l4-5"/>',
    formula: '<path d="M10 4c-2 0-2 2-2 4v8c0 2 0 4-2 4M5 10h6M14 10l6 8M20 10l-6 8"/>'
  };
  var CP_ICON = {
    receipt: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    fixed: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    area: '<path d="M3 15.5 15.5 3 21 8.5 8.5 21z"/><path d="m7 12 2 2M10 9l1.5 1.5M13 6l2 2"/>',
    meters: '<path d="M12 14l3.5-3.5"/><path d="M3.3 17a9.5 9.5 0 1 1 17.4 0"/><circle cx="12" cy="14" r="1.5"/>',
    people: '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5M16 5a3 3 0 0 1 0 6M18 15c2 .5 3 2.5 3 5"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    warn: '<path d="M12 3 2 20h20zM12 10v4M12 17h.01"/>',
    formula: '<path d="M10 4c-2 0-2 2-2 4v8c0 2 0 4-2 4M5 10h6M14 10l6 8M20 10l-6 8"/>',
    check: '<path d="M5 12l5 5L20 7"/>'
  };
  var SPLITS = [['shares', 'по долям'], ['equal', 'поровну'], ['area', 'по м²']];
  var SAMPLE = 5800;  // a sum for the example of «По квитанции» — the receipt's sum is not known yet

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function svg(path, cls) { return '<svg class="sv-i' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" aria-hidden="true">' + path + '</svg>'; }
  function sprite(kind, cls) {
    return '<svg class="icon ' + (cls || '') + '" aria-hidden="true"><use href="#i-r-' + esc(kind || 'custom') + '"/></svg>';
  }
  function kindIcon(kind) { return '<span class="sv-kind rk-' + esc(kind || 'custom') + '">' + sprite(kind) + '</span>'; }
  // a meter under an own name — the gauge (its group is grey), not the «document» of an own service
  function meterIcon(kind) {
    kind = kind || 'custom';
    var icon = kind === 'custom' ? '<svg class="icon" aria-hidden="true"><use href="#i-gauge"/></svg>' : sprite(kind);
    return '<span class="sv-mkind mk-' + esc(kind) + '">' + icon + '</span>';
  }
  function num(n) { return n == null ? '' : Number(n).toLocaleString('ru-RU', { maximumFractionDigits: 3 }); }
  function money(n) {
    n = Math.round(n * 100 + 1e-6) / 100;
    return n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₽';
  }
  function parse(v) {
    v = String(v || '').replace(/\s/g, '').replace(',', '.');
    if (v === '') return null;
    var n = parseFloat(v);
    return isFinite(n) ? n : null;
  }

  window.initServiceWindow = function (root) {
    var box = root.querySelector && root.querySelector('[data-svcwin]');
    if (!box || box.dataset.ready) return;
    box.dataset.ready = '1';
    var S = JSON.parse(box.querySelector('#svc-state').textContent);
    var nav = box.querySelector('[data-svc-nav]');
    var pane = box.querySelector('[data-svc-pane]');
    var csrf = (box.querySelector('input[name=csrfmiddlewaretoken]') || {}).value || '';
    var T = S.tenants;
    var current = null, editing = false, unitOpen = false, unitNew = '', addedUnits = [];
    var meterOpen = null, draft = null, exampleOpen = false, dirty = false, confirmDelete = false;
    // changed — there are changes not saved yet; asking — «Сохранить изменения?» before leaving this service;
    // pickOpen — the meter whose «Кто платит» menu is open; snap — the meters as they were (to undo «Не сохранять»).
    var changed = false, asking = null, askJump = null, pickOpen = null, snap = copy(S.meters);
    // After «Сохранить» or «Удалить» — a new service «По квитанции», ready for its name (the user's wish, 2026-11-19).
    function nextNew() {
      startNew('receipt');
      unitOpen = false; exampleOpen = false; meterOpen = null; confirmDelete = false; pickOpen = null;
      render(); pane.scrollTop = 0;
      var input = pane.querySelector('[data-f="name"]'); if (input) input.focus();
    }

    function byId(list, id) { return list.filter(function (x) { return x.id === id; })[0]; }
    function copy(s) { return JSON.parse(JSON.stringify(s)); }
    function tname(id) { var t = byId(T, id); return t ? t.name : ''; }
    function modeName(mode) { return S.modes.filter(function (m) { return m[0] === mode; })[0][1]; }

    function startNew(mode) {
      current = { id: null, isNew: true, kind: 'custom', name: '', provider: '', mode: mode, split: 'shares', excluded: [],
                  owner_takes: true, fixed: null, rate: null, unit: 'м²', volume: null, meters: [], group: null, autoName: false };
      changed = false; snap = copy(S.meters);
      if (mode === 'meters' && S.start && S.start.meter) {
        var m = byId(S.meters, S.start.meter);
        if (m && !busyGroup(m.group)) pickGroup(m.group);
      }
      editing = true;
    }
    // «По счётчикам» (2026-11-20): one service — one kind of meters. A group is busy when its meters are in another service.
    function groupOf(key) { return S.groups.filter(function (g) { return g.key === key; })[0]; }
    function busyGroup(key) {
      var g = groupOf(key);
      if (!g) return null;
      var other = S.meters.filter(function (m) { return g.meters.indexOf(m.id) >= 0 && m.service && m.service !== current.id; })[0];
      return other ? other.service : null;
    }
    function pickGroup(key) {
      var g = groupOf(key);
      current.group = key; current.meters = g.meters.slice(); current.kind = g.kind;
      // A meter in no service yet: «кто платит» is not chosen (the owner when there are no tenants).
      S.meters.forEach(function (m) {
        if (g.meters.indexOf(m.id) >= 0 && !m.service) { m.who = T.length ? '' : 'owner'; m.input = 'readings'; }
      });
      if (!String(current.name || '').trim() || current.autoName) { current.name = g.name; current.autoName = true; }
    }
    function mark() { changed = true; status('Есть несохранённые изменения'); }
    // Leaving the service with changes not saved: ask first (go — what to do after).
    // jumpTo — the name of the service we go to from «Уже в услугах»: then «Перейти в «…»?».
    function leave(go, jumpTo) {
      if (!changed) { go(); return; }
      asking = go; askJump = jumpTo || null; renderPane();
    }

    // ---------- the left menu ----------
    function renderNav() {
      var h = '<div class="sv-nav-cap">Начисление</div>';
      S.modes.forEach(function (m) {
        var on = current && current.isNew && current.mode === m[0];
        h += '<button type="button" class="sv-nav-item is-mode' + (on ? ' is-on' : '') + '" data-mode="' + m[0] + '">' +
          svg(MODE_ICON[m[0]]) + '<span class="fade">' + m[1] + '</span>' + (on ? svg(CP_ICON.check, 'sv-check') : '') + '</button>';
      });
      h += '<div class="sv-nav-sep"></div><div class="sv-nav-cap">Услуги объекта · ' + S.services.length + '</div>';
      S.services.forEach(function (s) {
        var on = current && current.id === s.id;
        h += '<button type="button" class="sv-nav-item' + (on ? ' is-active' : '') + '" data-svc="' + s.id + '">' +
          kindIcon(s.kind) + '<span class="fade">' + esc(s.name) + '</span></button>';
      });
      nav.innerHTML = h;
    }

    // ---------- «Делим и кто платит» (квитанция, фикс, тариф — одинаково) ----------
    function weight(t, how) { return how === 'equal' ? 1 : how === 'area' ? (t.area || 0) : (t.share || 0); }
    function shares(how, excluded, ownerTakes) {
      var on = T.filter(function (t) { return excluded.indexOf(t.id) < 0; });
      var off = T.length - on.length;
      var sum = function (l) { return l.reduce(function (a, t) { return a + weight(t, how); }, 0); };
      var canPass = on.length > 0 && off > 0;
      var takes = !canPass || ownerTakes !== false;
      // По долям / по м² with the owner taking: of 100% / of the object's area (the free part is the owner's too).
      var all = how === 'shares' ? 100 : how === 'area' ? (S.property.area || sum(T)) : T.length;
      var base = takes ? all : sum(on);
      var r = { canPass: canPass, takes: takes, off: off, k: {} };
      var given = 0;
      T.forEach(function (t) {
        r.k[t.id] = excluded.indexOf(t.id) < 0 && base ? weight(t, how) / base : 0;
        given += r.k[t.id];
      });
      r.owner = Math.max(0, 1 - given);
      return r;
    }
    function wholeArea() { return S.property.area || T.reduce(function (a, t) { return a + (t.area || 0); }, 0); }
    // по м² — the м² one pays for: its own while the owner takes the rest, a bigger part when the paying ones share it all
    function partText(how, r, t) {
      if (how === 'area') return t.area != null ? num(Math.round(r.k[t.id] * wholeArea() * 100) / 100) + ' м²' : '— м²';
      if (how === 'equal') return '1/' + (r.takes ? T.length : T.length - r.off);
      return Math.round(r.k[t.id] * 1000) / 10 + '%';
    }
    function ownerPartText(how, r) {
      if (r.owner <= 0.00001) return '—';
      if (how === 'area') {
        return num(Math.round(r.owner * wholeArea() * 100) / 100) + ' м²';
      }
      if (how === 'equal') return r.off + '/' + T.length;
      return Math.round(r.owner * 1000) / 10 + '%';
    }
    function splitTop(how, attr) {
      return '<div class="sv-split-top">' + svg(CP_ICON.people) + '<div class="sv-how">' + SPLITS.map(function (x) {
        return '<button type="button" ' + attr + '="' + x[0] + '"' + (x[0] === how ? ' class="is-on"' : '') + '>' + x[1] + '</button>';
      }).join('') + '</div></div>';
    }
    function sw(on, attr, label) {
      return '<button type="button" class="sv-sw' + (on ? ' is-on' : '') + '" ' + attr + ' role="switch" aria-checked="' + on +
        '" aria-label="' + esc(label) + '"></button>';
    }
    function serviceTotal(s) {
      if (s.mode === 'fixed') return s.fixed;
      if (s.mode === 'area') { var v = volume(s); return s.rate != null && v != null ? s.rate * v : null; }
      return null;
    }
    function payRows(s) {
      if (!T.length) {
        return '<div class="sv-gp"><div class="sv-gp-row is-owner"><span></span><span class="sv-who">' +
          (S.property.owner_used ? 'Пользуетесь сами — всё на вас' : 'Арендаторов пока нет — всё на вас') + '</span><span></span><span></span><span></span></div></div>';
      }
      var r = shares(s.split, s.excluded, s.owner_takes);
      var total = serviceTotal(s), sample = total == null;
      if (sample) total = SAMPLE;
      var sc = sample ? ' is-sample' : '';
      var rows = T.map(function (t, i) {
        var on = s.excluded.indexOf(t.id) < 0;
        var meta = s.split === 'area' ? (t.area != null ? num(t.area) + ' м²' : '— м²') :
          s.split === 'equal' ? '1/' + (on && !r.takes ? T.length - r.off : T.length) :
          (on ? Math.round(r.k[t.id] * 1000) / 10 : t.share) + '%';
        return '<div class="sv-gp-row' + (on ? '' : ' is-off') + '"><span class="sv-no">' + (i + 1) + '</span>' +
          '<span class="sv-who fade">' + esc(t.name) + '</span><span class="sv-meta">' + meta + '</span>' +
          '<span class="sv-sum' + (on ? sc : '') + '">' + (on ? money(total * r.k[t.id]) : 'не платит') + '</span>' +
          sw(on, 'data-pay="' + t.id + '"', t.name + ' платит') + '</div>';
      }).join('');
      var ownerSum = r.owner > 0.00001 ? money(total * r.owner) : '—';
      rows += '<div class="sv-gp-row is-owner' + (r.canPass ? ' can-pass' : '') + (r.takes ? '' : ' is-off') + '"><span></span>' +
        '<span class="sv-who">Остаётся на вас</span><span class="sv-meta"></span>' +
        '<span class="sv-sum' + (r.owner > 0.00001 ? sc : '') + '">' + ownerSum + '</span>' +
        (r.canPass ? sw(r.takes, 'data-owner', 'Остаток на вас') : '<span></span>') + '</div>';
      return '<div class="sv-gp">' + splitTop(s.split, 'data-split') + rows + '</div>';
    }

    // «Своя формула» where each pays by his own meters: nothing to divide, only who pays (the rest — on the owner).
    function eachRows(s) {
      return '<div class="sv-gp">' + T.map(function (t, i) {
        var on = s.excluded.indexOf(t.id) < 0;
        return '<div class="sv-gp-row' + (on ? '' : ' is-off') + '"><span class="sv-no">' + (i + 1) + '</span>' +
          '<span class="sv-who fade">' + esc(t.name) + '</span><span class="sv-meta"></span>' +
          '<span class="sv-sum">' + (on ? 'по своим счётчикам' : 'не платит') + '</span>' +
          sw(on, 'data-pay="' + t.id + '"', t.name + ' платит') + '</div>';
      }).join('') + '</div>';
    }

    // ---------- «Своя формула»: its own window over this one (formula.js); «Готово» — into this service ----------
    function openFormula() {
      var s = current, last = null, first = null;
      window.rentflowFormula.open({
        ctx: s.fx || S.fx_new, state: s.fx_data || null,
        host: box.closest('dialog') || document.body,
        split: function () { return s.split; },
        canPay: function (id) { return !!byId(T, id); },
        isOff: function (id) { return s.excluded.indexOf(id) >= 0; },
        togglePay: function (id) { toggle(s.excluded, id); mark(); },
        // the first publish is the formula as it opened: «Готово» without changes changes nothing
        publish: function (data, words, each) {
          last = { data: data, words: words, each: each, json: JSON.stringify(data) };
          if (first == null) first = last.json;
        },
        close: function (keep) {
          if (keep && last && last.json !== first) {
            s.fx_data = last.data; s.formula = last.words; s.fx_each = last.each && T.length > 0;
            mark();
          }
          if (current === s) renderPane();
        }
      });
    }

    // ---------- «По тарифу»: Тариф ₽ за [ед.] × [объём] = итог ----------
    function volume(s) { return s.volume != null ? s.volume : (s.unit === 'м²' ? S.property.area : null); }
    function unitPick(s) {
      var row = function (u, own) {
        return '<li class="sv-sel-row' + (u === s.unit ? ' is-selected' : '') + '"><button type="button" class="sv-sel-opt" data-unit="' + esc(u) + '">' +
          '<span>' + esc(u) + '</span>' + svg(CP_ICON.check, 'sv-ck') + '</button>' +
          (own ? '<button type="button" class="sv-sel-remove" data-unit-del="' + esc(u) + '" title="Удалить вариант" aria-label="Удалить вариант">×</button>' : '') + '</li>';
      };
      var own = S.own_units.concat(addedUnits.filter(function (u) { return S.own_units.indexOf(u) < 0; }));
      if (S.units.indexOf(s.unit) < 0 && own.indexOf(s.unit) < 0) own.push(s.unit);
      return '<span class="sv-unit-pick"><button type="button" class="sv-pick" data-unit-open aria-haspopup="true" aria-expanded="' + unitOpen + '">' +
        esc(s.unit) + '<svg class="icon sv-chev"><use href="#i-chevron-down"/></svg></button>' +
        (unitOpen ? '<div class="sv-sel-menu"><ul>' + S.units.map(function (u) { return row(u, false); }).join('') +
          own.map(function (u) { return row(u, addedUnits.indexOf(u) >= 0 && u !== s.unit); }).join('') + '</ul>' +
          '<div class="sv-sel-add"><span class="sv-plus">+</span><input data-f="unitNew" value="' + esc(unitNew) + '" placeholder="свой вариант…" maxlength="12" aria-label="Своя единица">' +
          (unitNew.trim() ? '<button type="button" class="sv-sel-add-btn" data-unit-add>Добавить</button>' : '') + '</div></div>' : '') + '</span>';
    }
    function field(f, v, unit, cls, ph) {
      return '<span class="sv-num' + (cls ? ' ' + cls : '') + '"><input data-f="' + f + '" value="' + (v != null ? num(v) : '') +
        '" placeholder="' + (ph || '0,00') + '" inputmode="decimal" autocomplete="off"><span class="sv-num-unit">' + esc(unit) + '</span></span>';
    }
    function cp(icon, inner) { return '<div class="sv-cp">' + svg(CP_ICON[icon]) + inner + '</div>'; }
    function block(title, body) { return '<div class="sv-sec"><h3>' + title + '</h3>' + body + '</div>'; }

    // ---------- «По счётчикам» (вариант 6): все счётчики объекта, кто платит — в окне счётчика ----------
    function payerName(m) {
      if (m.who === 'common') return 'Общий<small>' + SPLITS.filter(function (x) { return x[0] === (m.split || 'shares'); })[0][1] + '</small>';
      if (m.who === 'owner') return 'Платите вы';
      return esc(tname(m.who));
    }
    // Short tenant names for the parts badge: without ИП / ООО / «Арендатор» and quotes, the first word
    // («Аптека Вита» → «Аптека», «ИП Иванов П. С.» → «Иванов», «Арендатор А» → «А»); long — cut to 8 letters + «.»;
    // the same short twice — the next word's first letter is added («Иванов П.» / «Иванов С.»).
    var LEGAL = /^(ип|ооо|оао|зао|пао|ао|нко|арендатор)$/i;
    function shortNames() {
      var words = {}, out = {};
      T.forEach(function (t) {
        var w = String(t.name || '').replace(/[«»"']/g, ' ').split(/\s+/).filter(function (x) { return x && !LEGAL.test(x); });
        words[t.id] = w.length ? w : [String(t.name || '')];
        var f = words[t.id][0];
        out[t.id] = f.length > 9 ? f.slice(0, 8) + '.' : f;
      });
      var first = {};
      T.forEach(function (t) { first[t.id] = out[t.id]; });
      T.forEach(function (t) {
        var twin = T.filter(function (o) { return first[o.id] === first[t.id]; });
        if (twin.length > 1) {
          var next = words[t.id][1];
          out[t.id] = first[t.id] + ' ' + (next ? next.charAt(0) + '.' : twin.indexOf(t) + 1);
        }
      });
      return out;
    }
    // A common meter: «А 60% · Б 40%» in a badge next to its tariff (the full names — in its tooltip).
    // The badge is always there once «кто платит» is chosen: a tenant — «Б 100%», «Платите вы» — «Вы 100%»;
    // a common one — its parts and the owner's «Вы …» (three shown, «+N»; the full names — in its tooltip), ✎ — «Делим».
    function meterParts(m) {
      if (m.who === '' || m.who == null) return '';
      var short = shortNames(), list = [];
      if (m.who === 'owner') list.push(['Вы', 'Вы', '100%']);
      else if (m.who !== 'common') list.push([short[m.who] || '', tname(m.who), '100%']);
      else {
        var how = m.split || 'shares', r = shares(how, m.excluded, m.owner_takes);
        T.filter(function (t) { return m.excluded.indexOf(t.id) < 0; }).forEach(function (t) { list.push([short[t.id], t.name, partText(how, r, t)]); });
        if (r.owner > 0.00001) list.push(['Вы', 'Вы', ownerPartText(how, r)]);
      }
      var shown = list.slice(0, 3).map(function (x) { return esc(x[0] + ' ' + x[2]); });
      if (list.length > 3) shown.push('+' + (list.length - 3));
      var full = list.map(function (x) { return x[1] + ' ' + x[2]; }).join(' · ');
      return '<span class="sv-parts" title="' + esc(full) + '">' + shown.join(' · ') + '</span>' + (m.who !== 'common' ? '' :
        '<button type="button" class="sv-mt-edit" data-meter="' + m.id + '" title="Как делим" aria-label="Как делим"><svg class="icon"><use href="#i-edit"/></svg></button>');
    }
    // «Что считаем»: only free groups; the ones already in a service — info badges in the head of «Как начисляется».
    function busyBadges() {
      var busy = S.groups.filter(function (g) { return busyGroup(g.key); });
      if (!busy.length) return '';
      return '<span class="sv-busy">уже в услугах:' + busy.map(function (g) {
        var svc = byId(S.services, busyGroup(g.key));
        return '<button type="button" class="badge badge-info sv-busy-link" data-svc="' + svc.id + '" title="Открыть «' + esc(svc.name) + '»">' +
          esc(g.name) + (svc.name !== g.name ? ' → «' + esc(svc.name) + '»' : '') + '</button>';
      }).join('') + '</span>';
    }
    function groupTiles(s) {
      if (!S.groups.length) return '<p class="sv-note">У объекта пока нет счётчиков.</p>';
      var free = S.groups.filter(function (g) { return !busyGroup(g.key); });
      var h = free.length ? '<div class="sv-tiles">' + free.map(function (g) {
        var list = g.meters.map(function (id) { return '№ ' + (byId(S.meters, id).serial || '—'); }).join(', ');
        var n = g.meters.length, word = n === 1 ? 'счётчик' : n < 5 ? 'счётчика' : 'счётчиков';
        return '<button type="button" class="sv-tile' + (s.group === g.key ? ' is-on' : '') + '" data-group="' + esc(g.key) + '">' + meterIcon(g.kind) +
          '<span class="sv-tile-t"><b class="fade">' + esc(g.name) + '</b><span class="fade">' + n + ' ' + word + ' · ' + esc(list) + '</span></span></button>';
      }).join('') + '</div>' : '<p class="sv-note">Все счётчики объекта уже в услугах.</p>';
      return h;
    }
    // «Кто платит» (вариант Б, 2026-11-20): a table — Счётчик | Кто платит | Ввод показаний; one line per meter,
    // every row of the same height. A common meter: «Общий · по долям»; the parts — a badge, ✎ right after it — the window «Делим».
    function payerMenu(m) {
      var opt = function (v, label) {
        var sel = String(m.who) === String(v);
        return '<li class="sv-sel-row' + (sel ? ' is-selected' : '') + '"><button type="button" class="sv-sel-opt" data-who-set="' + m.id + ':' + v + '">' +
          '<span>' + esc(label) + '</span>' + svg(CP_ICON.check, 'sv-ck') + '</button></li>';
      };
      // «Общий — делим» with ✎ instead of the check: ✎ opens «Делим» right away (the meter is common after «Готово»)
      var common = '<li class="sv-sel-row sv-sel-common' + (m.who === 'common' ? ' is-selected' : '') + '">' +
        '<button type="button" class="sv-sel-opt" data-who-set="' + m.id + ':common"><span>Общий — делим</span></button>' +
        '<button type="button" class="sv-sel-edit" data-who-edit="' + m.id + '" title="Как делим" aria-label="Как делим"><svg class="icon"><use href="#i-edit"/></svg></button></li>';
      return '<div class="sv-sel-menu sv-payer-menu"><ul>' + T.map(function (t) { return opt(t.id, t.name); }).join('') +
        (T.length ? '<li class="sv-sel-sep"></li>' + common : '') + opt('owner', 'Платите вы') + '</ul></div>';
    }
    function meterTable(s) {
      if (!s.group) return '<div class="sv-mt-ph">Сначала выберите, что считаем</div>';
      var rows = s.meters.map(function (id) {
        var m = byId(S.meters, id), empty = m.who === '' || m.who == null, common = m.who === 'common';
        return '<div class="sv-mt-row sv-mt-line">' + meterIcon(m.kind) +
          '<span class="sv-mt-no"><b class="fade">№ ' + esc(m.serial || '—') + '</b><span class="sv-mt-sub"><span class="fade' + (m.tariff ? '' : ' sv-none') + '">' +
          esc(m.tariff || 'нет тарифа') + (m.dn ? ' · день / ночь' : '') + '</span>' + meterParts(m) + '</span></span>' +
          '<span class="sv-mt-pick"><button type="button" class="sv-pick' + (empty ? ' is-empty' : '') + '" data-pick="' + m.id + '" aria-haspopup="true" aria-expanded="' + (pickOpen === m.id) + '">' +
          '<span class="fade">' + (empty ? 'Выберите' : payerName(m)) + '</span><svg class="icon sv-chev"><use href="#i-chevron-down"/></svg></button>' +
          (pickOpen === m.id ? payerMenu(m) : '') + '</span>' +
          '<div class="sv-seg sv-mt-seg"><button type="button" data-input="' + m.id + ':readings"' + (m.input !== 'usage' ? ' class="is-on"' : '') + '>Было / стало</button>' +
          '<button type="button" data-input="' + m.id + ':usage"' + (m.input === 'usage' ? ' class="is-on"' : '') + '>Расход</button></div></div>';
      }).join('');
      return '<div class="sv-mt"><div class="sv-mt-head"><span></span><span>Счётчик</span><span>Кто платит</span><span>Ввод показаний</span></div>' + rows + '</div>' +
        '<div><a href="' + esc(S.urls.object) + '" data-modal data-svc-return="' + esc(S.urls.window) + '" class="sv-add-link">+ Добавить счётчик объекта</a></div>';
    }
    // «изменить» under a common meter: only how it is divided (who pays by it is chosen in its row).
    function meterWindow() {
      var m = byId(S.meters, meterOpen), d = draft;
      var r = shares(d.split, d.excluded, d.owner_takes);
      var body = splitTop(d.split, 'data-msplit') + T.map(function (t, i) {
        var on = d.excluded.indexOf(t.id) < 0;
        return '<div class="sv-gp-row sv-mshare' + (on ? '' : ' is-off') + '"><span class="sv-no">' + (i + 1) + '</span><span class="sv-who fade">' + esc(t.name) + '</span>' +
          '<span class="sv-pc">' + (on ? partText(d.split, r, t) : 'не платит') + '</span>' + sw(on, 'data-mpay="' + t.id + '"', t.name + ' платит') + '</div>';
      }).join('') + '<div class="sv-gp-row sv-mshare is-owner' + (r.canPass && r.takes ? ' is-live' : '') + '"><span></span><span class="sv-who">Остаётся на вас</span>' +
        '<span class="sv-pc">' + ownerPartText(d.split, r) + '</span>' +
        (r.canPass ? sw(r.takes, 'data-mowner', 'Остаток на вас') : '<span></span>') + '</div>';
      return '<div class="sv-back" data-meter-close><div class="sv-mw" role="dialog" aria-modal="true" aria-label="Общий счётчик — делим">' +
        '<div class="sv-mw-head">' + meterIcon(m.kind) + '<b>№ ' + esc(m.serial || '—') + '</b><span class="sv-sub">общий — делим</span>' +
        '<button type="button" class="sv-x" data-meter-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
        '<div class="sv-mw-body"><div class="sv-gp">' + body + '</div></div>' +
        '<div class="sv-mw-foot"><button type="button" class="btn btn-ghost btn-auto" data-meter-close>Отмена</button>' +
        '<button type="button" class="btn btn-primary btn-auto" data-meter-done>Готово</button></div></div></div>';
    }

    // ---------- «См. пример на странице объекта» ----------
    function example(s) {
      var name = '<span class="sv-pv-name"><span class="fade">' + esc(s.name || 'Новая услуга') + '</span><svg class="icon"><use href="#i-edit"/></svg></span>' +
        (s.provider ? '<span class="sv-pv-sub fade">' + esc(s.provider) + '</span>' : '');
      if (s.mode === 'receipt') {
        return '<div class="sv-pv-card"><div class="sv-pv-head">Суммы из квитанций<span class="badge badge-accent">за весь объект</span></div>' +
          '<div class="sv-pv-row"><span class="sv-pv-who">' + name + '</span><span class="sv-pv-field"><span>' + num(SAMPLE) + '</span><span class="sv-num-unit">₽</span></span></div></div>';
      }
      if (s.mode === 'fixed' || s.mode === 'area') {
        var total = serviceTotal(s);
        return '<div class="sv-pv-card"><div class="sv-pv-head">Считается само</div>' +
          '<div class="sv-pv-row"><span class="sv-pv-who">' + name + '</span><span class="sv-pv-sum">' + (total != null ? money(total) : '—') + '</span></div></div>';
      }
      var list = S.meters.filter(function (m) { return s.meters.indexOf(m.id) >= 0; });
      if (!list.length) return '<p class="sv-note">Включите счётчики — они появятся на странице объекта.</p>';
      var kinds = list.map(function (m) { return m.kind; }).filter(function (k, i, a) { return a.indexOf(k) === i; });
      var mixed = kinds.length > 1;
      var rows = list.map(function (m) {
        var who = m.who === 'common' ? 'общий · ' + SPLITS.filter(function (x) { return x[0] === m.split; })[0][1] : m.who === 'owner' ? 'платите вы' : tname(m.who);
        var parts = m.dn ? ['день', 'ночь'] : [''];
        return parts.map(function (p, j) {
          return '<div class="sv-pr">' + (mixed && j === 0 ? meterIcon(m.kind) : '<span></span>') + '<span class="sv-pr-nm">' +
            (j === 0 ? '<span class="fade">№ ' + esc(m.serial || '—') + (p ? ' <em>' + p + '</em>' : '') + '</span><small class="fade">' + esc(who) + '</small>' : '<em>' + p + '</em>') +
            '</span><span class="sv-pr-v">…</span><span class="sv-pr-in"></span><span class="sv-pr-use"><span>— ' + esc(m.unit) + '</span></span></div>';
        }).join('');
      }).join('');
      return '<div class="sv-pv-cap"><span class="sv-l">Показания счётчиков</span><span>Было</span><span>Стало</span><span>Расход</span></div>' +
        '<div class="sv-pv-group' + (mixed ? '' : ' mk-' + esc(kinds[0])) + '"><div class="sv-pv-gname">' +
        (mixed ? svg(CP_ICON.meters) : meterIcon(kinds[0])) + '<span class="fade">' + esc(s.name || 'Новая услуга') + '</span><svg class="icon sv-pen"><use href="#i-edit"/></svg></div>' + rows + '</div>';
    }

    // ---------- the right part ----------
    function renderPane() {
      var s = current, h = '';
      if (!s) {
        pane.innerHTML = '<div class="sv-empty">' + (S.services.length ? 'Выберите услугу слева или начните новую.' :
          'У объекта пока нет услуг. Выберите слева, как начисляется новая.') + '</div>';
        return;
      }
      h += '<div class="sv-top"><div class="sv-top-line">' + (s.isNew ? '<span class="sv-kind">' + svg(MODE_ICON[s.mode]) + '</span>' : kindIcon(s.kind)) +
        '<span class="sv-name">' + esc(s.name || 'Новая услуга') + '</span>' +
        (s.provider ? '<span class="sv-prov fade">· ' + esc(s.provider) + '</span>' : '') +
        '<button type="button" class="head-icon" data-edit title="Название и поставщик" aria-label="Название и поставщик"><svg class="icon"><use href="#i-edit"/></svg></button>' +
        '<span class="sv-saved" data-saved>' + (changed ? 'Есть несохранённые изменения' : s.id ? 'Сохранено' : '') + '</span>' +
        (s.id ? '<button type="button" class="head-icon sv-del" data-delete title="Удалить услугу" aria-label="Удалить услугу">' +
          '<svg class="icon"><use href="#i-trash"/></svg></button>' : '') + '</div>' +
        // The same fields as everywhere (properties/_field.html): the label over a 38px box.
        (editing ? '<div class="sv-top-edit"><div class="field fl"><label for="sv-name">Название в счёте <span class="req">*</span></label>' +
          '<input type="text" id="sv-name" data-f="name" value="' + esc(s.name) + '" placeholder=" " maxlength="100" autocomplete="off"></div>' +
          '<div class="field fl"><label for="sv-provider">Поставщик <span class="req">*</span></label>' +
          '<input type="text" id="sv-provider" data-f="provider" value="' + esc(s.provider) + '" placeholder=" " maxlength="150" autocomplete="off"></div></div>' : '') +
        '</div><div class="sv-body">';

      var b;
      if (s.mode === 'receipt') b = cp('receipt', '<span>Сумму из квитанции вводите <b>каждый месяц</b> на странице объекта.</span>');
      if (s.mode === 'fixed') b = cp('fixed', '<span>Сумма в месяц</span>' + field('fixed', s.fixed, '₽', 'w-sum'));
      if (s.mode === 'area') {
        var v = volume(s), t = s.rate != null && v != null ? s.rate * v : 0;
        b = cp('area', '<span>Тариф</span>' + field('rate', s.rate, '₽', 'w-tariff') + '<span>за</span>' + unitPick(s) +
          '<span class="sv-op">×</span>' + field('volume', v, s.unit, 'w-vol', '0') + '<span class="sv-cp-total">= ' + money(t) + '</span>');
      }
      if (s.mode === 'meters') b = cp('meters', '<span>Каждый платит по своему счётчику: <b>расход</b> <span class="sv-op">×</span> <b>тариф счётчика</b>. Общий счётчик — делим.</span>');
      if (s.mode === 'formula') {
        b = cp('formula', '<span class="fade sv-formula' + (s.formula ? '' : ' is-empty') + '" title="' + esc(s.formula) + '">' +
          esc(s.formula || 'Формула ещё не собрана') + '</span>' +
          '<button type="button" class="btn btn-primary btn-auto btn-sm" data-fx-open>' + (s.formula ? 'Изменить формулу' : 'Собрать формулу') + '</button>');
      }
      var warn = s.mode === 'area' ? '<span class="sv-badge-warn" title="Объём здесь постоянный. Если есть счётчик — выберите «По счётчикам»: расход возьмётся из показаний.">' +
        svg(CP_ICON.warn) + 'Не для счётчиков</span>' : '';
      h += block('Как начисляется · ' + modeName(s.mode) + warn + (s.mode === 'meters' && s.isNew ? busyBadges() : ''), b);
      if (s.mode === 'formula' && s.fx_each) {
        h += block('Кто платит', eachRows(s));
      } else if (s.mode === 'receipt' || s.mode === 'fixed' || s.mode === 'area' || s.mode === 'formula') {
        h += block('Делим и кто платит' + ((s.mode === 'receipt' || s.mode === 'formula') && T.length ? '<span class="sv-badge-sample">для примера ' + money(SAMPLE).replace(',00', '') + '</span>' : ''), payRows(s));
      } else if (s.mode === 'meters') {
        if (s.isNew) h += block('Что считаем', groupTiles(s));
        var todo = s.meters.filter(function (id) { var m = byId(S.meters, id); return m.who === '' || m.who == null; }).length;
        h += block('Кто платит' + (todo ? '<span class="sv-badge-warn">не выбрано: ' + todo + '</span>' : ''), meterTable(s));
      }
      if (s.mode !== 'formula') {
        h += '<button type="button" class="sv-ex-link" data-example>' + svg(CP_ICON.eye) + 'См. пример на странице объекта</button>';
      }
      h += '</div>';
      if (exampleOpen && s.mode !== 'formula') {
        h += '<div class="sv-back" data-ex-close><div class="sv-mw sv-ex" role="dialog" aria-modal="true" aria-label="На странице объекта">' +
          '<div class="sv-mw-head"><b>На странице объекта</b>' + (s.mode === 'receipt' ? '<span class="sv-badge-sample">для примера ' + money(SAMPLE).replace(',00', '') + '</span>' : '') +
          '<button type="button" class="sv-x" data-ex-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
          '<div class="sv-mw-body"><p class="sv-note">' + (s.mode === 'receipt' ? 'Каждый месяц вы вводите сюда сумму из квитанции.' :
            s.mode === 'meters' ? 'Каждый месяц вы вводите сюда показания счётчиков.' : 'Сумма считается сама — вводить ничего не нужно.') + '</p>' + example(s) + '</div></div></div>';
      }
      // The bottom bar repeats the top right corner: «Удалить услугу» on the left, «Сохранить» — the main button.
      h += '<div class="sv-foot">' + (s.id ? '<button type="button" class="subwin-delete" data-delete>Удалить услугу</button>' : '') +
        '<button type="button" class="btn btn-ghost btn-auto sv-cancel" data-modal-close>Отмена</button>' +
        '<button type="button" class="btn btn-primary btn-auto" data-save-next>Сохранить</button></div>';
      if (confirmDelete) {
        h += '<div class="sv-back" data-del-close><div class="sv-mw" role="dialog" aria-modal="true" aria-label="Удалить услугу">' +
          '<div class="sv-mw-head"><b>Удалить услугу?</b><button type="button" class="sv-x" data-del-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
          '<div class="sv-mw-body"><p class="sv-note">«' + esc(s.name) + '» больше не будет в счетах; её суммы и тарифы удалятся. Счётчики объекта и их показания останутся.</p></div>' +
          '<div class="sv-mw-foot"><button type="button" class="btn btn-ghost btn-auto" data-del-close>Отмена</button>' +
          '<button type="button" class="btn btn-danger btn-auto" data-del-yes>Удалить</button></div></div></div>';
      }
      if (asking && askJump) {
        h += '<div class="sv-back" data-ask-close><div class="sv-mw" role="dialog" aria-modal="true" aria-label="Перейти в услугу">' +
          '<div class="sv-mw-head"><b>Перейти в «' + esc(askJump) + '»?</b><button type="button" class="sv-x" data-ask-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
          '<div class="sv-mw-body"><p class="sv-note">Новая услуга «' + esc(s.name || 'Новая услуга') + '» не сохранится.</p></div>' +
          '<div class="sv-mw-foot"><button type="button" class="btn btn-ghost btn-auto" data-ask-close>Остаться</button>' +
          '<button type="button" class="btn btn-primary btn-auto" data-ask-drop>Перейти</button></div></div></div>';
      } else if (asking) {
        h += '<div class="sv-back" data-ask-close><div class="sv-mw" role="dialog" aria-modal="true" aria-label="Сохранить изменения?">' +
          '<div class="sv-mw-head"><b>Сохранить изменения?</b><button type="button" class="sv-x" data-ask-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
          '<div class="sv-mw-body"><p class="sv-note">В «' + esc(s.name || 'Новая услуга') + '» есть несохранённые изменения.</p></div>' +
          // «Не сохранять» on the left; «Отмена» — stay on this service, «Сохранить» — the main one
          '<div class="sv-mw-foot"><button type="button" class="btn btn-ghost btn-auto sv-ask-drop" data-ask-drop>Не сохранять</button>' +
          '<button type="button" class="btn btn-ghost btn-auto" data-ask-close>Отмена</button>' +
          '<button type="button" class="btn btn-primary btn-auto" data-ask-save>Сохранить</button></div></div></div>';
      }
      if (meterOpen != null) h += meterWindow();
      pane.innerHTML = h;
      // «Кто платит» near the bottom bar: the menu opens upwards
      var menu = pane.querySelector('.sv-payer-menu'), foot = pane.querySelector('.sv-foot');
      if (menu && foot && menu.getBoundingClientRect().bottom > foot.getBoundingClientRect().top - 8) menu.classList.add('is-up');
    }
    function render() { renderNav(); renderPane(); }

    // ---------- saving ----------
    var saving = false, closed = false, afterSave = null;
    // «Сохранить»: send now (or wait for the save on its way), then go on.
    function saveThen(next) {
      var s = current, need = !String(s.name || '').trim() ? 'name' : !String(s.provider || '').trim() ? 'provider' : null;
      if (need) {
        editing = true; renderPane();
        status(need === 'name' ? 'Введите название услуги' : 'Введите поставщика', 'is-error');
        pane.querySelector('[data-f="' + need + '"]').focus();
        return;
      }
      if (s.mode === 'meters') {
        if (!s.group) { status('Выберите, что считаем', 'is-error'); return; }
        var todo = s.meters.map(function (id) { return byId(S.meters, id); }).filter(function (m) { return m.who === '' || m.who == null; })[0];
        if (todo) { status('Выберите, кто платит по № ' + (todo.serial || '—'), 'is-error'); return; }
      }
      if (s.mode === 'formula' && !s.formula) { status('Соберите формулу', 'is-error'); return; }
      afterSave = next;
      save();
    }
    function removeCurrent() {
      var gone = current;
      fetch(gone.delete_url, { method: 'POST', credentials: 'same-origin', headers: { 'X-Modal': '1', 'X-CSRFToken': csrf } })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          dirty = true;
          S.services = S.services.filter(function (s) { return s.id !== gone.id; });
          S.meters.forEach(function (m) { if (m.service === gone.id) { m.service = null; m.service_name = ''; } });
          nextNew();
        })
        .catch(function () { confirmDelete = false; renderPane(); status('Не удалось удалить', 'is-error'); });
    }
    function done() { if (closed && !saving && dirty) window.location.reload(); }
    function status(text, cls) {
      var el = pane.querySelector('[data-saved]');
      if (!el) return;
      el.textContent = text;
      el.className = 'sv-saved' + (cls ? ' ' + cls : '');
    }
    function payload() {
      var s = current;
      var data = { id: s.id, kind: s.kind, name: s.name, provider: s.provider, mode: s.mode, split: s.split,
                   excluded: s.excluded, owner_takes: s.owner_takes, fixed: s.fixed, rate: s.rate, unit: s.unit,
                   volume: s.mode === 'area' ? volume(s) : null };
      if (s.mode === 'meters') {
        data.group = s.group;
        data.meters = s.meters.map(function (id) {
          var m = byId(S.meters, id);
          return { id: m.id, who: m.who, input: m.input, split: m.split, excluded: m.excluded, owner_takes: m.owner_takes };
        });
      }
      if (s.mode === 'formula') data.formula = s.fx_data || null;  // null — the stored formula stays as it is
      return data;
    }
    function save() {
      if (!current || saving) return;
      saving = true;
      status('Сохраняем…');
      var sent = current;
      fetch(S.urls.save, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify(payload())
      }).then(function (response) {
        return response.json().then(function (json) { return { ok: response.ok, json: json }; });
      }).then(function (answer) {
        saving = false;
        if (!answer.ok) { afterSave = null; status(answer.json.error || 'Не сохранено', 'is-error'); done(); return; }
        dirty = true; changed = false;
        var fresh = answer.json;
        S.services = fresh.services;
        S.own_units = fresh.own_units;
        S.fx_new = fresh.fx_new;  // a new formula sees the meters this save connected (or let go)
        // The meters: who uses which (the window keeps its own choices of who pays).
        S.meters = fresh.meters; S.groups = fresh.groups; snap = copy(S.meters);
        if (sent.isNew) { sent.id = fresh.selected; sent.isNew = false; }
        var saved = byId(S.services, sent.id);
        if (saved) {
          sent.kind = saved.kind; sent.delete_url = saved.delete_url;
          // the formula as the server keeps it now (numbers with their ids, who pays by each meter)
          sent.fx = saved.fx; sent.formula = saved.formula; sent.fx_each = saved.fx_each; sent.split = saved.split; delete sent.fx_data;
        }
        renderNav();
        if (current === sent && !pane.querySelector('[data-f]:focus')) renderPane();
        status('Сохранено ✓', 'is-on');
        clearTimeout(status.t);
        status.t = setTimeout(function () { status('Сохранено'); }, 1500);
        done();
        if (afterSave) { var next = afterSave; afterSave = null; next(); }
      }).catch(function () { saving = false; afterSave = null; status('Нет связи — не сохранено', 'is-error'); done(); });
    }

    // ---------- clicks ----------
    box.addEventListener('click', function (e) {
      var t;
      // Off to the object window: keep what is typed here; the window opened again picks it up (see «the start»).
      if (e.target.closest('[data-svc-return]')) {
        window.rentflowServiceDraft = { property: S.property.id, current: copy(current), meters: copy(S.meters), changed: changed };
        return;
      }
      // «Сохранить изменения?» — before leaving a service with changes not saved
      if (asking) {
        if (e.target.closest('[data-ask-save]')) { var go = asking; asking = null; saveThen(go); return; }
        if (e.target.closest('[data-ask-drop]')) { var drop = asking; asking = null; S.meters = copy(snap); changed = false; drop(); return; }
        if ((t = e.target.closest('[data-ask-close]')) && (e.target === t || t.tagName === 'BUTTON')) { asking = null; renderPane(); }
        return;
      }
      if ((t = e.target.closest('[data-svc]'))) {
        var id = +t.dataset.svc, jump = t.classList.contains('sv-busy-link') ? byId(S.services, id).name : null;
        leave(function () {
          current = copy(byId(S.services, id)); changed = false; snap = copy(S.meters);
          editing = false; unitOpen = false; exampleOpen = false; meterOpen = null; pickOpen = null;
          render(); pane.scrollTop = 0;
        }, jump);
        return;
      }
      if ((t = e.target.closest('[data-mode]'))) {
        var mode = t.dataset.mode;
        var start = function () {
          startNew(mode);
          editing = true; exampleOpen = false; meterOpen = null; pickOpen = null;
          render(); pane.scrollTop = 0;
          var input = pane.querySelector('[data-f="name"]'); if (input) input.focus();
        };
        if (current && current.isNew) {
          // a new one not saved yet: only the way of charging changes; the name and the supplier stay
          var keep = { name: current.autoName ? '' : current.name, provider: current.provider };
          S.meters = copy(snap); startNew(mode); current.name = keep.name; current.provider = keep.provider;
          changed = !!(keep.name || keep.provider);
          editing = true; exampleOpen = false; meterOpen = null; pickOpen = null;
          render(); pane.scrollTop = 0;
        } else leave(start);
        return;
      }
      if (!current) return;
      // «Удалить услугу» — asked in a small window right here; after it — a new service «По квитанции»
      if (confirmDelete) {
        if (e.target.closest('[data-del-yes]')) { removeCurrent(); return; }
        if ((t = e.target.closest('[data-del-close]')) && (e.target === t || t.tagName === 'BUTTON')) { confirmDelete = false; renderPane(); }
        return;
      }
      if (e.target.closest('[data-delete]')) { confirmDelete = true; return renderPane(); }
      if (e.target.closest('[data-save-next]')) { saveThen(nextNew); return; }
      // the meter's window
      if (meterOpen != null) {
        if (e.target.closest('[data-meter-done]')) {
          var m = byId(S.meters, meterOpen);
          m.split = draft.split; m.excluded = draft.excluded; m.owner_takes = draft.owner_takes;
          if (draft.makeCommon) m.who = 'common';
          meterOpen = null; renderPane(); mark(); return;
        }
        if ((t = e.target.closest('[data-meter-close]')) && (e.target === t || t.tagName === 'BUTTON')) { meterOpen = null; return renderPane(); }
        if ((t = e.target.closest('[data-msplit]'))) { draft.split = t.dataset.msplit; return renderPane(); }
        if ((t = e.target.closest('[data-mpay]'))) { toggle(draft.excluded, +t.dataset.mpay); return renderPane(); }
        if (e.target.closest('[data-mowner]')) { draft.owner_takes = draft.owner_takes === false; return renderPane(); }
        return;
      }
      if (exampleOpen) {
        if ((t = e.target.closest('[data-ex-close]')) && (e.target === t || t.tagName === 'BUTTON')) { exampleOpen = false; renderPane(); }
        return;
      }
      if (e.target.closest('[data-example]')) { exampleOpen = true; return renderPane(); }
      if (e.target.closest('[data-fx-open]')) { openFormula(); return; }
      if (e.target.closest('[data-edit]')) { editing = !editing; renderPane(); if (editing) pane.querySelector('[data-f="name"]').focus(); return; }
      if (e.target.closest('[data-unit-open]')) { unitOpen = !unitOpen; return renderPane(); }
      if ((t = e.target.closest('[data-unit-del]'))) {
        var d = t.dataset.unitDel;
        addedUnits = addedUnits.filter(function (u) { return u !== d; });
        return renderPane();
      }
      if (e.target.closest('[data-unit-add]')) return addUnit();
      if ((t = e.target.closest('[data-unit]'))) {
        unitOpen = false;
        if (t.dataset.unit !== current.unit) { current.unit = t.dataset.unit; current.volume = null; }
        renderPane(); mark();
        var vol = pane.querySelector('[data-f="volume"]'); if (vol) vol.focus();
        return;
      }
      if (unitOpen && !e.target.closest('.sv-sel-menu')) { unitOpen = false; renderPane(); }
      if ((t = e.target.closest('[data-split]'))) { current.split = t.dataset.split; renderPane(); return mark(); }
      if (e.target.closest('[data-owner]')) { current.owner_takes = current.owner_takes === false; renderPane(); return mark(); }
      if ((t = e.target.closest('[data-pay]'))) { toggle(current.excluded, +t.dataset.pay); renderPane(); return mark(); }
      if ((t = e.target.closest('[data-group]'))) { S.meters = copy(snap); pickGroup(t.dataset.group); pickOpen = null; renderPane(); return mark(); }
      if ((t = e.target.closest('[data-who-edit]'))) { pickOpen = null; openMeter(+t.dataset.whoEdit); draft.makeCommon = true; return renderPane(); }
      if ((t = e.target.closest('[data-who-set]'))) {
        var p = t.dataset.whoSet.split(':'), mm = byId(S.meters, +p[0]);
        mm.who = /^[0-9]+$/.test(p[1]) ? +p[1] : p[1];
        if (mm.who === 'common' && !mm.split) mm.split = 'shares';
        pickOpen = null; renderPane(); return mark();
      }
      if ((t = e.target.closest('[data-pick]'))) { pickOpen = pickOpen === +t.dataset.pick ? null : +t.dataset.pick; return renderPane(); }
      if (pickOpen != null) { pickOpen = null; renderPane(); }
      if ((t = e.target.closest('[data-input]'))) {
        var q = t.dataset.input.split(':'); byId(S.meters, +q[0]).input = q[1]; renderPane(); return mark();
      }
      if ((t = e.target.closest('[data-meter]'))) { openMeter(+t.dataset.meter); }
    });
    function toggle(list, id) { var i = list.indexOf(id); if (i < 0) list.push(id); else list.splice(i, 1); }
    function openMeter(id) {
      var m = byId(S.meters, id);
      meterOpen = id;
      draft = { who: m.who, split: m.split || 'shares', excluded: m.excluded.slice(), owner_takes: m.owner_takes };
      renderPane();
    }
    function addUnit() {
      var u = unitNew.trim();
      if (!u) return;
      if (S.units.indexOf(u) < 0 && S.own_units.indexOf(u) < 0 && addedUnits.indexOf(u) < 0) addedUnits.push(u);
      current.unit = u; current.volume = null; unitNew = ''; unitOpen = false;
      renderPane(); mark();
      var vol = pane.querySelector('[data-f="volume"]'); if (vol) vol.focus();
    }

    // ---------- typing: recounted as it is typed; the focus, the text and the caret come back ----------
    var NUMS = { fixed: 1, rate: 1, volume: 1 };
    box.addEventListener('input', function (e) {
      var f = e.target.dataset.f;
      if (!f || !current) return;
      var v = e.target.value, pos = e.target.selectionStart;
      if (f === 'unitNew') unitNew = v;
      else current[f] = NUMS[f] ? parse(v) : v;
      if (f === 'name') current.autoName = false;
      if (f !== 'unitNew') changed = true;
      renderPane();
      var el = pane.querySelector('[data-f="' + f + '"]');
      if (el) { el.value = v; el.focus(); try { el.setSelectionRange(pos, pos); } catch (x) { /* number inputs */ } }
    });
    box.addEventListener('change', function (e) {
      var f = e.target.dataset.f;
      if (NUMS[f] && current && current[f] != null && e.target.value !== '') e.target.value = num(current[f]);  // 1470.7 → 1 470,7
    });
    box.addEventListener('keydown', function (e) {
      if (e.target.dataset && e.target.dataset.f === 'unitNew') {
        if (e.key === 'Enter') { e.preventDefault(); addUnit(); }
        if (e.key === 'Escape') { e.stopPropagation(); unitOpen = false; unitNew = ''; renderPane(); }
        return;
      }
      if (e.key === 'Escape' && (meterOpen != null || exampleOpen || unitOpen || confirmDelete || asking || pickOpen != null)) {
        e.stopPropagation(); meterOpen = null; exampleOpen = false; unitOpen = false; confirmDelete = false; asking = null; pickOpen = null; renderPane(); return;
      }
      if (e.key === 'Enter' && e.target.dataset && e.target.dataset.f) {
        // Enter — the next field (as everywhere), the last one just leaves.
        e.preventDefault();
        var fields = Array.prototype.slice.call(pane.querySelectorAll('[data-f]'));
        var next = fields[fields.indexOf(e.target) + 1];
        if (next) next.focus(); else e.target.blur();
      }
    });
    // Closed with changes: the page under it shows them (the object page, the lists).
    var dialog = box.closest('dialog');
    if (dialog) {
      dialog.addEventListener('close', function onClose() {
        dialog.removeEventListener('close', onClose);
        closed = true;
        if (!saving && dirty) window.location.reload();
      });
    }

    // ---------- the start ----------
    var draftBack = window.rentflowServiceDraft;
    window.rentflowServiceDraft = null;
    if (draftBack && draftBack.property === S.property.id) {
      // Back from the object window: the service as it was typed, the meters' choices kept, new meters added.
      var fresh = {};
      S.meters.forEach(function (m) { fresh[m.id] = m; });
      draftBack.meters.forEach(function (m) {
        var f = fresh[m.id];
        if (f) { f.who = m.who; f.input = m.input; f.split = m.split; f.excluded = m.excluded; f.owner_takes = m.owner_takes; }
      });
      current = draftBack.current; changed = draftBack.changed; editing = !!current.isNew;
      if (current.mode === 'meters' && current.group && groupOf(current.group)) {
        var added = groupOf(current.group).meters.filter(function (id) { return current.meters.indexOf(id) < 0; });
        added.forEach(function (id) { var m = byId(S.meters, id); if (!m.service) { m.who = T.length ? '' : 'owner'; m.input = 'readings'; } });
        current.meters = groupOf(current.group).meters.slice();
        if (added.length) changed = true;
      }
    } else if (S.start && S.start.mode) startNew(S.start.mode);
    else if (S.start && S.start.meter) startNew('meters');
    else if (S.selected && byId(S.services, S.selected)) current = copy(byId(S.services, S.selected));
    else startNew('receipt');  // opened without a service (2026-11-19): a new one «По квитанции», ready for its name
    render();
    if (editing) { var first = pane.querySelector('[data-f="name"]'); if (first) first.focus(); }
  };
})();
