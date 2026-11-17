/* «Своя формула» — its own window over the service window (2026-11-16), as in the approved mockup
   docs/mockups/2026-11-16-formula-blocks.html (round 25).

   The service window has a panel row [data-formula-panel]: the formula in words, «Собрать / Изменить формулу», a hidden
   formula_json (what the server saves) and #formula-ctx (the object's tenants, meters with last month's usage, the numbers
   and the blocks). The window keeps its state in memory; «Готово» writes formula_json, «Отмена» brings back what was.
   The server counts the bills itself (apps/billing/formula.py) — the check here is only a preview on last month's numbers.

   Meters: a block of a kind («Электричество») with the object's meters of that kind ticked, and each meter's «чей»
   (the tenant who pays by it). One meter of a tenant — the formula is his only; several «у каждого свой» — each by his
   own; «складываем» or common ones — one number for all. Who pays is not asked: it follows from the formula. */
(function () {
  'use strict';

  var SAMPLES = { '₽': 6400, 'кВт·ч': 270, 'м³': 5, 'Гкал': 0.42, 'м²': 60, 'чел.': 3 };
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
    electricity: svg('<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/>', true),
    water: svg('<path d="M12 2.5c-.3 0-.6.2-.8.4C9.4 5.3 5.5 10.4 5.5 14.5a6.5 6.5 0 0 0 13 0c0-4.1-3.9-9.2-5.7-11.6-.2-.2-.5-.4-.8-.4z"/>', true),
    heating: svg('<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 6v12M12 6v12M16 6v12M6 18v3M18 18v3"/>'),
    gas: svg('<path d="M12 2s5 4.6 5 10a5 5 0 0 1-10 0c0-2.4 1.3-4.3 2.3-5.4.2 1.6 1 2.6 1.9 2.6C12.6 9.2 11 5.9 12 2z"/>', true),
    custom: svg('<circle cx="12" cy="13" r="8"/><path d="M12 13l4-4M12 5V3"/>'),
  };
  ICONS.hot_water = ICONS.water;
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

  function setup(panel) {
    var form = panel.closest('form');
    var host = form.closest('dialog') || document.body;
    var ctx = JSON.parse(panel.querySelector('#formula-ctx').textContent);
    var jsonInput = panel.querySelector('[data-formula-json]');
    var summaryEl = panel.querySelector('[data-formula-summary]');
    var openBtn = panel.querySelector('[data-formula-open]');
    var TENANTS = ctx.tenants, METERS = ctx.meters, KINDS = ctx.kinds, SYM = ctx.symbol || '₽';
    var uid = 0, nid = 0;

    var values = ctx.numbers.map(function (n) {
      return { id: String(n.id), type: n.monthly ? 'month' : 'const', label: n.label, unit: cleanUnit(n.unit), per: cleanUnit(n.per),
        value: n.value === null || n.value === undefined ? 0 : n.value,
        sample: n.last === null || n.last === undefined ? sampleFor(n.unit) : n.last, real: n.last !== null && n.last !== undefined };
    });
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
    function offKindText(key) {
      return 'Счётчики «' + kindOf(key).name + '» пока не подключены ни к одной услуге — их показания негде вводить. ' +
        'Подключите счётчик в услуге «По счётчикам» (например, создайте услугу «' + kindOf(key).name + '»), ' +
        'и тогда его можно будет взять в формулу.';
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
    function usageOf(meterId) { var m = meterById(meterId); return m && m.last !== null && m.last !== undefined ? m.last : sampleFor(kindOf(m ? m.key : '').unit); }
    function usageIsSample(meterId) { var m = meterById(meterId); return !m || m.last === null || m.last === undefined; }
    function payBox(tenantId) { return form.querySelector('input[name=pays][value="' + tenantId + '"]'); }
    function isOff(tenantId) { var box = payBox(tenantId); return box ? !box.checked : false; }
    function splitNow() { var r = form.querySelector('input[name=split]:checked'); return r ? r.value : 'shares'; }

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

    function modeNow() {
      if (!TENANTS.length) return 'total';
      return blocks.some(function (b) {
        return b.type === 'meter' && ((b.meters.length > 1 && b.join === 'each') || (b.meters.length === 1 && tenantOf(b.meters[0])));
      }) ? 'each' : 'total';
    }

    // ---------- The DOM of the window ----------
    var overlay = document.createElement('div');
    overlay.className = 'fx-overlay';
    overlay.hidden = true;
    overlay.innerHTML =
      '<div class="fx-modal" role="dialog" aria-label="Своя формула">' +
      '<h2>Своя формула</h2>' +
      '<p class="fx-desc">Соберите расчёт как на бумаге: числа, счётчики и знаки. Внизу сразу видно, сколько выйдет у каждого арендатора.</p>' +
      '<div class="fx-examples">Примеры:' +
      '<button type="button" data-example="sewage">Водоотведение</button>' +
      '<button type="button" data-example="usage">Сумма по расходу</button>' +
      '<button type="button" data-example="heat">Отопление</button>' +
      '<button type="button" data-example="one">Только арендатору 1</button></div>' +
      '<div class="fx-palette">' +
      '<div class="fx-group"><h3>Вводите каждый месяц</h3><p class="fx-sub">например, из квитанции</p><div class="fx-chips" data-pal="month"></div></div>' +
      '<div class="fx-group"><h3>Тарифы и нормативы</h3><p class="fx-sub">задаёте один раз</p><div class="fx-chips" data-pal="const"></div></div>' +
      '<div class="fx-group"><h3>Счётчики</h3><p class="fx-sub">расход за месяц</p><div class="fx-chips" data-pal="meter"></div></div>' +
      '<div class="fx-group"><h3>Знаки</h3><p class="fx-sub">или с клавиатуры</p><div class="fx-chips is-signs">' +
      ['+', '−', '×', '÷', '(', ')'].map(function (s) { return '<span class="fx-chip k-op" data-new="op:' + s + '">' + s + '</span>'; }).join('') +
      '</div></div></div>' +
      '<div class="fx-strip-wrap"><div class="fx-strip" data-strip></div>' +
      '<button class="fx-clear" type="button" data-clear title="Очистить формулу" aria-label="Очистить формулу">×</button></div>' +
      '<p class="fx-trash-hint">Перетащите блок в строку или нажмите на него · вытащите из строки, чтобы убрать · нажмите на блок в строке, чтобы настроить</p>' +
      '<div class="fx-check-box"><h3>Как посчитается <span class="fx-badge" data-check-badge>на числах прошлого месяца</span> <span class="fx-badge" data-state-badge></span></h3>' +
      '<div class="fx-check" data-check></div></div>' +
      '<div class="fx-acts"><button class="fx-btn" type="button" data-cancel>Отмена</button><button class="fx-btn is-primary" type="button" data-done>Готово</button></div>' +
      '</div>';
    host.appendChild(overlay);
    var strip = overlay.querySelector('[data-strip]');

    function chipText(b) {
      if (b.type === 'op') return b.op;
      if (b.type === 'meter') {
        var short = shortOf(b.key);
        if (!b.meters.length) return short + ' · ?';
        if (b.meters.length === 1) return short + ' · ' + whoShort(b.meters[0]);
        if (modeNow() === 'total' || b.join === 'sum') {
          var all = METERS.filter(function (m) { return m.key === b.key; }).length === b.meters.length;
          return short + ' · ' + (all ? 'все вместе' : b.meters.map(whoShort).join(' + '));
        }
        return short + ' · у каждого';
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
      if (b.type === 'meter') { var short = shortOf(b.key); return [short, chipText(b).slice(short.length + 3) + ' · ' + kindOf(b.key).unit]; }
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

    function renderPalette() {
      ['month', 'const'].forEach(function (type) {
        var box = overlay.querySelector('[data-pal="' + type + '"]');
        box.innerHTML = '';
        values.filter(function (v) { return v.type === type; }).forEach(function (v) {
          var b = { type: 'val', vid: v.id };
          var tile = tileEl('val:' + v.id, kindClass(b), iconOf(b), v.label, chipValue(b) || 'без единицы');
          tile.insertAdjacentHTML('beforeend', '<span class="fx-del" title="Удалить число" aria-label="Удалить число «' + esc(v.label) + '»">×</span>');
          box.appendChild(tile);
        });
        box.appendChild(tileEl('new:' + type, 'k-new ' + (type === 'const' ? 'k-const' : 'k-month'), ICONS.plus,
          type === 'const' ? 'Тариф или норматив' : 'Число или сумма', type === 'const' ? 'например, 45 ₽ за м³' : 'например, Гкал или сумма'));
      });
      var meters = overlay.querySelector('[data-pal="meter"]');
      meters.innerHTML = '';
      if (!KINDS.length) meters.innerHTML = '<p class="fx-hint">У объекта нет счётчиков — их добавляют в окне объекта.</p>';
      KINDS.forEach(function (k) {
        var on = METERS.some(function (m) { return m.key === k.key && isActive(m); });
        var tile = tileEl((on ? 'meter:' : 'off:') + k.key, 'k-meter mk-' + k.icon + (on ? '' : ' is-off'), ICONS[k.icon] || ICONS.custom, k.name,
          on ? 'расход' + (k.unit ? ', ' + k.unit : '') : 'не подключён к услуге');
        if (!on) tile.title = offKindText(k.key);
        meters.appendChild(tile);
      });
    }

    function render() {
      strip.innerHTML = '';
      if (!blocks.length) strip.innerHTML = '<span class="fx-empty">Перетащите сюда блоки — например, Вода гор. + Вода хол. × Тариф</span>';
      blocks.forEach(function (b) {
        var el = chipEl(b);
        el.insertAdjacentHTML('beforeend', '<span class="fx-del" title="Убрать из формулы" aria-label="Убрать из формулы">×</span>');
        strip.appendChild(el);
      });
      strip.querySelectorAll('.fx-nm, .fx-s2').forEach(function (e) { e.classList.toggle('is-cut', e.scrollWidth > e.clientWidth + 1); });
      renderPalette();
      renderCheck();
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
        if (b.meters.length > 1 && tenantId !== null && b.join !== 'sum') ids = b.meters.filter(function (id) { return tenantOf(id) === tenantId; });
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
        return r;
      } catch (msg) { return { error: String(msg) }; }
    }

    function renderCheck() {
      var box = overlay.querySelector('[data-check]');
      var badge = overlay.querySelector('[data-state-badge]');
      box.innerHTML = '';
      if (!blocks.length) {
        badge.textContent = ''; badge.className = 'fx-badge';
        box.innerHTML = '<p class="fx-hint">Соберите формулу — здесь появится расчёт для каждого арендатора.</p>';
        return;
      }
      function line(who, parts, sum, bad, tid) {
        var d = document.createElement('div');
        var switchable = tid && payBox(tid);
        d.className = 'fx-line' + (switchable ? ' has-pay' : '') + (switchable && isOff(tid) ? ' is-off' : '');
        var html;
        if (typeof parts === 'string') html = '<span class="fx-note' + (bad ? ' is-err' : '') + '">' + esc(parts) + '</span>';
        else html = parts.map(function (x) {
          return x.op ? '<span class="fx-op' + ('()'.indexOf(x.op) >= 0 ? ' is-paren' : '') + '">' + x.op + '</span>'
            : '<span class="fx-n" title="' + esc(x.word) + '"><b>' + esc(x.num) + '</b><i>' + esc(x.word) + (x.sample ? ' · пример' : '') + '</i></span>';
        }).join('') + (sum ? '<span class="fx-eq"><span class="fx-op">=</span> <span class="fx-res">' + esc(sum) + '</span></span>' : '');
        d.innerHTML = '<span class="fx-who"></span><span class="fx-calc">' + html + '</span>';
        d.querySelector('.fx-who').textContent = who;
        if (switchable) {
          d.insertAdjacentHTML('beforeend', '<button type="button" class="fx-pay' + (isOff(tid) ? '' : ' is-on') + '" data-pay="' + tid +
            '" role="switch" aria-checked="' + !isOff(tid) + '" title="' + (isOff(tid) ? 'Не платит' : 'Платит') + '"><span></span></button>');
        }
        box.appendChild(d);
      }
      function hint(text, cls) { var h = document.createElement('p'); h.className = 'fx-hint' + (cls ? ' ' + cls : ''); h.textContent = text; box.appendChild(h); return h; }
      var ok = true;
      if (modeNow() === 'each') {
        var meterBlocks = blocks.filter(function (b) { return b.type === 'meter'; });
        var own = meterBlocks.filter(function (b) { return b.meters.length > 1 && b.join === 'each'; });
        var named = [];
        meterBlocks.forEach(function (b) { if (b.meters.length === 1 && tenantOf(b.meters[0]) && named.indexOf(tenantOf(b.meters[0])) < 0) named.push(tenantOf(b.meters[0])); });
        var payers = own.length ? TENANTS.filter(function (t) { return own.every(function (b) { return b.meters.some(function (id) { return tenantOf(id) === t.id; }); }); }).map(function (t) { return t.id; })
          : named;
        if (!own.length && named.length > 1) {
          ok = false;
          line('Кому?', 'В формуле счётчики разных арендаторов — непонятно, кому выставить. Отметьте у счётчика обоих и выберите «у каждого свой» или «складываем».', '', true);
        } else if (own.length && !payers.length) {
          ok = false;
          line('Кому?', 'Ни у одного арендатора нет своего счётчика в формуле — укажите у счётчиков, чьи они.', '', true);
        } else {
          TENANTS.forEach(function (t) {
            if (payers.indexOf(t.id) < 0) { line(t.name, 'не платит — нет его счётчика в формуле', ''); return; }
            if (isOff(t.id)) { line(t.name, 'не платит — его часть на вас', '', false, t.id); return; }
            var r = evaluate(t.id);
            if (r.error) { ok = false; line(t.name, r.error, '', true, t.id); }
            else line(t.name, r.parts, rub(r.v, SYM), false, t.id);
          });
        }
      } else {
        var r = evaluate(null);
        if (r.error) { ok = false; line('Объект', r.error, '', true); }
        else if (!TENANTS.length) {
          line('Вы', r.parts, rub(r.v, SYM));
        } else {
          line('Объект', r.parts, rub(r.v, SYM));
          var split = splitNow();
          var paying = TENANTS.filter(function (t) { return !isOff(t.id); }).length;
          var owner = r.v;
          TENANTS.forEach(function (t) {
            if (split === 'owner') { line(t.name, 'не платит — «Плачу сам»', ''); return; }
            if (isOff(t.id)) { line(t.name, 'не платит — его часть на вас', '', false, t.id); return; }
            var whole = { num: rub(r.v, SYM), word: 'на объект' };
            var part, parts;
            if (split === 'equal') { part = r.v / paying; parts = [whole, { op: '÷' }, { num: String(paying), word: paying === 1 ? 'платит один' : 'платят' }]; }
            else if (split === 'area') {
              part = ctx.area ? r.v * (t.area || 0) / ctx.area : 0;
              parts = [whole, { op: '×' }, { num: fmt(t.area || 0) + ' м²', word: 'его площадь' }, { op: '÷' }, { num: fmt(ctx.area || 0) + ' м²', word: 'площадь объекта' }];
            } else { part = r.v * t.share / 100; parts = [whole, { op: '×' }, { num: fmt(t.share) + '%', word: 'доля' }]; }
            owner -= part;
            line(t.name, parts, rub(part, SYM), false, t.id);
          });
          if (owner > 0.004) line('На вас', [{ num: rub(owner, SYM), word: split === 'owner' ? 'вся сумма' : 'не платит / не сдано' }], '');
          hint(split === 'owner' ? 'Всю сумму платите вы. Как делить, выбираете в окне услуги, под формулой.'
            : 'Формула даёт одну сумму на объект — она делится ' + ({ shares: 'по долям', equal: 'поровну', area: 'по м²' }[split] || 'по долям') +
              '. Как делить, выбираете в окне услуги, под формулой.');
        }
      }
      if (ok && evaluate(modeNow() === 'each' && TENANTS.length ? TENANTS[0].id : null).bare) {
        hint('У одного из чисел не указана единица — проверку «итог в рублях» для этой формулы не делаем.');
      }
      var samples = values.filter(function (v) { return v.type === 'month' && !v.real && blocks.some(function (b) { return b.vid === v.id; }); });
      var sampleMeters = blocks.some(function (b) { return b.type === 'meter' && b.meters.some(usageIsSample); });
      overlay.querySelector('[data-check-badge]').textContent = samples.length || sampleMeters ? 'на примерных числах' : 'на числах прошлого месяца';
      if (samples.length || sampleMeters) {
        var words = samples.map(function (v) { return v.label + ' ' + fmt(v.sample) + (v.unit ? ' ' + v.unit : ''); });
        if (sampleMeters) words.push('расход счётчиков без показаний');
        var h = hint('Прошлого месяца ещё нет — для примера взяли ' + words.join(', ') + '.', 'fx-sample-note');
        box.prepend(h);
      }
      badge.textContent = ok ? 'считается' : 'есть ошибка';
      badge.className = 'fx-badge ' + (ok ? 'is-ok' : 'is-bad');
    }

    // ---------- Drag and drop (mouse and finger), click to add ----------
    var drag = null, justDragged = false;
    var caret = document.createElement('span'); caret.className = 'fx-caret';
    function insertBlock(b, at) { blocks.splice(at === undefined ? blocks.length : at, 0, b); render(); }
    function insertIndex(x, y) {
      var chips = Array.prototype.slice.call(strip.querySelectorAll('.fx-chip:not(.is-dragging)'));
      for (var n = 0; n < chips.length; n++) {
        var r = chips[n].getBoundingClientRect();
        if (y < r.top - 4) return n;
        if (y <= r.bottom + 4 && x < r.left + r.width / 2) return n;
      }
      return chips.length;
    }
    function overStrip(x, y) { var r = strip.getBoundingClientRect(); return x >= r.left - 12 && x <= r.right + 12 && y >= r.top - 12 && y <= r.bottom + 12; }

    overlay.addEventListener('pointerdown', function (e) {
      if (e.target === overlay) { closeFormula(false); return; }
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
      if ((chip.dataset.new || '').indexOf('off:') === 0) {
        // Not connected to any service: it can't be taken — say why and how to fix it.
        e.preventDefault();
        openNote(chip, 'Счётчик пока не подключён', offKindText(chip.dataset.new.slice(4)));
        return;
      }
      var inStrip = strip.contains(chip);
      if (!inStrip && !chip.dataset.new) return;
      e.preventDefault();
      closePop();
      drag = { chip: chip, fromStrip: inStrip, startX: e.clientX, startY: e.clientY, moved: false };
    });
    overlay.addEventListener('pointermove', function (e) {
      if (!drag) return;
      if (!drag.moved && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) < 5) return;
      if (!drag.moved) {
        drag.moved = true;
        var kind = drag.chip.dataset.new || '';
        drag.block = drag.fromStrip ? blocks.find(function (b) { return String(b.id) === drag.chip.dataset.id; })
          : kind.indexOf('new:') === 0 ? { id: 0, type: 'new', kind: kind.slice(4) } : make(kind);
        drag.ghost = drag.block.type === 'new' ? drag.chip.cloneNode(true) : chipEl(drag.block);
        drag.ghost.classList.add('is-ghost'); overlay.appendChild(drag.ghost);
        if (drag.fromStrip) drag.chip.classList.add('is-dragging');
      }
      drag.ghost.style.left = (e.clientX - 20) + 'px'; drag.ghost.style.top = (e.clientY - 15) + 'px';
      var over = overStrip(e.clientX, e.clientY);
      strip.classList.toggle('is-over', over);
      caret.remove();
      if (over) {
        var chips = Array.prototype.slice.call(strip.querySelectorAll('.fx-chip:not(.is-dragging)'));
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
        if (kind.indexOf('new:') === 0) openDraft(kind.slice(4), d.chip);
        else if (!d.fromStrip) insertBlock(make(kind));
        else openPop(blocks.find(function (b) { return String(b.id) === d.chip.dataset.id; }), d.chip);
        return;
      }
      d.ghost.remove();
      justDragged = true; setTimeout(function () { justDragged = false; }, 0);
      var over = overStrip(e.clientX, e.clientY);
      var at = over ? insertIndex(e.clientX, e.clientY) : -1;
      if (d.block.type === 'new') { if (over) openDraft(d.block.kind, d.chip, at); return; }
      if (d.fromStrip) blocks = blocks.filter(function (b) { return b !== d.block; });  // moved or dragged out (= deleted)
      if (over) blocks.splice(Math.min(at, blocks.length), 0, d.block);
      render();
    });
    overlay.querySelector('[data-clear]').addEventListener('click', function () { closePop(); blocks = []; render(); });

    // ---------- Examples: a ready formula from this object's own meters; its numbers go to the palette ----------
    // A number of an example is taken from the palette when it is already there (by its name) — pressing twice adds nothing.
    function exampleValue(type, props) {
      return values.find(function (v) { return v.type === type && v.label === props.label; }) ||
        newValue(type, Object.assign({ sample: type === 'month' ? sampleFor(props.unit) : 0 }, props));
    }
    function val(v) { return { id: ++uid, type: 'val', vid: v.id }; }
    function op(sign) { return make('op:' + sign); }
    function meterSum(key) { var b = make('meter:' + key); b.join = 'sum'; return b; }
    var EXAMPLES = {
      sewage: { needs: ['hot_water', 'water'], build: function () {
        var t = exampleValue('const', { label: 'Тариф водоотведения', value: 45, unit: '₽', per: 'м³' });
        return [op('('), make('meter:hot_water'), op('+'), make('meter:water'), op(')'), op('×'), val(t)];
      } },
      usage: { needs: ['electricity'], build: function () {
        var sum = exampleValue('month', { label: 'Сумма по квитанции', unit: '₽' });
        return [val(sum), op('÷'), meterSum('electricity'), op('×'), make('meter:electricity')];
      } },
      heat: { needs: ['hot_water'], build: function () {
        var heat = exampleValue('month', { label: 'Тепло по квитанции', unit: 'Гкал' });
        var per = exampleValue('const', { label: 'Подогрев 1 м³', value: 0.06, unit: 'Гкал', per: 'м³' });
        var tariff = exampleValue('const', { label: 'Тариф тепла', value: 4800, unit: '₽', per: 'Гкал' });
        return [op('('), val(heat), op('−'), op('('), meterSum('hot_water'), op('×'), val(per), op(')'), op(')'), op('×'), val(tariff)];
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
        var b = make('meter:electricity'); b.meters = [meter.id];
        return [b, op('×'), val(t)];
      } },
    };
    overlay.querySelector('.fx-examples').addEventListener('click', function (e) {
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
    overlay.querySelector('[data-check]').addEventListener('click', function (e) {
      var b = e.target.closest('[data-pay]'); if (!b) return;
      var box = payBox(b.dataset.pay); if (!box) return;
      box.checked = !box.checked;
      box.dispatchEvent(new Event('change', { bubbles: true }));
      render();
    });

    // ---------- The small windows: a number's setup, a meter's «чей расход» ----------
    var pop = null;
    function closePop() { closeUnitMenu(); if (pop) pop.remove(); pop = null; }
    function placePop(anchor) {
      var r = anchor.getBoundingClientRect();
      pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8)) + 'px';
      var h = pop.offsetHeight;
      pop.style.top = (r.bottom + 8 + h > innerHeight ? Math.max(8, r.top - h - 8) : r.bottom + 8) + 'px';
    }
    function valueSays(v) {
      var n = v.type === 'const' ? fmt(v.value) : 'число';
      var one = v.per ? ' за 1 ' + v.per : '';
      if (v.type === 'month') {
        if (!v.unit) return 'Каждый месяц на странице объекта вводите число (без единицы итог в рублях не проверяем).';
        return 'Каждый месяц на странице объекта вводите ' + (v.unit === '₽' ? 'сумму в ₽' : 'сколько ' + v.unit) + ' — например, из квитанции.';
      }
      if (!v.unit) return 'Просто число ' + n + ' — например, коэффициент. Без единицы итог в рублях не проверяем.';
      if (v.unit === '₽') return v.per ? 'Это тариф: ' + n + ' ₽' + one + '.' : 'Это сумма: ' + n + ' ₽ каждый месяц.';
      return v.per ? 'Это норматив: ' + n + ' ' + v.unit + ' на 1 ' + v.per + '.' : 'Это количество: ' + n + ' ' + v.unit + '.';
    }
    function unitButton(key, cur) { return '<button type="button" class="fx-usel" data-k="' + key + '" data-v="' + esc(cur || '') + '"><span>' + esc(cur || '—') + '</span>' + CHEV + '</button>'; }
    function valueFields(v) {
      var num = function (n) { return String(n).replace('.', ','); };
      var name = '<label class="fx-f">Название<input data-k="label" value="' + esc(v.label) + '" placeholder="' +
        (v.type === 'const' ? 'Например, Тариф тепло' : 'Например, Тепло по квитанции') + '"><small>Так подписано на странице объекта и в счёте</small></label>';
      if (v.type === 'month') {
        return name + '<div class="fx-f">Цифра для проверки формулы<div class="fx-vrow is-one"><span class="fx-vfield">' +
          '<input data-k="sample" class="fx-sample" disabled value="' + num(v.sample || sampleFor(v.unit)) + '">' + unitButton('unit', v.unit) +
          '</span></div></div><p class="fx-say">' + valueSays(v) + '</p>';
      }
      return name + '<div class="fx-f">Сколько<div class="fx-vrow"><span class="fx-vfield">' +
        '<input data-k="value" inputmode="decimal" value="' + (v.value ? num(v.value) : '') + '" placeholder="0">' + unitButton('unit', v.unit) +
        '</span><span>за</span>' + unitButton('per', v.per) + '</div></div><p class="fx-say">' + valueSays(v) + '</p>';
    }
    // The number's fields write into v; «change» of a unit refreshes the sample and the sentence.
    function wireValue(v, onChange) {
      pop.addEventListener('input', function (ev) {
        var key = ev.target.dataset.k; if (!key || ev.target.tagName !== 'INPUT') return;
        var val = ev.target.value;
        if (key === 'value') val = toNumber(val);
        v[key] = val;
        pop.querySelector('.fx-say').textContent = valueSays(v);
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
            pop.querySelector('.fx-say').textContent = valueSays(v);
            onChange();
          });
        });
      });
    }
    // A new number is set up first — next to the palette — then kept («Сохранить») or put in the formula.
    function openDraft(type, anchor, at) {
      closePop();
      var v = { id: '', type: type, label: '', unit: '₽', per: '', value: 0, sample: 0, real: false };
      if (type === 'month') v.sample = sampleFor(v.unit);
      pop = document.createElement('div'); pop.className = 'fx-pop';
      pop.innerHTML = '<h4>' + (type === 'const' ? 'Новый тариф или норматив' : 'Новое число или сумма — каждый месяц') + '</h4>' + valueFields(v) +
        '<div class="fx-acts"><button type="button" class="fx-btn" data-cancel>Отмена</button><button type="button" class="fx-btn" data-keep disabled title="Сохранить в палитру, поставить в формулу потом">Сохранить</button>' +
        '<button type="button" class="fx-btn is-primary" data-put disabled>В формулу</button></div>';
      overlay.appendChild(pop);
      placePop(anchor);
      var ready = function () { pop.querySelectorAll('[data-keep], [data-put]').forEach(function (btn) { btn.disabled = !String(v.label).trim(); }); };
      wireValue(v, ready);
      function save() { return newValue(type, { label: v.label.trim(), unit: v.unit, per: v.per, value: v.value, sample: v.sample }); }
      pop.querySelector('[data-cancel]').onclick = closePop;
      pop.querySelector('[data-keep]').onclick = function () { save(); closePop(); render(); };
      pop.querySelector('[data-put]').onclick = function () { var saved = save(); closePop(); insertBlock({ id: ++uid, type: 'val', vid: saved.id }, at); };
      pop.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && !pop.querySelector('[data-put]').disabled) { ev.preventDefault(); pop.querySelector('[data-put]').click(); } });
      pop.querySelector('[data-k="label"]').focus();
    }

    function meterPopBody(b) {
      var k = kindOf(b.key), u = k.unit ? ' ' + k.unit : '';
      var many = b.meters.length > 1;
      // Each meter of this kind: a connected one — a tick, whose it is and where its readings are typed («чей» is changed
      // there); one no service types — greyed, a click says why it can't be taken.
      var rows = METERS.filter(function (m) { return m.key === b.key; }).map(function (m) {
        var num = '<span>№ ' + esc(m.serial || '—') + (m.dn ? ' · день / ночь' : '') + '</span>';
        if (!isActive(m)) {
          return '<div class="fx-mrow is-off" data-off="' + m.id + '" title="' + esc(offText(m)) + '"><input type="checkbox" disabled>' + num +
            '<span class="fx-locked">не подключён к услуге</span></div>';
        }
        return '<label class="fx-mrow"><input type="checkbox" data-meter="' + m.id + '"' + (b.meters.indexOf(m.id) >= 0 ? ' checked' : '') + '>' + num +
          '<span class="fx-locked" title="Показания вводятся в услуге «' + esc(m.typed[0]) + '», там же меняется, чей счётчик">' +
          esc(whoLabel(m.id)) + ' · в «' + esc(m.typed[0]) + '»</span></label>';
      }).join('');
      var example;
      if (!b.meters.length) example = 'Отметьте хотя бы один счётчик.';
      else if (!many) {
        var t = tenantById(tenantOf(b.meters[0]));
        example = t ? 'Только ' + t.name + ': ' + fmt(usageOf(b.meters[0])) + u + '. Остальные по этой формуле не платят.'
          : 'Один счётчик: ' + fmt(usageOf(b.meters[0])) + u + ' — одно число для всех.';
      } else if (b.join === 'sum') {
        example = b.meters.map(function (id) { return fmt(usageOf(id)); }).join(' + ') + ' = ' +
          fmt(b.meters.reduce(function (s, id) { return s + usageOf(id); }, 0)) + u + ' — одно число в формуле для всех.';
      } else {
        example = b.meters.map(function (id) { return whoShort(id) + ' — ' + fmt(usageOf(id)) + u; }).join(' · ') + ' — каждому по его счётчику.';
      }
      return '<div class="fx-meter-body"><div class="fx-f">Какие счётчики и чьи</div><div class="fx-mrows">' + rows + '</div>' +
        '<div class="fx-seg' + (many ? '' : ' is-off') + '">' +
        [['each', 'У каждого свой'], ['sum', 'Складываем']].map(function (p) {
          return '<button type="button" data-join="' + p[0] + '"' + (b.join === p[0] ? ' class="is-on"' : '') + (many ? '' : ' disabled') + '>' + p[1] + '</button>';
        }).join('') + '</div><p class="fx-example">' + esc(example) + '</p></div>';
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
      } else {
        pop.innerHTML = '<h4>' + esc(kindOf(b.key).name) + ' — расход за месяц</h4>' + meterPopBody(b);
      }
      pop.insertAdjacentHTML('beforeend', '<div class="fx-acts"><button type="button" class="fx-btn is-danger" data-del>Убрать из формулы</button><button type="button" class="fx-btn is-primary" data-ok>Готово</button></div>');
      overlay.appendChild(pop);
      placePop(anchor);
      if (b.type === 'val') wireValue(valueOf(b), render);
      else wireMeter(b);
      pop.querySelector('[data-ok]').onclick = closePop;
      pop.querySelector('[data-del]').onclick = function () { blocks = blocks.filter(function (x) { return x !== b; }); closePop(); render(); };
    }
    function wireMeter(b) {
      function redraw() { pop.querySelector('.fx-meter-body').outerHTML = meterPopBody(b); wireWho(); render(); }
      function wireWho() {
        pop.querySelectorAll('[data-who]').forEach(function (btn) {
          btn.addEventListener('click', function (ev) {
            ev.preventDefault();
            var id = Number(btn.dataset.who);
            var options = [['', 'Общий']].concat(TENANTS.map(function (t) { return [String(t.id), t.name]; }), [['free', 'Собственник']]);
            openMenu(btn, options, owners[id] || '', false, function (value) { owners[id] = value; redraw(); });
          });
        });
      }
      pop.addEventListener('change', function (ev) {
        if (ev.target.dataset.meter === undefined) return;
        var id = Number(ev.target.dataset.meter);
        b.meters = ev.target.checked ? METERS.filter(function (m) { return m.key === b.key && (m.id === id || b.meters.indexOf(m.id) >= 0); }).map(function (m) { return m.id; })
          : b.meters.filter(function (x) { return x !== id; });
        redraw();
      });
      pop.addEventListener('click', function (ev) {
        var off = ev.target.closest('[data-off]');
        if (off) {
          // The explanation right in this window, where the example usually is.
          var note = pop.querySelector('.fx-example');
          note.textContent = offText(meterById(Number(off.dataset.off)));
          note.classList.add('is-warn');
          return;
        }
        var btn = ev.target.closest('[data-join]'); if (!btn || btn.disabled) return;
        b.join = btn.dataset.join; redraw();
      });
      wireWho();
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
    function openMenu(btn, options, cur, custom, pick) {
      var was = btn.classList.contains('is-open');
      closeUnitMenu(); if (was) return;
      btn.classList.add('is-open');
      var m = document.createElement('div'); m.className = 'fx-umenu'; m.setAttribute('role', 'listbox');
      m.innerHTML = options.map(function (o) {
        return '<button type="button" role="option" data-v="' + esc(o[0]) + '"' + (o[0] === cur ? ' class="is-on"' : '') + '>' +
          (o[0] || !custom ? esc(o[1]) : '<span class="fx-none">' + esc(o[1]) + '</span>') + '</button>';
      }).join('') + (custom ? '<div class="fx-ucustom"><input placeholder="свой вариант…" maxlength="12"><button type="button" title="Добавить">✓</button></div>' : '');
      overlay.appendChild(m);
      var r = btn.getBoundingClientRect();
      m.style.minWidth = Math.max(r.width, 150) + 'px';
      m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + 'px';
      m.style.top = (r.bottom + 4 + m.offsetHeight > innerHeight ? r.top - 4 - m.offsetHeight : r.bottom + 4) + 'px';
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
    if (host.tagName === 'DIALOG') host.addEventListener('cancel', function (e) { if (!overlay.hidden) { e.preventDefault(); closeFormula(false); } });

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
    }
    function serialize() {
      return JSON.stringify({
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
      });
    }
    function publish() {
      var json = serialize();
      var changed = jsonInput.value !== json;
      jsonInput.value = json;
      summaryEl.textContent = blocks.length ? 'Формула: ' + blocks.map(chipText).join(' ').replace(/\( /g, '(').replace(/ \)/g, ')') : 'Формула ещё не собрана';
      summaryEl.title = summaryEl.textContent;
      summaryEl.classList.toggle('is-empty', !blocks.length);
      openBtn.textContent = blocks.length ? 'Изменить формулу' : 'Собрать формулу';
      form.classList.toggle('is-formula-each', modeNow() === 'each');
      if (changed) jsonInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    openBtn.addEventListener('click', openFormula);
    overlay.querySelector('[data-cancel]').addEventListener('click', function () { closeFormula(false); });
    overlay.querySelector('[data-done]').addEventListener('click', function () { closeFormula(true); });
    // «Делим» and the «платит» switches live in the service window: the check follows them when it opens.
    publish();
    // A refused save of an unfinished formula: open the window again so the error is right there.
    if (panel.querySelector('.calc-error') && blocks.length && form.querySelector('input[name=charge][value=formula]:checked')) openFormula();
  }

  window.initFormula = function (root) {
    (root || document).querySelectorAll('[data-formula-panel]').forEach(function (panel) {
      if (panel.dataset.ready) return;
      panel.dataset.ready = '1';
      setup(panel);
    });
  };
  window.initFormula(document);
})();
