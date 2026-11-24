/* «Своя формула» — its own window over the service window (2026-11-16), as in the approved mockup
   docs/mockups/2026-11-16-formula-blocks.html (round 25).

   The service window (services.js, 2026-11-20) opens it: window.rentflowFormula.open({ctx, state, …}) — ctx is the
   server's formula_context (the object's tenants, meters with last month's usage, the numbers and the blocks), state —
   what «Готово» gave last time, not saved yet. «Готово» hands the formula back (publish + close(true)), «Отмена»
   leaves it as it was. The server counts the bills itself (apps/billing/formula.py) — the check here is only a preview
   on last month's numbers.

   Window v2 (2026-11-21, docs/mockups/2026-11-21-formula-blocks-v2.html): four blocks of one size — «Число за месяц»,
   «Постоянное число» (one menu of units), «Выбрать счётчики» (every meter of the object with a tick), signs. Each meter is
   a block of its own; several go in as «( А + Б )». Who pays follows from the meters: one tenant's — his only; several
   tenants' — each by his own (another's meter is 0 for him); common ones — one sum, split by «Делим». Common and
   tenants' meters together are refused. Older blocks of several meters («у каждого свой» / «Σ складываем») still work. */
(function () {
  'use strict';

  var SAMPLES = { '₽': 6400, 'кВт·ч': 270, 'м³': 5, 'Гкал': 0.42, 'м²': 60, 'чел.': 3 };
  // A meter without readings (2026-11-25): each meter its own sample usage, by its place among the object's meters —
  // «5 м³ + 5 м³» everywhere looked fake.
  var METER_SAMPLES = { 'м³': [3, 2, 5, 4], 'кВт·ч': [270, 180, 320, 240], 'Гкал': [0.42, 0.31, 0.55, 0.38] };
  var SHORT = { electricity: 'Электричество', water: 'Вода хол.', hot_water: 'Вода гор.' };
  var KEYS = { '+': '+', '-': '−', '*': '×', '/': '÷', '(': '(', ')': ')' };
  function svg(d, filled) {
    return '<svg viewBox="0 0 24 24" width="16" height="16" fill="' + (filled ? 'currentColor' : 'none') +
      '" stroke="' + (filled ? 'none' : 'currentColor') + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  }
  var ICONS = {
    month: svg('<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>'),
    const: svg('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    tag: svg('<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.5"/>'),
    gauge: svg('<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/>'),
    people: svg('<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5M16 5a3 3 0 0 1 0 6M18 15c2 .5 3 2.5 3 5"/>'),
    electricity: svg('<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/>', true),
    water: svg('<path d="M12 2.5c-.3 0-.6.2-.8.4C9.4 5.3 5.5 10.4 5.5 14.5a6.5 6.5 0 0 0 13 0c0-4.1-3.9-9.2-5.7-11.6-.2-.2-.5-.4-.8-.4z"/>', true),
    heating: svg('<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 6v12M12 6v12M16 6v12M6 18v3M18 18v3"/>'),
    gas: svg('<path d="M12 2s5 4.6 5 10a5 5 0 0 1-10 0c0-2.4 1.3-4.3 2.3-5.4.2 1.6 1 2.6 1.9 2.6C12.6 9.2 11 5.9 12 2z"/>', true),
    custom: svg('<circle cx="12" cy="13" r="8"/><path d="M12 13l4-4M12 5V3"/>'),
  };
  ICONS.hot_water = ICONS.water;
  ICONS.const = ICONS.tag;
  var CHEV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';

  function fmt(n, d) {
    return Number(n).toLocaleString('ru-RU', { maximumFractionDigits: d === undefined ? 4 : d, minimumFractionDigits: d === undefined ? 0 : d });
  }
  function esc(text) { return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
  function sampleFor(unit) { return SAMPLES[unit] || 10; }
  // «-», «—» typed as an own unit mean «no unit» (a coefficient): not a unit of its own.
  function cleanUnit(text) { var t = String(text || '').trim(); return /^[-–—_.\s]*$/.test(t) ? '' : t; }
  function toNumber(text) { var n = Number(String(text).replace(/[\s ]/g, '').replace(',', '.')); return isFinite(n) ? n : 0; }

  // ---------- Arithmetic with units: 45 ₽/м³ → { '₽': 1, 'м³': -1 } ----------
  function unitsOf(unit, per) { var u = {}; if (unit) u[unit] = 1; if (per) { u[per] = (u[per] || 0) - 1; if (!u[per]) delete u[per]; } return u; }
  function combine(a, b, sign) {
    var u = Object.assign({}, a);
    Object.keys(b).forEach(function (k) { u[k] = (u[k] || 0) + sign * b[k]; if (!u[k]) delete u[k]; });
    return u;
  }
  function sameUnits(a, b) {
    var ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every(function (k) { return a[k] === b[k]; });
  }
  function unitText(u) {
    var up = Object.keys(u).filter(function (k) { return u[k] > 0; }), down = Object.keys(u).filter(function (k) { return u[k] < 0; });
    if (!up.length && !down.length) return 'число';
    return (up.join('·') || '1') + (down.length ? '/' + down.join('·') : '');
  }
  function rub(v, sym) { return fmt(Math.round(v * 100) / 100, 2) + ' ' + sym; }

  // The context of the server (formula_context) with what the window gave last time ({numbers, blocks, owners}) over it:
  // a formula changed by «Готово» but not saved yet opens as it was left.
  function withState(ctx, state) {
    if (!state) return ctx;
    var last = {};
    ctx.numbers.forEach(function (n) { last[n.id] = n.last; });
    var owners = state.owners || {};
    return Object.assign({}, ctx, {
      numbers: (state.numbers || []).map(function (n) { return Object.assign({}, n, { id: String(n.id), last: last[n.id] === undefined ? null : last[n.id] }); }),
      blocks: state.blocks || [],
      meters: ctx.meters.map(function (m) {
        if (!(m.id in owners)) return m;
        var o = owners[m.id];
        return Object.assign({}, m, { tenant: o && o !== 'free' ? Number(o) : null, vacant: o === 'free' });
      }),
    });
  }

  /* The formula window over a service window. opts:
     ctx, state — what to draw (formula_context of the server, and the window's last «Готово» over it);
     host — where the window goes (the service window's <dialog>);
     split() — how the sum is divided now; canPay(id), isOff(id), togglePay(id) — the «платит» switch of a tenant;
     publish(data, summary, each) — the formula as it is now: data for the server, the words, each by his own meters;
     close(keep) — the window closed by «Готово» (keep) or «Отмена». */
  function setup(opts) {
    var host = opts.host || document.body;
    // Inline (2026-11-24, docs/mockups/2026-11-24-formula-in-body.html, вариант А): the editor is drawn right in the service
    // window's body — no window of its own, no «Готово»: every change goes to the service at once (publish), it is saved
    // by the service's own «Сохранить». «Как посчитается» goes into opts.checkEl (the service's own section).
    var inline = !!opts.inline;
    var ctx = withState(opts.ctx, opts.state);
    var TENANTS = ctx.tenants, METERS = ctx.meters, KINDS = ctx.kinds, SYM = ctx.symbol || '₽';
    var LIBRARY = ctx.library || [];  // the numbers of the account's other services («Или готовое»)
    var uid = 0, nid = 0;

    var values = ctx.numbers.map(function (n) {
      return { id: String(n.id), type: n.monthly ? 'month' : 'const', label: n.label, unit: cleanUnit(n.unit), per: cleanUnit(n.per),
        value: n.value === null || n.value === undefined ? 0 : n.value,
        sample: n.last === null || n.last === undefined ? sampleFor(n.unit) : n.last, real: n.last !== null && n.last !== undefined };
    });
    // a new number gets an id after the ones there are (the editor is drawn again from what it published)
    values.forEach(function (v) { var n = /^n(\d+)$/.exec(v.id); if (n) nid = Math.max(nid, Number(n[1])); });
    var owners = {};
    METERS.forEach(function (m) { owners[m.id] = m.tenant ? String(m.tenant) : (m.vacant ? 'free' : ''); });
    var blocks = (ctx.blocks || []).map(function (b) {
      if (b.t === 'op') return { id: ++uid, type: 'op', op: b.op };
      if (b.t === 'num') return valueById(String(b.id)) ? { id: ++uid, type: 'val', vid: String(b.id) } : null;
      if (b.t === 'meter') return { id: ++uid, type: 'meter', key: b.key, meters: (b.meters || []).filter(meterById), join: b.join === 'sum' ? 'sum' : 'each' };
      return null;
    }).filter(Boolean);

    function valueById(id) { return values.find(function (v) { return v.id === id; }); }
    function valueOf(b) { return valueById(b.vid); }
    function meterById(id) { return METERS.find(function (m) { return m.id === id; }); }
    function kindOf(key) { return KINDS.find(function (k) { return k.key === key; }) || { key: key, name: key, unit: '', icon: 'custom' }; }
    function shortOf(key) { return SHORT[key] || kindOf(key).name; }
    function tenantById(id) { return TENANTS.find(function (t) { return t.id === id; }); }
    // Whose a meter is now (as the window has it): a tenant id, or null — common or the owner's.
    function tenantOf(meterId) { var o = owners[meterId]; return o && o !== 'free' ? Number(o) : null; }
    function firstName(name) { return String(name).split(' ')[0]; }
    function whoShort(meterId) {
      var t = tenantById(tenantOf(meterId));
      if (t) return firstName(t.name);
      return owners[meterId] === 'free' ? 'собственник' : 'общий';
    }
    function whoLabel(meterId) {
      var t = tenantById(tenantOf(meterId));
      if (t) return t.name;
      return owners[meterId] === 'free' ? 'Собственник' : 'Общий';
    }
    // One meter — one field: only a meter whose readings are typed in some service can go in the formula.
    function isActive(m) { return !!(m && m.typed && m.typed.length); }
    function meterName(m) { return m.name + (m.serial ? ' № ' + m.serial : ''); }
    function offText(m) {
      return 'Счётчик «' + meterName(m) + '» пока не подключён ни к одной услуге — его показания негде вводить. ' +
        'Подключите его в услуге «По счётчикам», и тогда его можно будет взять в формулу.';
    }
    // A short window with the explanation and «Понятно».
    function openNote(anchor, title, text) {
      closePop();
      pop = document.createElement('div'); pop.className = 'fx-pop';
      pop.innerHTML = '<h4>' + esc(title) + '</h4><p class="fx-example">' + esc(text) + '</p>' +
        '<div class="fx-acts"><button type="button" class="fx-btn is-primary" data-ok>Понятно</button></div>';
      overlay.appendChild(pop);
      placePop(anchor);
      pop.querySelector('[data-ok]').onclick = closePop;
      pop.querySelector('[data-ok]').focus();
    }
    function usageOf(meterId) {
      var m = meterById(meterId);
      if (m && m.last !== null && m.last !== undefined) return m.last;
      var unit = kindOf(m ? m.key : '').unit, list = METER_SAMPLES[unit];
      return list && m ? list[METERS.indexOf(m) % list.length] : sampleFor(unit);
    }
    function usageIsSample(meterId) { var m = meterById(meterId); return !m || m.last === null || m.last === undefined; }
    function payBox(tenantId) { return opts.canPay(Number(tenantId)); }
    function isOff(tenantId) { return payBox(tenantId) ? opts.isOff(Number(tenantId)) : false; }
    function splitNow() { return opts.split() || 'shares'; }

    function make(kind) {
      var id = ++uid;
      if (kind.indexOf('val:') === 0) return { id: id, type: 'val', vid: kind.slice(4) };
      if (kind.indexOf('meter:') === 0) {
        var key = kind.slice(6);
        return { id: id, type: 'meter', key: key, meters: METERS.filter(function (m) { return m.key === key && isActive(m); }).map(function (m) { return m.id; }), join: 'each' };
      }
      if (kind.indexOf('op:') === 0) return { id: id, type: 'op', op: kind.slice(3) };
    }
    function newValue(type, props) {
      var v = Object.assign({ id: 'n' + (++nid), type: type, label: '', unit: '', per: '', value: 0, sample: 0, real: false }, props || {});
      if (!v.label) v.label = 'Число ' + (values.length + 1);
      values.push(v);
      return v;
    }
    function unitLabel(v) { return (v.unit || '') + (v.per ? (v.unit ? ' за ' : 'за ') + v.per : ''); }

    // The tenants whose meters stand in the formula — alone or in a «Σ» block (a short way to write «сч1 + сч2 + сч3»);
    // a «весь объект» block (the examples' whole usage) is one number for all and counts none.
    function tenantsIn() {
      var found = [];
      blocks.forEach(function (b) {
        if (b.type !== 'meter' || b.join === 'sum') return;
        b.meters.forEach(function (id) { var t = tenantOf(id); if (t !== null && found.indexOf(t) < 0) found.push(t); });
      });
      return TENANTS.map(function (t) { return t.id; }).filter(function (id) { return found.indexOf(id) >= 0; });
    }
    function modeNow() { return TENANTS.length && tenantsIn().length ? 'each' : 'total'; }
    function meterCount(n) {
      return n + ' ' + (n % 10 === 1 && n % 100 !== 11 ? 'счётчик' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'счётчика' : 'счётчиков');
    }

    // ---------- The DOM of the window ----------
    var overlay = document.createElement('div');
    var PALETTE = '<div class="fx-palette">' +
      '<div class="fx-group"><h3>Каждый месяц</h3><div data-pal="month"></div></div>' +
      '<div class="fx-group"><h3>Тариф · норматив</h3><div data-pal="const"></div></div>' +
      '<div class="fx-group"><h3>Расход счётчиков</h3><div data-pal="meter"></div></div>' +
      '<div class="fx-group"><h3>Знаки</h3><div class="fx-signs">' +
      ['+', '−', '×', '÷', '(', ')'].map(function (s) { return '<span class="fx-chip k-op" data-new="op:' + s + '">' + s + '</span>'; }).join('') +
      '</div></div></div>';
    if (inline) {
      // the grey panel (as with every way of charging) — a word and the examples, no button; the palette; the line;
      // in the line's corner × clears it. The palette is always open (2026-11-25: folding it — no).
      overlay.className = 'fx-inline fx-preview';
      overlay.setAttribute('data-fx-inline', '');
      // The grey panel with the examples — a saved formula too (2026-11-25, the user: «верни»).
      overlay.innerHTML = '<div class="sv-cp fx-gpanel fx-examples">' + svg('<path d="M10 4c-2 0-2 2-2 4v8c0 2 0 4-2 4M5 10h6M14 10l6 8M20 10l-6 8"/>') +
        '<span class="fx-lead">Соберите из блоков ниже или начните с примера:</span>' +
        '<button type="button" data-example="sewage">Водоотведение</button>' +
        '<button type="button" data-example="one">Только арендатору 1</button></div>' + PALETTE +
        '<div class="fx-strip-wrap"><div class="fx-strip" data-strip></div>' +
        '<button class="fx-clear" type="button" data-clear title="Очистить формулу" aria-label="Очистить формулу">×</button></div>' +
        '<p class="fx-trash-hint">Нажмите на блок или перетащите его в строку · вытащите из строки — уберётся</p>';
    } else {
    overlay.className = 'fx-overlay';
    overlay.hidden = true;
    overlay.innerHTML =
      '<div class="fx-modal" role="dialog" aria-label="Своя формула">' +
      '<div class="fx-head"><h2>Своя формула</h2><button type="button" class="fx-x" data-x title="Закрыть без изменений" aria-label="Закрыть">×</button></div>' +
      '<p class="fx-desc">Соберите расчёт из четырёх блоков. Внизу сразу видно, сколько выйдет у каждого арендатора.</p>' +
      '<div class="fx-examples">Примеры:' +
      '<button type="button" data-example="sewage">Водоотведение</button>' +
      '<button type="button" data-example="one">Только арендатору 1</button></div>' +
      // Four blocks of one size (2026-11-21, window v2): a click opens a small window — pick a ready one or make a new one.
      '<div class="fx-palette">' +
      '<div class="fx-group"><h3>Каждый месяц</h3><div data-pal="month"></div></div>' +
      '<div class="fx-group"><h3>Тариф · норматив</h3><div data-pal="const"></div></div>' +
      '<div class="fx-group"><h3>Расход счётчиков</h3><div data-pal="meter"></div></div>' +
      '<div class="fx-group"><h3>Знаки</h3><div class="fx-signs">' +
      ['+', '−', '×', '÷', '(', ')'].map(function (s) { return '<span class="fx-chip k-op" data-new="op:' + s + '">' + s + '</span>'; }).join('') +
      '</div></div></div>' +
      '<div class="fx-strip-wrap"><div class="fx-strip" data-strip></div>' +
      '<button class="fx-clear" type="button" data-clear title="Очистить формулу" aria-label="Очистить формулу">×</button></div>' +
      '<p class="fx-trash-hint">Перетащите блок в строку или нажмите на него · вытащите из строки, чтобы убрать · нажмите на блок в строке, чтобы настроить</p>' +
      '<div class="fx-check-box"><h3>Как посчитается <span class="fx-badge" data-check-badge>на числах прошлого месяца</span> <span class="fx-badge" data-state-badge></span></h3>' +
      '<div class="fx-check" data-check></div></div>' +
      '<div class="fx-acts"><button class="fx-btn" type="button" data-cancel>Отмена</button><button class="fx-btn is-primary" type="button" data-done>Готово</button></div>' +
      '</div>';
    }
    host.appendChild(overlay);
    // Things drawn «fixed» (small windows, menus, a dragged block) inside the service window's body: that body is a
    // container (container-type), so «fixed» counts from it, not from the screen — the shift is measured and taken off.
    function origin(el) {
      el.style.left = '0px'; el.style.top = '0px';
      var r = el.getBoundingClientRect();
      return { x: r.left, y: r.top };
    }
    function placeAt(el, x, y) { var o = origin(el); el.style.left = (x - o.x) + 'px'; el.style.top = (y - o.y) + 'px'; }
    var strip = overlay.querySelector('[data-strip]');

    // A meter of its own (window v2): «Вода хол. № 545575».
    function oneName(b) { var m = meterById(b.meters[0]); return shortOf(b.key) + (m && m.serial ? ' № ' + m.serial : ''); }
    function chipText(b) {
      if (b.type === 'op') return b.op;
      if (b.type === 'meter') {
        var short = shortOf(b.key);
        if (!b.meters.length) return short + ' · ?';
        if (b.meters.length === 1) return oneName(b);
        return 'Σ ' + short + (b.join === 'sum' ? ' · весь объект' : '');
      }
      return valueOf(b).label;
    }
    function chipValue(b) {
      if (b.type === 'meter') return kindOf(b.key).unit;
      if (b.type !== 'val') return '';
      var v = valueOf(b);
      if (v.type === 'const') return fmt(v.value) + (unitLabel(v) ? ' ' + unitLabel(v) : '');
      return unitLabel(v);
    }
    function iconOf(b) { return b.type === 'meter' ? (ICONS[kindOf(b.key).icon] || ICONS.custom) : ICONS[valueOf(b).type === 'const' ? 'const' : 'month']; }
    function kindClass(b) {
      if (b.type === 'op') return 'k-op';
      if (b.type === 'meter') return 'k-meter mk-' + kindOf(b.key).icon;
      return valueOf(b).type === 'const' ? 'k-const' : 'k-month';
    }
    function chipParts(b) {
      if (b.type === 'meter' && b.meters.length === 1) return [oneName(b), whoShort(b.meters[0]) + ' · ' + kindOf(b.key).unit];
      // «Σ» (2026-11-22): all the meters of one group — a short way to write «сч1 + сч2 + сч3»; a click shows them.
      if (b.type === 'meter') return ['Σ ' + shortOf(b.key), (b.join === 'sum' ? 'весь объект' : meterCount(b.meters.length)) + ' · ' + kindOf(b.key).unit];
      var v = valueOf(b), val = chipValue(b).replace(' за ', '/');
      return [v.label, v.type === 'month' ? (val ? val + ' · каждый месяц' : 'каждый месяц') : (val || 'число')];
    }
    function chipEl(b) {
      var el = document.createElement('span');
      el.className = 'fx-chip ' + kindClass(b);
      el.dataset.id = b.id;
      if (b.type === 'op') { el.textContent = b.op; return el; }
      var parts = chipParts(b);
      el.classList.add('is-fx');
      el.title = parts[0] + (parts[1] ? ' · ' + parts[1] : '');
      el.innerHTML = '<span class="fx-r1"><span class="fx-ico">' + iconOf(b) + '</span><span class="fx-nm"></span></span><span class="fx-s2"></span>';
      el.querySelector('.fx-nm').textContent = parts[0];
      el.querySelector('.fx-s2').textContent = parts[1];
      return el;
    }
    function tileEl(kind, cls, icon, name, sub) {
      var el = document.createElement('span');
      el.className = 'fx-chip is-tile ' + cls;
      el.dataset.new = kind;
      el.title = name + (sub ? ' · ' + sub : '');
      el.innerHTML = '<span class="fx-ico">' + icon + '</span><span class="fx-tl"><span class="fx-t1"></span><span class="fx-t2"></span></span>';
      el.querySelector('.fx-t1').textContent = name;
      el.querySelector('.fx-t2').textContent = sub;
      return el;
    }

    // The palette: always the same four blocks (window v2) — the ready numbers and meters are picked in their small windows.
    function renderPalette() {
      var month = overlay.querySelector('[data-pal="month"]');
      if (!month.firstChild) {
        month.appendChild(tileEl('new:month', 'k-new k-month', ICONS.month, 'Число за месяц', 'из квитанции'));
        overlay.querySelector('[data-pal="const"]').appendChild(tileEl('new:const', 'k-new k-const', ICONS.tag, 'Постоянное число', 'тариф или коэф.'));
        overlay.querySelector('[data-pal="meter"]').appendChild(tileEl('pick:meters', 'k-new k-meter', ICONS.gauge, 'Выбрать счётчики', 'расход за месяц'));
      }
      var meterTile = overlay.querySelector('[data-pal="meter"] .fx-chip');
      var any = METERS.some(isActive);
      meterTile.classList.toggle('is-off', !any);
      meterTile.querySelector('.fx-t2').textContent = METERS.length ? (any ? 'расход за месяц' : 'не подключены к услугам') : 'у объекта нет счётчиков';
    }

    // ---------- Hints right where the problem is (2026-11-22, variant Б of docs/mockups/2026-11-22-formula-hints.html):
    // a block or sign outlined with «!» (its words on hover or click), dashed brackets / sign where one is missing —
    // a click puts it. Cases: «A + B × C» without brackets, two blocks with no sign, a missing «)», a sign out of place.
    function isOp(b, ops) { return b && b.type === 'op' && ops.indexOf(b.op) >= 0; }
    function nameOf(b) { return b.type === 'op' ? b.op : chipParts(b)[0]; }
    function analyze() {
      var marks = {}, fixed = {}, ghosts = [], onGhost = {}, fixes = 0, stack = [], expect = true;
      function ghost(at, op, fix, say) { ghosts.push({ at: at, op: op, fix: fix, say: say }); }
      blocks.forEach(function (b, i) {
        var operand = b.type !== 'op';
        if (operand || isOp(b, ['('])) {
          if (!expect) {
            var f = ++fixes;
            fixed[i] = f;
            marks[i] = 'Между «' + nameOf(blocks[i - 1]) + '» и «' + nameOf(b) + '» нужен знак — нажмите на мигающую плашку и выберите его.';
            // «!» stands on the plaque itself, the block keeps no frame (2026-11-23)
            ghost(i, '?', f, marks[i]);
            onGhost[i] = true;
          }
          if (operand) expect = false; else { stack.push(i); expect = true; }
        } else if (isOp(b, [')'])) {
          if (expect) marks[i] = 'Перед «)» нужен блок — число или счётчик.';
          else if (!stack.length) marks[i] = 'Лишняя скобка «)» — у неё нет пары «(». Уберите её.';
          else stack.pop();
          expect = false;
        } else {
          if (expect) marks[i] = i ? 'Знак «' + b.op + '» не на месте: два знака подряд — уберите один.' : 'Формула не может начинаться со знака «' + b.op + '».';
          expect = true;
        }
      });
      if (blocks.length && expect && !Object.keys(marks).length) {
        marks[blocks.length - 1] = 'Формула обрывается — после знака нужен блок.';
      }
      stack.forEach(function (at) {
        var f = ++fixes;
        ghost(blocks.length, ')', f);
        fixed[at] = f;
        marks[at] = 'У скобки «(» нет пары — нажмите на пунктирную «)» в конце или поставьте её сами.';
      });
      if (!Object.keys(marks).length) precedence(0, blocks.length);
      return { marks: marks, fixed: fixed, ghosts: ghosts, onGhost: onGhost };

      // «A + B × C»: B alone is multiplied — offer brackets around the sum. One level (inside a pair of brackets) at a time.
      function precedence(from, to) {
        var items = [], ops = [], i = from;
        while (i < to) {
          var b = blocks[i];
          if (isOp(b, ['('])) {
            var depth = 1, j = i + 1;
            while (j < to && depth) { if (isOp(blocks[j], ['('])) depth++; else if (isOp(blocks[j], [')'])) depth--; j++; }
            precedence(i + 1, j - 1);
            items.push({ start: i, end: j - 1 });
            i = j;
          } else if (b.type === 'op') { ops.push(b.op); i++; }
          else { items.push({ start: i, end: i }); i++; }
        }
        for (var k = 1; k < ops.length; k++) {
          // Only when the sum is of like things (м³ + м³ × тариф): «Абонплата + Расход × Тариф» is right as it is.
          if ('×÷'.indexOf(ops[k]) >= 0 && '+−'.indexOf(ops[k - 1]) >= 0 && alike(items[k - 1], items[k])) {
            var first = k - 1;
            while (first > 0 && '+−'.indexOf(ops[first - 1]) >= 0) first--;
            var f = ++fixes, who = items[k];
            ghost(items[first].start, '(', f);
            ghost(who.end + 1, ')', f);
            fixed[who.start] = f;
            marks[who.start] = 'Сейчас «' + ops[k] + '» применится только к «' + nameOf(blocks[who.start]) + '». Чтобы сначала ' +
              (ops[k - 1] === '+' ? 'сложить' : 'вычесть') + ', нажмите на пунктирные скобки.';
            return;
          }
        }
      }
    }
    // The units of one item of a level: a block's own; a group in brackets — unknown (null).
    function itemUnits(item) {
      if (item.start !== item.end) return null;
      var b = blocks[item.start];
      if (b.type === 'meter') return unitsOf(kindOf(b.key).unit, '');
      if (b.type === 'val') { var v = valueOf(b); return unitsOf(v.unit, v.per); }
      return null;
    }
    function alike(a, b) { var ua = itemUnits(a), ub = itemUnits(b); return !ua || !ub || sameUnits(ua, ub); }
    // A click on a dashed bracket or sign: put every piece of that fix (both brackets of a pair).
    // sign — what was picked for a «?» (a missing sign is never guessed, 2026-11-22).
    function applyFix(fix, sign) {
      var hint = analyze();
      hint.ghosts.filter(function (g) { return g.fix === fix; }).sort(function (a, b) { return b.at - a.at; })
        .forEach(function (g) { blocks.splice(g.at, 0, make('op:' + (g.op === '?' ? sign : g.op))); });
      render();
    }

    function render() {
      strip.innerHTML = '';
      if (!blocks.length) strip.innerHTML = '<span class="fx-empty">Перетащите сюда блоки — например, Вода гор. + Вода хол. × Тариф</span>';
      var hint = analyze();
      function ghosts(at) {
        hint.ghosts.filter(function (g) { return g.at === at; }).forEach(function (g) {
          var el = document.createElement('span');
          el.className = 'fx-ghost';
          el.dataset.fix = g.fix;
          el.dataset.op = g.op;
          if (g.op === '?') el.innerHTML = '<span>+ −</span><span>× ÷</span>';
          else el.textContent = g.op;
          if (g.op === '?') el.classList.add('is-blank');
          el.title = g.op === '?' ? g.say : 'Поставить «' + g.op + '» сюда';
          if (g.op === '?') el.insertAdjacentHTML('beforeend', '<i class="fx-pin">!</i>');
          strip.appendChild(el);
        });
      }
      blocks.forEach(function (b, i) {
        ghosts(i);
        var el = chipEl(b);
        el.insertAdjacentHTML('beforeend', '<span class="fx-del" title="Убрать из формулы" aria-label="Убрать из формулы"><svg class="icon"><use href="#i-x"/></svg></span>');
        if (hint.marks[i] && !hint.onGhost[i]) {
          el.classList.add('is-mark');
          el.insertAdjacentHTML('beforeend', '<span class="fx-pin" title="' + esc(hint.marks[i]) + '">!</span>');
          el.querySelector('.fx-pin').dataset.say = hint.marks[i];
        }
        strip.appendChild(el);
      });
      ghosts(blocks.length);
      strip.querySelectorAll('.fx-nm, .fx-s2').forEach(function (e) { e.classList.toggle('is-cut', e.scrollWidth > e.clientWidth + 1); });
      renderPalette();
      if (!inline) { renderCheck(); return; }
      if (opts.checkEl) { opts.checkEl.hidden = !blocks.length; if (blocks.length) renderCheck(opts.checkEl); }
      publish();
    }

    // ---------- Counting the preview (the server counts the bills itself) ----------
    function evaluate(tenantId) {
      var i = 0, bare = false;
      function value(b) {
        if (b.type === 'val') {
          var x = valueOf(b), n = x.type === 'const' ? x.value : x.sample;
          if (!x.unit && !x.per) bare = true;
          var text = fmt(n) + (x.unit ? ' ' + x.unit : '') + (x.per ? '/' + x.per : '');
          return { v: n, u: unitsOf(x.unit, x.per), parts: [{ num: text, word: x.label, sample: x.type === 'month' && !x.real }] };
        }
        var k = kindOf(b.key);
        if (!b.meters.length) throw 'У счётчика «' + shortOf(b.key) + '» не отмечен ни один счётчик.';
        var loose = b.meters.map(meterById).filter(function (m) { return !isActive(m); });
        if (loose.length) throw offText(loose[0]);
        var ids = b.meters;
        // Another tenant's meter of its own: 0 in this one's count, and left out of his line.
        if (b.meters.length === 1 && tenantId !== null && tenantOf(b.meters[0]) !== null && tenantOf(b.meters[0]) !== tenantId) {
          return { v: 0, u: unitsOf(k.unit, ''), parts: [{ num: '0', word: chipText(b), foreign: true }] };
        }
        if (b.meters.length > 1 && tenantId !== null && b.join !== 'sum') ids = b.meters.filter(function (id) { return tenantOf(id) === tenantId; });
        if (!ids.length) return { v: 0, u: unitsOf(k.unit, ''), parts: [{ num: '0', word: chipText(b), foreign: true }] };
        var v = ids.reduce(function (s, id) { return s + usageOf(id); }, 0);
        var word = chipText(b);
        if (tenantId !== null && b.meters.length > 1 && b.join !== 'sum') word = shortOf(b.key) + ' · ' + firstName(tenantById(tenantId).name);
        return { v: v, u: unitsOf(k.unit, ''), parts: [{ num: fmt(v) + (k.unit ? ' ' + k.unit : ''), word: word, sample: ids.some(usageIsSample) }] };
      }
      function primary() {
        var b = blocks[i];
        if (!b) throw 'Формула обрывается — добавьте число или счётчик в конце.';
        if (b.type === 'op' && b.op === '(') {
          i++; var r = sum();
          if (!blocks[i] || blocks[i].op !== ')') throw 'Не хватает закрывающей скобки «)».';
          i++; return { v: r.v, u: r.u, parts: [{ op: '(' }].concat(r.parts, [{ op: ')' }]) };
        }
        if (b.type === 'op') throw 'Знак «' + b.op + '» стоит не на месте.';
        i++; return value(b);
      }
      function product() {
        var a = primary();
        while (blocks[i] && blocks[i].type === 'op' && (blocks[i].op === '×' || blocks[i].op === '÷')) {
          var op = blocks[i++].op, b = primary();
          if (op === '÷' && !b.v) throw 'Делим на ноль: ' + b.parts[0].num + '.';
          a = { v: op === '×' ? a.v * b.v : a.v / b.v, u: combine(a.u, b.u, op === '×' ? 1 : -1), parts: a.parts.concat([{ op: op }], b.parts) };
        }
        return a;
      }
      function sum() {
        var a = product();
        while (blocks[i] && blocks[i].type === 'op' && (blocks[i].op === '+' || blocks[i].op === '−')) {
          var op = blocks[i++].op, b = product();
          if (!bare && !sameUnits(a.u, b.u)) throw 'Нельзя ' + (op === '+' ? 'складывать' : 'вычитать') + ' ' + unitText(a.u) + ' и ' + unitText(b.u) + '.';
          a = { v: op === '+' ? a.v + b.v : a.v - b.v, u: a.u, parts: a.parts.concat([{ op: op }], b.parts) };
        }
        return a;
      }
      try {
        if (!blocks.length) return { error: '' };
        var r = sum();
        if (i < blocks.length) throw blocks[i].op === ')' ? 'Лишняя закрывающая скобка «)».' : 'Между блоками не хватает знака.';
        if (bare) r.bare = true;
        else if (!sameUnits(r.u, { '₽': 1 })) return { error: 'В итоге получается ' + unitText(r.u) + ', а нужны рубли.' };
        r.parts = dropForeign(r.parts);
        return r;
      } catch (msg) { return { error: String(msg) }; }
    }

    // «(4 + 0) × 45» → «4 × 45»: another tenant's meter goes with the «+» / «−» next to it; brackets around one value go.
    function dropForeign(parts) {
      var out = parts.slice(), at;
      while ((at = out.findIndex(function (p) { return p.foreign; })) >= 0) {
        if (at > 0 && (out[at - 1].op === '+' || out[at - 1].op === '−')) out.splice(at - 1, 2);
        else if (out[at + 1] && out[at + 1].op === '+') out.splice(at, 2);
        else out[at] = Object.assign({}, out[at], { foreign: false });
      }
      for (var i = 0; i + 2 < out.length; i++) {
        if (out[i].op === '(' && !out[i + 1].op && out[i + 2].op === ')') { out.splice(i + 2, 1); out.splice(i, 1); i = -1; }
      }
      return out;
    }
    // Common meters and tenants' meters in one formula are refused (2026-11-21, as in «По счётчикам»).
    var MIXED = 'Общий счётчик и счётчики арендаторов в одной формуле нельзя — для общего сделайте отдельную услугу.';
    function isMixed(ids) {
      var own = false, common = false;
      ids.forEach(function (id) { if (tenantOf(id) !== null) own = true; else common = true; });
      return own && common && TENANTS.length > 0;
    }
    function formulaMeters() {
      var ids = [];
      blocks.forEach(function (b) { if (b.type === 'meter' && b.join !== 'sum') b.meters.forEach(function (id) { if (ids.indexOf(id) < 0) ids.push(id); }); });
      return ids;
    }

    function renderCheck(root) {
      root = root || overlay;
      var box = root.querySelector('[data-check]');
      var badge = root.querySelector('[data-state-badge]') || document.createElement('span');
      var checkBadge = root.querySelector('[data-check-badge]') || document.createElement('span');
      box.innerHTML = '';
      if (!blocks.length) {
        badge.textContent = ''; badge.className = 'fx-badge';
        box.innerHTML = '<p class="fx-hint">Соберите формулу — здесь появится расчёт для каждого арендатора.</p>';
        return;
      }
      // Variant А (2026-11-21, docs/mockups/2026-11-21-formula-result.html): a card per tenant like the object page's
      // «Счёт» — what goes in (name · number), the formula in numbers, «Итого» big; under the cards «Всего по услуге».
      function partsText(parts) {
        return parts.map(function (x) { return x.op || x.num; }).join(' ').replace(/\( /g, '(').replace(/ \)/g, ')');
      }
      function valueRows(parts) {
        return parts.filter(function (x) { return !x.op; }).map(function (x) { return [x.word, x.num, x.sample]; });
      }
      // 2026-11-22: as the service window's «Делим и кто платит» — a grey panel, a 40px row per tenant (№ in a circle ·
      // name · the formula in numbers, grey · sum · the small switch), then «Остаётся на вас» and «Всего по услуге».
      var cards = document.createElement('div'); cards.className = 'sv-gp fx-gp';
      var no = 0;
      // rows: [[word, number, sample]] — the words go to the hint of the calc; note — a sentence instead (bad — an error).
      function card(who, o) {
        var d = document.createElement('div');
        var switchable = o.tid && payBox(o.tid), off = switchable && isOff(o.tid);
        var ownerOn = o.owner && o.ownerSw === true;
        d.className = 'sv-gp-row fx-row' + (off || o.muted || (o.owner && !ownerOn) ? ' is-off' : '') +
          (o.owner ? ' is-owner' + (o.ownerSw !== undefined ? ' can-pass' : '') : '') + (o.total_row ? ' is-total' : '');
        var calc = o.note || o.calc || '';
        var words = (o.rows || []).map(function (row) { return row[0] + (row[2] ? ' (пример)' : '') + ' — ' + row[1]; }).join(' · ');
        d.innerHTML = (o.owner || o.total_row ? '<span></span>' : '<span class="sv-no">' + (++no) + '</span>') +
          '<span class="sv-who fade"></span><span class="fx-rcalc' + (o.bad ? (soft ? ' is-warn' : ' is-err') : '') + '"></span>' +
          '<span class="sv-sum">' + esc(o.total || '—') + '</span>' +
          (switchable ? '<button type="button" class="sv-sw' + (off ? '' : ' is-on') + '" data-pay="' + o.tid + '" role="switch" aria-checked="' + !off +
            '" title="' + (off ? 'Не платит' : 'Платит') + '"></button>'
            : o.ownerSw !== undefined ? '<button type="button" class="sv-sw' + (o.ownerSw ? ' is-on' : '') + '" data-owner role="switch" aria-checked="' +
              o.ownerSw + '" title="Остаток на вас"></button>' : '<span></span>');
        d.querySelector('.sv-who').textContent = who;
        d.querySelector('.fx-rcalc').textContent = calc;
        d.querySelector('.fx-rcalc').title = words ? words + ' · ' + calc : calc;
        cards.appendChild(d);
      }
      // «Остаётся на вас» and «Всего по услуге» — the last rows of the same panel.
      // «Остаётся на вас» as everywhere: its switch shows once someone doesn't pay (canPass); off — those who pay share it.
      function sums(owner, total, calc, canPass, takes) {
        if (canPass || owner > 0.004) {
          card('Остаётся на вас', { owner: true, ownerSw: canPass ? takes : undefined, total: owner > 0.004 ? rub(owner, SYM) : '—',
            calc: canPass ? (takes ? 'часть неплатящих — на вас' : 'часть неплатящих делят платящие') : '' });
        }
        card('Всего по услуге', { total_row: true, calc: calc || '', total: rub(total, SYM) });
      }
      var takes = opts.ownerTakes ? opts.ownerTakes() : true;
      function fail(text) { var p = document.createElement('p'); p.className = 'fx-note ' + (soft ? 'is-warn' : 'is-err'); p.textContent = text; box.appendChild(p); }
      function hint(text, cls) { var h = document.createElement('p'); h.className = 'fx-hint' + (cls ? ' ' + cls : ''); h.textContent = text; box.appendChild(h); return h; }
      var ok = true;
      // Almost right (2026-11-22): the line shows the fix; here only the reasons, in orange — red is for real errors.
      var found = analyze();
      // While the line has a fix to put, what doesn't count yet is a warning (orange), not an error (red).
      var soft = Object.keys(found.marks).length > 0;
      if (isMixed(formulaMeters())) {
        fail(MIXED);
        badge.textContent = 'есть ошибка'; badge.className = 'fx-badge is-bad';
        return;
      }
      if (modeNow() === 'each') {
        // Every tenant with a meter of his in the formula pays by his own ones (another's meter is 0 for him).
        var payers = tenantsIn();
        {
          // Counted first: the part of those who don't pay may go to those who do (as the server does).
          var got = {}, onIds = [], offSum = 0, base = 0, all = 0, counted = 0;
          payers.forEach(function (id) {
            got[id] = evaluate(id);
            if (got[id].error) return;
            counted++;
            all += got[id].v;
            if (isOff(id)) offSum += got[id].v; else { onIds.push(id); base += got[id].v; }
          });
          var canPass = onIds.length > 0 && onIds.length < counted;
          var pass = canPass && !takes && offSum > 0;
          box.appendChild(cards);
          TENANTS.forEach(function (t) {
            if (payers.indexOf(t.id) < 0) { card(t.name, { note: 'не платит — нет его счётчика в формуле', muted: true }); return; }
            var r = got[t.id];
            if (r.error) { ok = false; card(t.name, { note: r.error, bad: true, tid: t.id }); return; }
            if (isOff(t.id)) {
              card(t.name, { note: 'не платит — его часть ' + rub(r.v, SYM) + (pass ? ' делят платящие' : ' на вас'), tid: t.id });
              return;
            }
            var extra = pass ? (base ? offSum * r.v / base : offSum / onIds.length) : 0;
            card(t.name, { rows: valueRows(r.parts), total: rub(r.v + extra, SYM), tid: t.id,
              calc: partsText(r.parts) + (extra ? ' + ' + rub(extra, SYM) + ' за неплатящих' : '') });
          });
          if (ok) sums(pass ? 0 : offSum, all, '', canPass, takes);
        }
      } else {
        var r = evaluate(null);
        if (r.error) { ok = false; fail(r.error); }
        else if (!TENANTS.length) {
          box.appendChild(cards);
          card('Вы', { rows: valueRows(r.parts), calc: partsText(r.parts), total: rub(r.v, SYM) });
        } else {
          var split = splitNow();
          var on = TENANTS.filter(function (t) { return !isOff(t.id); });
          var owner = r.v, whole = ['Сумма на объект', rub(r.v, SYM)];
          // As «Делим и кто платит» (services.js shares): «Остаётся на вас» on — of 100% / the object's м² / everyone;
          // off — of those who pay only.
          var canPass = split !== 'owner' && on.length > 0 && on.length < TENANTS.length;
          var tk = !canPass || takes;
          var weight = function (t) { return split === 'equal' ? 1 : split === 'area' ? (t.area || 0) : (t.share || 0); };
          var sumW = function (list) { return list.reduce(function (a, t) { return a + weight(t); }, 0); };
          var allW = split === 'shares' ? 100 : split === 'area' ? (ctx.area || sumW(TENANTS)) : TENANTS.length;
          var baseW = tk ? allW : sumW(on);
          box.appendChild(cards);
          if (split !== 'owner') {
            cards.insertAdjacentHTML('afterbegin', '<div class="sv-split-top">' + ICONS.people.replace('<svg ', '<svg class="sv-i" ') +
              '<div class="sv-how">' + [['shares', 'по долям'], ['equal', 'поровну'], ['area', 'по м²']].map(function (x) {
                return '<button type="button" data-split="' + x[0] + '"' + (x[0] === split ? ' class="is-on"' : '') + '>' + x[1] + '</button>';
              }).join('') + '</div></div>');
          }
          TENANTS.forEach(function (t) {
            if (split === 'owner') { card(t.name, { note: 'не платит — «Плачу сам»', muted: true }); return; }
            if (isOff(t.id)) { card(t.name, { note: 'не платит — его часть ' + (tk ? 'на вас' : 'делят платящие'), tid: t.id }); return; }
            var part = baseW ? r.v * weight(t) / baseW : 0, how;
            if (split === 'equal') how = '÷ ' + (tk ? TENANTS.length : on.length);
            else if (split === 'area') how = '× ' + fmt(t.area || 0) + ' ÷ ' + fmt(baseW) + ' м²';
            else how = '× ' + fmt(Math.round(weight(t) / baseW * 1000) / 10) + '%';
            owner -= part;
            card(t.name, { rows: [whole], calc: rub(r.v, SYM) + ' ' + how, total: rub(part, SYM), tid: t.id });
          });
          sums(owner, r.v, partsText(r.parts), canPass, tk);
          if (split === 'owner') hint('Всю сумму платите вы.');
        }
      }
      if (ok && evaluate(modeNow() === 'each' && TENANTS.length ? TENANTS[0].id : null).bare) {
        hint('У одного из чисел не указана единица — проверку «итог в рублях» для этой формулы не делаем.');
      }
      var samples = values.filter(function (v) { return v.type === 'month' && !v.real && blocks.some(function (b) { return b.vid === v.id; }); });
      var sampleMeters = blocks.some(function (b) { return b.type === 'meter' && b.meters.some(usageIsSample); });
      checkBadge.textContent = samples.length || sampleMeters ? 'на примерных числах' : 'на числах прошлого месяца';
      if (samples.length || sampleMeters) {
        var words = samples.map(function (v) { return v.label + ' ' + fmt(v.sample) + (v.unit ? ' ' + v.unit : ''); });
        if (sampleMeters) words.push('расход счётчиков без показаний');
        var h = hint('Прошлого месяца ещё нет — для примера взяли ' + words.join(', ') + '.', 'fx-sample-note');
        box.prepend(h);
      }
      badge.textContent = ok ? 'считается' : soft ? 'почти готово' : 'есть ошибка';
      badge.className = 'fx-badge ' + (ok ? 'is-ok' : soft ? '' : 'is-bad');
    }

    // ---------- Drag and drop (mouse and finger), click to add ----------
    var drag = null, justDragged = false;
    var caret = document.createElement('span'); caret.className = 'fx-caret';
    function insertBlock(b, at) { blocks.splice(at === undefined ? blocks.length : at, 0, b); render(); }
    function insertIndex(x, y) {
      var chips = Array.prototype.slice.call(strip.querySelectorAll('.fx-chip:not(.is-dragging):not(.is-ghost)'));
      for (var n = 0; n < chips.length; n++) {
        var r = chips[n].getBoundingClientRect();
        if (y < r.top - 4) return n;
        if (y <= r.bottom + 4 && x < r.left + r.width / 2) return n;
      }
      return chips.length;
    }
    function overStrip(x, y) { var r = strip.getBoundingClientRect(); return x >= r.left - 12 && x <= r.right + 12 && y >= r.top - 12 && y <= r.bottom + 12; }

    overlay.addEventListener('pointerdown', function (e) {
      if (!inline && e.target === overlay) { closeFormula(false); return; }
      var fix = e.target.closest('.fx-ghost');
      if (fix && fix.classList.contains('fx-ghost') && fix.dataset.op === '?') {
        // The blinking plaque: all six signs right at it, as the palette's «Знаки» (3 × 2)
        e.preventDefault(); closePop(); closeUnitMenu();
        var id = Number(fix.dataset.fix);
        var m = document.createElement('div'); m.className = 'fx-umenu fx-signmenu';
        m.innerHTML = ['+', '−', '×', '÷', '(', ')'].map(function (sign) {
          return '<button type="button" class="fx-chip k-op" data-sign="' + sign + '" title="Поставить «' + sign + '»">' + sign + '</button>';
        }).join('');
        overlay.appendChild(m);
        var r = fix.getBoundingClientRect();
        placeAt(m, Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)), r.bottom + 4 + m.offsetHeight > innerHeight ? r.top - 4 - m.offsetHeight : r.bottom + 4);
        m.addEventListener('click', function (ev) {
          var b = ev.target.closest('[data-sign]'); if (!b) return;
          closeUnitMenu(); applyFix(id, b.dataset.sign);
        });
        return;
      }
      if (fix) { e.preventDefault(); closePop(); applyFix(Number(fix.dataset.fix)); return; }
      var pin = e.target.closest('.fx-pin');
      if (pin) { e.preventDefault(); openNote(pin.closest('.fx-chip'), 'Подсказка', pin.dataset.say); return; }
      var del = e.target.closest('.fx-del');
      if (del) {
        e.preventDefault(); closePop();
        var owner = del.closest('.fx-chip'), id = owner.dataset.id;
        if ((owner.dataset.new || '').indexOf('val:') === 0) {
          // A number of the palette: it goes away together with its blocks in the formula.
          var vid = owner.dataset.new.slice(4);
          values = values.filter(function (v) { return v.id !== vid; });
          blocks = blocks.filter(function (b) { return !(b.type === 'val' && b.vid === vid); });
        } else blocks = blocks.filter(function (b) { return String(b.id) !== id; });
        justDragged = true; setTimeout(function () { justDragged = false; }, 0);
        render(); return;
      }
      var chip = e.target.closest('.fx-chip');
      if (!chip || e.button > 0) return;
      if (chip.dataset.new === 'pick:meters' && chip.classList.contains('is-off')) {
        // No meter is typed in any service: none can be taken — say why and how to fix it.
        e.preventDefault();
        openNote(chip, 'Счётчиков пока нет', METERS.length
          ? 'Счётчики объекта пока не подключены ни к одной услуге — их показания негде вводить. Подключите их в услуге «По счётчикам», и тогда их можно будет взять в формулу.'
          : 'У объекта нет счётчиков — их добавляют в окне объекта.');
        return;
      }
      var inStrip = strip.contains(chip);
      if (!inStrip && !chip.dataset.new) return;
      e.preventDefault();
      closePop();
      drag = { chip: chip, fromStrip: inStrip, startX: e.clientX, startY: e.clientY, moved: false };
      // in the body the pointer may leave the editor while dragging: it keeps the pointer until it is let go
      if (inline && overlay.setPointerCapture) { try { overlay.setPointerCapture(e.pointerId); } catch (err) { /* an old browser */ } }
    });
    overlay.addEventListener('pointermove', function (e) {
      if (!drag) return;
      if (!drag.moved && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) < 5) return;
      if (!drag.moved) {
        drag.moved = true;
        var kind = drag.chip.dataset.new || '';
        drag.block = drag.fromStrip ? blocks.find(function (b) { return String(b.id) === drag.chip.dataset.id; })
          : kind.indexOf('new:') === 0 || kind.indexOf('pick:') === 0 ? { id: 0, type: 'new', kind: kind } : make(kind);
        drag.ghost = drag.block.type === 'new' ? drag.chip.cloneNode(true) : chipEl(drag.block);
        drag.ghost.classList.add('is-ghost');
        // A block of the formula keeps its size while dragged: its copy lives in the line, where the blocks' styles are.
        (drag.block.type === 'new' ? overlay : strip).appendChild(drag.ghost);
        if (drag.fromStrip) drag.chip.classList.add('is-dragging');
        drag.o = origin(drag.ghost);
      }
      drag.ghost.style.left = (e.clientX - 20 - drag.o.x) + 'px'; drag.ghost.style.top = (e.clientY - 15 - drag.o.y) + 'px';
      var over = overStrip(e.clientX, e.clientY);
      strip.classList.toggle('is-over', over);
      caret.remove();
      if (over) {
        var chips = Array.prototype.slice.call(strip.querySelectorAll('.fx-chip:not(.is-dragging):not(.is-ghost)'));
        var at = insertIndex(e.clientX, e.clientY);
        if (at < chips.length) strip.insertBefore(caret, chips[at]); else strip.appendChild(caret);
      }
    });
    overlay.addEventListener('pointerup', function (e) {
      if (!drag) return;
      var d = drag; drag = null;
      caret.remove(); strip.classList.remove('is-over');
      var kind = d.chip.dataset.new || '';
      if (!d.moved) {
        if (kind === 'pick:meters') openMeters(d.chip);
        else if (kind.indexOf('new:') === 0) openDraft(kind.slice(4), d.chip);
        else if (!d.fromStrip) insertBlock(make(kind));
        else openPop(blocks.find(function (b) { return String(b.id) === d.chip.dataset.id; }), d.chip);
        return;
      }
      d.ghost.remove();
      justDragged = true; setTimeout(function () { justDragged = false; }, 0);
      var over = overStrip(e.clientX, e.clientY);
      var at = over ? insertIndex(e.clientX, e.clientY) : -1;
      if (d.block.type === 'new') {
        if (over) { if (d.block.kind === 'pick:meters') openMeters(d.chip, at); else openDraft(d.block.kind.slice(4), d.chip, at); }
        return;
      }
      if (d.fromStrip) blocks = blocks.filter(function (b) { return b !== d.block; });  // moved or dragged out (= deleted)
      if (over) blocks.splice(Math.min(at, blocks.length), 0, d.block);
      render();
    });
    var clearBtn = overlay.querySelector('[data-clear]');
    if (clearBtn) clearBtn.addEventListener('click', function () { closePop(); blocks = []; render(); });

    // ---------- Examples: a ready formula from this object's own meters; its numbers go to the palette ----------
    // A number of an example is taken from the palette when it is already there (by its name) — pressing twice adds nothing.
    function exampleValue(type, props) {
      return values.find(function (v) { return v.type === type && v.label === props.label; }) ||
        newValue(type, Object.assign({ sample: type === 'month' ? sampleFor(props.unit) : 0 }, props));
    }
    function val(v) { return { id: ++uid, type: 'val', vid: v.id }; }
    function op(sign) { return make('op:' + sign); }
    var EXAMPLES = {
      sewage: { needs: ['hot_water', 'water'], build: function () {
        var t = exampleValue('const', { label: 'Тариф водоотведения', value: 45, unit: '₽', per: 'м³' });
        return meterBlocks(activeOf(['water', 'hot_water'])).concat([op('×'), val(t)]);
      } },
      // The first tenant's own light meter × a tariff: only that tenant pays by this formula.
      one: { needs: ['electricity'], build: function (anchor) {
        var first = TENANTS[0];
        var meter = first && METERS.find(function (m) { return m.key === 'electricity' && isActive(m) && tenantOf(m.id) === first.id; });
        if (!meter) {
          openNote(anchor, 'Пример не собрать', 'Для этого примера у первого арендатора должен быть свой счётчик электричества, подключённый к услуге «По счётчикам».');
          return null;
        }
        var t = exampleValue('const', { label: 'Тариф', value: 9.6, unit: '₽', per: 'кВт·ч' });
        return meterBlocks([meter.id]).concat([op('×'), val(t)]);
      } },
    };
    if (overlay.querySelector('.fx-examples')) overlay.querySelector('.fx-examples').addEventListener('click', function (e) {
      var btn = e.target.closest('[data-example]'); if (!btn) return;
      closePop();
      var example = EXAMPLES[btn.dataset.example];
      var missing = example.needs.filter(function (key) { return !METERS.some(function (m) { return m.key === key && isActive(m); }); });
      if (missing.length) {
        var names = { electricity: 'Электричество', water: 'Вода холодная', hot_water: 'Вода горячая' };
        openNote(btn, 'Пример не собрать', 'Для этого примера нужны счётчики: ' + missing.map(function (k) { return '«' + names[k] + '»'; }).join(' и ') +
          '. Добавьте их в окне объекта и подключите в услуге «По счётчикам» — там вводятся показания.');
        return;
      }
      var built = example.build(btn);
      if (built) { blocks = built; render(); }
    });
    // inline: the service window handles its own «Как посчитается» (data-pay / data-owner / data-split)
    if (!inline) overlay.querySelector('[data-check]').addEventListener('click', function (e) {
      if (e.target.closest('[data-owner]') && opts.toggleOwner) { opts.toggleOwner(); render(); return; }
      var how = e.target.closest('[data-split]');
      if (how && opts.setSplit) { opts.setSplit(how.dataset.split); render(); return; }
      var b = e.target.closest('[data-pay]'); if (!b || !payBox(b.dataset.pay)) return;
      opts.togglePay(Number(b.dataset.pay));
      render();
    });

    // ---------- The small windows: a number's setup, a meter's «чей расход» ----------
    var pop = null;
    function closePop() { closeUnitMenu(); if (pop) pop.remove(); pop = null; }
    function placePop(anchor) {
      var r = anchor.getBoundingClientRect();
      // A wide one («Расход счётчиков») — in the middle of the formula window, not hanging off its edge.
      var m = pop.classList.contains('is-wide') ? (overlay.querySelector('.fx-modal') || overlay).getBoundingClientRect() : null;
      var left = m ? m.left + (m.width - pop.offsetWidth) / 2 : r.left;
      var h = pop.offsetHeight;
      placeAt(pop, Math.max(8, Math.min(left, innerWidth - pop.offsetWidth - 8)), r.bottom + 8 + h > innerHeight ? Math.max(8, r.top - h - 8) : r.bottom + 8);
    }
    // HTML: the word that changes with the units — «тариф / сумма / норматив / …» — in bold (2026-11-23).
    function valueSays(v) {
      var n = v.type === 'const' ? fmt(v.value) : 'число';
      var unit = esc(v.unit || ''), one = v.per ? ' за 1 ' + esc(v.per) : '';
      var is = function (word, rest) { return 'Это <b>' + word + '</b>: ' + rest; };
      if (v.type === 'month') {
        if (!v.unit) return 'Каждый месяц на странице объекта вводите число (без единицы итог в рублях не проверяем).';
        return 'Каждый месяц на странице объекта вводите ' + (v.unit === '₽' ? 'сумму в ₽' : 'сколько ' + unit) + ' — например, из квитанции.';
      }
      if (!v.unit) return is('коэффициент', n + '. Без единицы итог в рублях не проверяем.');
      if (v.unit === '₽') return v.per ? is('тариф', n + ' ₽' + one + '.') : is('сумма', n + ' ₽ каждый месяц.');
      return v.per ? is('норматив', n + ' ' + unit + ' на 1 ' + esc(v.per) + '.') : is('количество', n + ' ' + unit + '.');
    }
    function unitButton(key, cur) { return '<button type="button" class="fx-usel" data-k="' + key + '" data-v="' + esc(cur || '') + '"><span>' + esc(cur || '—') + '</span>' + CHEV + '</button>'; }
    function valueFields(v) {
      var num = function (n) { return String(n).replace('.', ','); };
      var name = '<label class="fx-f"><span>Название <span class="req">*</span></span><input data-k="label" value="' + esc(v.label) + '" placeholder="' +
        (v.type === 'const' ? 'Например, Тариф тепло' : 'Например, Тепло по квитанции') + '"><small>Так подписано на странице объекта и в счёте</small></label>';
      if (v.type === 'month') {
        return name + '<div class="fx-f">Цифра для проверки формулы<div class="fx-vrow is-one"><span class="fx-vfield">' +
          '<input data-k="sample" class="fx-sample" disabled value="' + num(v.sample || sampleFor(v.unit)) + '">' + unitButton('unit', v.unit) +
          '</span></div></div><p class="fx-say">' + valueSays(v) + '</p>';
      }
      // Two fields side by side (variant Г, 2026-11-23): «Сколько [45 | ₽ ▾]» · «За [1 м³ ▾]»; «—» in both — a coefficient.
      return name + '<div class="fx-two"><div class="fx-f">Сколько<span class="fx-vfield">' +
        '<input data-k="value" inputmode="decimal" value="' + (v.value ? num(v.value) : '') + '" placeholder="0">' +
        unitButton('unit', v.unit) + '</span></div>' +
        '<div class="fx-f">За<span class="fx-vfield is-per"><span class="fx-one">1</span>' + unitButton('per', v.per) +
        '</span></div></div><p class="fx-say">' + valueSays(v) + '</p>';
    }
    // The number's fields write into v; «change» of a unit refreshes the sample and the sentence.
    function wireValue(v, onChange) {
      pop.addEventListener('input', function (ev) {
        var key = ev.target.dataset.k; if (!key || ev.target.tagName !== 'INPUT') return;
        var val = ev.target.value;
        if (key === 'value') val = toNumber(val);
        v[key] = val;
        pop.querySelector('.fx-say').innerHTML = valueSays(v);
        onChange();
      });
      pop.querySelectorAll('.fx-usel').forEach(function (btn) {
        btn.addEventListener('click', function () {
          openUnitMenu(btn, function (unit) {
            v[btn.dataset.k] = unit;
            btn.dataset.v = unit;
            btn.querySelector('span').textContent = unit || '—';
            if (btn.dataset.k === 'unit' && v.type === 'month' && !v.real) {
              v.sample = sampleFor(unit);
              var f = pop.querySelector('.fx-sample'); if (f) f.value = String(v.sample).replace('.', ',');
            }
            pop.querySelector('.fx-say').innerHTML = valueSays(v);
            onChange();
          });
        });
      });
    }
    // A new number is set up first — next to the palette — then kept («Сохранить») or put in the formula.
    // A block of the palette (window v2): the ready numbers of this kind on top — a click puts one in the formula,
    // × deletes it; below — a new one, set up and put in the formula.
    function readyRows(type) {
      var own = values.filter(function (v) { return v.type === type; }).map(function (v) {
        var b = { type: 'val', vid: v.id };
        return '<div class="fx-ready-row"><button type="button" class="fx-ready ' + kindClass(b) + '" data-use="' + esc(v.id) + '">' +
          '<span class="fx-ico">' + iconOf(b) + '</span><span class="fx-ready-nm"></span><span class="fx-ready-v">' +
          esc(chipValue(b).replace(' за ', '/') || (type === 'const' ? 'коэффициент' : 'каждый месяц')) + '</span></button>' +
          '<button type="button" class="fx-ready-del" data-drop="' + esc(v.id) + '" title="Удалить число" aria-label="Удалить «' + esc(v.label) + '»">×</button></div>';
      });
      // The numbers of the account's other services (2026-11-25, every object): a click copies one into this service.
      // No × — they belong to those services.
      // with rows of this service above (they have ×) — an empty place for × too: all the rows of one width
      var gap = own.length ? '<span class="fx-ready-gap"></span>' : '';
      var lib = libraryOf(type).map(function (n) {
        var v = libValue(n), units = unitLabel(v);
        var text = (type === 'const' ? fmt(v.value) + (units ? ' ' + units : '') : units).replace(' за ', '/') ||
          (type === 'const' ? 'коэффициент' : 'каждый месяц');
        return '<div class="fx-ready-row"><button type="button" class="fx-ready k-' + type + '" data-lib="' + LIBRARY.indexOf(n) + '">' +
          '<span class="fx-ico">' + ICONS[type] + '</span><span class="fx-ready-nm"></span><span class="fx-ready-v">' +
          esc(text) + '</span></button>' + gap + '</div>';
      });
      return own.concat(lib).join('');
    }
    function libValue(n) {
      var unit = cleanUnit(n.unit);
      return { label: n.label, unit: unit, per: n.monthly ? '' : cleanUnit(n.per), value: n.value || 0,
        sample: n.monthly ? sampleFor(unit) : 0 };
    }
    // The library without what this service already has (the same name, unit and value).
    function libraryOf(type) {
      return LIBRARY.filter(function (n) {
        return (n.monthly ? 'month' : 'const') === type && !values.some(function (v) {
          return v.type === type && v.label.trim().toLowerCase() === n.label.trim().toLowerCase() &&
            v.unit === cleanUnit(n.unit) && v.per === cleanUnit(n.per) && (type === 'month' || Number(v.value) === Number(n.value));
        });
      });
    }
    function openDraft(type, anchor, at) {
      closePop();
      var v = { id: '', type: type, label: '', unit: '₽', per: type === 'const' ? 'м³' : '', value: 0, sample: 0, real: false };
      if (type === 'month') v.sample = sampleFor(v.unit);
      var ready = readyRows(type);
      pop = document.createElement('div'); pop.className = 'fx-pop';
      // The new one on top, the ready ones under it (2026-11-22), then the buttons.
      pop.innerHTML = '<h4>' + (type === 'const' ? 'Постоянное число' : 'Число за месяц') + '</h4>' +
        valueFields(v) +
        (ready ? '<div class="fx-f fx-or">Или готовое</div><div class="fx-ready-list">' + ready + '</div>' : '') +
        '<div class="fx-acts"><button type="button" class="fx-btn" data-cancel>Отмена</button>' +
        '<button type="button" class="fx-btn is-primary" data-put disabled>В формулу</button></div>';
      overlay.appendChild(pop);
      pop.querySelectorAll('[data-use]').forEach(function (btn) {
        btn.querySelector('.fx-ready-nm').textContent = valueById(btn.dataset.use).label;
        btn.onclick = function () { closePop(); insertBlock({ id: ++uid, type: 'val', vid: btn.dataset.use }, at); };
      });
      pop.querySelectorAll('[data-lib]').forEach(function (btn) {
        var n = LIBRARY[Number(btn.dataset.lib)];
        btn.querySelector('.fx-ready-nm').textContent = n.label;
        btn.onclick = function () { var v = newValue(type, libValue(n)); closePop(); insertBlock({ id: ++uid, type: 'val', vid: v.id }, at); };
      });
      pop.querySelectorAll('[data-drop]').forEach(function (btn) {
        btn.onclick = function () {
          var vid = btn.dataset.drop;
          values = values.filter(function (x) { return x.id !== vid; });
          blocks = blocks.filter(function (b) { return !(b.type === 'val' && b.vid === vid); });
          render();
          openDraft(type, anchor, at);
        };
      });
      placePop(anchor);
      var check = function () { pop.querySelector('[data-put]').disabled = !String(v.label).trim(); };
      wireValue(v, check);
      function save() { return newValue(type, { label: v.label.trim(), unit: v.unit, per: v.per, value: v.value, sample: v.sample }); }
      pop.querySelector('[data-cancel]').onclick = closePop;
      pop.querySelector('[data-put]').onclick = function () { var saved = save(); closePop(); insertBlock({ id: ++uid, type: 'val', vid: saved.id }, at); };
      pop.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && !pop.querySelector('[data-put]').disabled) { ev.preventDefault(); pop.querySelector('[data-put]').click(); } });
      pop.querySelector('[data-k="label"]').focus();
    }

    // ---------- «Расход счётчиков» (window v2): every meter of the object with a tick, no groups ----------
    function activeOf(keys) { return METERS.filter(function (m) { return keys.indexOf(m.key) >= 0 && isActive(m); }).map(function (m) { return m.id; }); }
    // The ticked meters into the formula: each a block of its own (no sums of meters — 2026-11-22); several — «( А + Б )».
    function meterBlocks(ids) {
      var list = ids.map(function (id) { return { id: ++uid, type: 'meter', key: meterById(id).key, meters: [id], join: 'each' }; });
      if (list.length < 2) return list;
      var out = [op('(')];
      list.forEach(function (b, n) { if (n) out.push(op('+')); out.push(b); });
      out.push(op(')'));
      return out;
    }
    // Meters already standing in the formula as blocks of their own: one meter goes in once.
    function inFormula() {
      var ids = [];
      blocks.forEach(function (b) { if (b.type === 'meter' && b.join !== 'sum') b.meters.forEach(function (id) { ids.push(id); }); });
      return ids;
    }
    function openMeters(anchor, at) {
      closePop();
      var picked = [], taken = inFormula();
      function free(keys) { return activeOf(keys).filter(function (id) { return taken.indexOf(id) < 0; }); }
      // Quick ticks: «вся вода» when there are both waters, then each kind there is (only meters not in the formula yet).
      var quick = [];
      if (free(['water']).length && free(['hot_water']).length) quick.push(['water,hot_water', 'вся вода']);
      KINDS.forEach(function (k) { if (free([k.key]).length) quick.push([k.key, k.name.toLowerCase()]); });
      pop = document.createElement('div'); pop.className = 'fx-pop is-wide';
      pop.innerHTML = '<h4>Расход счётчиков</h4>' +
        (quick.length > 1 ? '<div class="fx-quick">Отметить:' + quick.map(function (q) {
          return '<button type="button" data-quick="' + q[0] + '">' + esc(q[1]) + '</button>';
        }).join('') + '</div>' : '') +
        '<div class="fx-mlist"><div class="fx-mhead"><span></span><span></span><span>Счётчик</span><span>Кто платит</span></div>' +
        METERS.map(function (m) {
          var k = kindOf(m.key), on = isActive(m), used = taken.indexOf(m.id) >= 0;
          var sub = !on ? 'не подключён к услуге' : used ? 'уже в формуле' : 'расход' + (k.unit ? ', ' + esc(k.unit) : '');
          return '<label class="fx-mline mk-' + k.icon + (on && !used ? '' : ' is-off') + (used ? ' is-used' : '') + '"' +
            (on ? '' : ' title="' + esc(offText(m)) + '"') + '>' +
            '<input type="checkbox" data-m="' + m.id + '"' + (used ? ' checked disabled' : on ? '' : ' disabled') + '>' +
            '<span class="fx-ico">' + (ICONS[k.icon] || ICONS.custom) + '</span>' +
            '<span class="fx-mname"><span>' + esc(meterName(m)) + '</span><small>' + sub + '</small></span>' +
            '<span class="fx-mwho">' + esc(whoLabel(m.id)) + '</span></label>';
        }).join('') + '</div>' +
        '<p class="fx-example" data-mnote></p>' +
        '<div class="fx-acts"><button type="button" class="fx-btn" data-cancel>Отмена</button>' +
        '<button type="button" class="fx-btn is-primary" data-add disabled>Добавить</button></div>';
      overlay.appendChild(pop);
      placePop(anchor);
      function refresh() {
        pop.querySelectorAll('[data-m]:not(:disabled)').forEach(function (box) { box.checked = picked.indexOf(Number(box.dataset.m)) >= 0; });
        var mixed = isMixed(picked.concat(formulaMeters()));
        var add = pop.querySelector('[data-add]'), note = pop.querySelector('[data-mnote]');
        add.disabled = !picked.length || mixed;
        add.textContent = picked.length ? 'Добавить ' + meterCount(picked.length) : 'Добавить';
        note.textContent = mixed ? MIXED : picked.length > 1 ? 'В формулу встанут через «+» в скобках.' : '';
        note.classList.toggle('is-warn', mixed);
      }
      pop.addEventListener('change', function (ev) {
        var id = Number(ev.target.dataset.m); if (!id) return;
        picked = ev.target.checked ? picked.concat([id]) : picked.filter(function (x) { return x !== id; });
        refresh();
      });
      pop.addEventListener('click', function (ev) {
        var q = ev.target.closest('[data-quick]'); if (!q) return;
        var ids = free(q.dataset.quick.split(','));
        var all = ids.every(function (id) { return picked.indexOf(id) >= 0; });
        picked = all ? picked.filter(function (id) { return ids.indexOf(id) < 0; })
          : picked.concat(ids.filter(function (id) { return picked.indexOf(id) < 0; }));
        refresh();
      });
      pop.querySelector('[data-cancel]').onclick = closePop;
      pop.querySelector('[data-add]').onclick = function () {
        // In the object's order, not the order of the ticks.
        var ids = METERS.map(function (m) { return m.id; }).filter(function (id) { return picked.indexOf(id) >= 0; });
        var add = meterBlocks(ids);
        closePop();
        var where = at === undefined ? blocks.length : Math.min(at, blocks.length);
        blocks.splice.apply(blocks, [where, 0].concat(add));
        render();
      };
      refresh();
    }

    function openPop(b, anchor) {
      closePop();
      if (!b || b.type === 'op') return;
      pop = document.createElement('div'); pop.className = 'fx-pop';
      if (b.type === 'val') {
        var v = valueOf(b);
        var uses = blocks.filter(function (x) { return x.vid === v.id; }).length;
        pop.innerHTML = '<h4>' + (v.type === 'const' ? 'Тариф или норматив · задаёте один раз' : 'Вводите каждый месяц · например, из квитанции') + '</h4>' +
          (uses > 1 ? '<p class="fx-uses">Стоит в формуле ' + uses + ' раза — правка меняет везде.</p>' : '') + valueFields(v);
      } else if (b.meters.length === 1) {
        // A meter of its own (window v2): what it is, whose, where its readings are typed.
        var m = meterById(b.meters[0]), k = kindOf(b.key);
        pop.innerHTML = '<h4>' + esc(meterName(m)) + '</h4><p class="fx-example">Расход за месяц' + (k.unit ? ', ' + esc(k.unit) : '') +
          ' · ' + esc(whoLabel(m.id)) + (m.typed && m.typed.length ? ' · показания вводятся в «' + esc(m.typed[0]) + '»' : '') + '.</p>';
      } else {
        // «Σ»: nothing to set up — only what it stands for.
        pop.innerHTML = '<h4>Σ ' + esc(kindOf(b.key).name) + '</h4><p class="fx-example">' +
          (b.join === 'sum' ? 'Весь расход объекта — одно число для всех: ' : 'Сумма ' + meterCount(b.meters.length) + ': ') +
          esc('(' + b.meters.map(function (id) { return oneName({ key: b.key, meters: [id] }); }).join(' + ') + ')') + '</p>' +
          '<ul class="fx-sumlist">' + b.meters.map(function (id) {
            return '<li><span>' + esc(meterName(meterById(id))) + '</span><span>' + esc(whoLabel(id)) + '</span></li>';
          }).join('') + '</ul>';
      }
      pop.insertAdjacentHTML('beforeend', '<div class="fx-acts"><button type="button" class="fx-btn is-danger" data-del>Убрать из формулы</button><button type="button" class="fx-btn is-primary" data-ok>Готово</button></div>');
      overlay.appendChild(pop);
      placePop(anchor);
      if (b.type === 'val') wireValue(valueOf(b), render);
      pop.querySelector('[data-ok]').onclick = closePop;
      pop.querySelector('[data-del]').onclick = function () { blocks = blocks.filter(function (x) { return x !== b; }); closePop(); render(); };
    }
    // Our own menus (no browser list): units with «свой вариант…», a meter's «чей».
    function closeUnitMenu() {
      overlay.querySelectorAll('.fx-umenu').forEach(function (m) { m.remove(); });
      overlay.querySelectorAll('.fx-usel.is-open').forEach(function (b) { b.classList.remove('is-open'); });
    }
    function openUnitMenu(btn, pick) {
      var units = (ctx.units || []).slice();
      var cur = btn.dataset.v || '';
      if (cur && units.indexOf(cur) < 0) units.push(cur);
      openMenu(btn, [['', 'без единицы']].concat(units.map(function (u) { return [u, u]; })), cur, true, pick);
    }
    function openMenu(btn, options, cur, custom, pick, customText) {
      var was = btn.classList.contains('is-open');
      closeUnitMenu(); if (was) return;
      btn.classList.add('is-open');
      var m = document.createElement('div'); m.className = 'fx-umenu'; m.setAttribute('role', 'listbox');
      m.innerHTML = options.map(function (o) {
        return '<button type="button" role="option" data-v="' + esc(o[0]) + '"' + (o[0] === cur ? ' class="is-on"' : '') + '>' +
          (o[0] || !custom ? esc(o[1]) : '<span class="fx-none">' + esc(o[1]) + '</span>') + '</button>';
      }).join('') + (custom ? '<div class="fx-ucustom"><input placeholder="' + esc(customText || 'свой вариант…') + '" maxlength="20"><button type="button" title="Добавить">✓</button></div>' : '');
      overlay.appendChild(m);
      var r = btn.getBoundingClientRect();
      m.style.minWidth = Math.max(r.width, 150) + 'px';
      placeAt(m, Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)), r.bottom + 4 + m.offsetHeight > innerHeight ? r.top - 4 - m.offsetHeight : r.bottom + 4);
      function done(value) { closeUnitMenu(); btn.focus(); pick(cleanUnit(value)); }
      m.addEventListener('click', function (e) {
        var o = e.target.closest('[data-v]'); if (o) { done(o.dataset.v); return; }
        if (e.target.closest('.fx-ucustom button')) { var t = m.querySelector('.fx-ucustom input').value; if (t.trim()) done(t); }
      });
      var input = m.querySelector('.fx-ucustom input');
      if (input) input.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== 'Escape') return;
        e.preventDefault(); e.stopPropagation();
        if (e.key === 'Escape') { closeUnitMenu(); btn.focus(); } else if (e.target.value.trim()) done(e.target.value);
      });
    }
    overlay.addEventListener('pointerdown', function (e) {
      if (!e.target.closest('.fx-umenu, .fx-usel')) closeUnitMenu();
      if (pop && !pop.contains(e.target) && !e.target.closest('.fx-umenu') && !strip.contains(e.target)) closePop();
    }, true);

    // ---------- Signs from the keyboard; Escape ----------
    overlay.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (inline && !overlay.querySelector('.fx-umenu') && !pop) return;  // nothing open — Escape is the service window's
        e.preventDefault(); e.stopPropagation();
        if (overlay.querySelector('.fx-umenu')) closeUnitMenu();
        else if (pop) closePop();
        else closeFormula(false);
        return;
      }
      if (e.target.closest('input, textarea')) return;
      if (KEYS[e.key]) { e.preventDefault(); insertBlock(make('op:' + KEYS[e.key])); }
      else if (e.key === 'Backspace' && blocks.length) { e.preventDefault(); blocks.pop(); render(); }
    });
    // The service window's <dialog> closes on Escape — not while the formula window is open.
    function onCancel(e) { if (!overlay.hidden) { e.preventDefault(); closeFormula(false); } }
    if (host.tagName === 'DIALOG') host.addEventListener('cancel', onCancel);

    // ---------- Open / close; what the service window sees ----------
    var saved = null;
    function snapshot() { return JSON.stringify({ blocks: blocks, values: values, owners: owners }); }
    function openFormula() {
      saved = snapshot();
      overlay.hidden = false;
      render();
      overlay.querySelector('.fx-modal').setAttribute('tabindex', '-1');
      overlay.querySelector('.fx-modal').focus();
    }
    function closeFormula(keep) {
      closePop();
      if (!keep && saved) {
        var s = JSON.parse(saved);
        blocks = s.blocks; values = s.values; owners = s.owners;
      }
      overlay.hidden = true;
      publish();
      if (opts.close) opts.close(keep);
    }
    function serialize() {
      return {
        numbers: values.map(function (v) {
          return { id: v.id, label: v.label, monthly: v.type === 'month', unit: v.unit, per: v.type === 'month' ? '' : v.per,
            value: v.type === 'const' ? v.value : null };
        }),
        blocks: blocks.map(function (b) {
          if (b.type === 'val') return { t: 'num', id: b.vid };
          if (b.type === 'meter') return { t: 'meter', key: b.key, meters: b.meters, join: b.join };
          return { t: 'op', op: b.op };
        }),
        owners: owners,
      };
    }
    function publish() {
      var words = blocks.map(chipText).join(' ').replace(/\( /g, '(').replace(/ \)/g, ')');
      if (opts.publish) opts.publish(serialize(), words, modeNow() === 'each');
    }
    if (inline) render();  // draws the line, the check and publishes what is there
    else {
      overlay.querySelector('[data-cancel]').addEventListener('click', function () { closeFormula(false); });
      overlay.querySelector('[data-x]').addEventListener('click', function () { closeFormula(false); });
      overlay.querySelector('[data-done]').addEventListener('click', function () { closeFormula(true); });
      publish();
    }
    // The service window shows the same formula and the same «Как посчитается» (2026-11-22): blocks here are read-only,
    // the panel's switches are the service window's own (data-pay / data-owner / data-split are handled there).
    function preview(chipsEl, checkEl) {
      if (chipsEl) {
        chipsEl.innerHTML = '';
        if (!blocks.length) chipsEl.innerHTML = '<span class="fx-empty">Формула ещё не собрана</span>';
        blocks.forEach(function (b) { chipsEl.appendChild(chipEl(b)); });
        chipsEl.querySelectorAll('.fx-nm, .fx-s2').forEach(function (e) { e.classList.toggle('is-cut', e.scrollWidth > e.clientWidth + 1); });
      }
      if (checkEl && blocks.length) renderCheck(checkEl);
    }
    return {
      preview: preview,
      open: openFormula,
      destroy: function () { closePop(); overlay.remove(); if (host.tagName === 'DIALOG') host.removeEventListener('cancel', onCancel); },
    };
  }

  /* The service window (services.js) opens it: one window per opening, gone when closed.
     «Делим» and the «платит» switches live in the service window: the check follows them. */
  window.rentflowFormula = {
    // Draw the formula (blocks) and «Как посчитается» into the service window, without opening the formula window.
    preview: function (opts, chipsEl, checkEl) {
      var fx = setup(Object.assign({}, opts, { host: document.createElement('div') }));
      fx.preview(chipsEl, checkEl);
    },
    // The editor right in the service window's body (2026-11-24): opts.host — where, opts.checkEl — «Как посчитается»,
    // opts.publish — every change.
    inline: function (opts) {
      return setup(Object.assign({}, opts, { inline: true }));
    },
    open: function (opts) {
      var fx = setup(Object.assign({}, opts, {
        close: function (keep) {
          fx.destroy();
          if (opts.close) opts.close(keep);
        },
      }));
      fx.open();
      return fx;
    },
  };
})();
