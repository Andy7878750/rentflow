/* «Услуги · <объект>» (2026-11-19): every service of the object in one window, saved by itself.
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
  function meterIcon(kind) { return '<span class="sv-mkind mk-' + esc(kind || 'custom') + '">' + sprite(kind) + '</span>'; }
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
    // After «Сохранить» or «Удалить» — a new service «По квитанции», ready for its name (the user's wish, 2026-11-19).
    function nextNew() {
      startNew('receipt');
      unitOpen = false; exampleOpen = false; meterOpen = null; confirmDelete = false;
      render(); pane.scrollTop = 0;
      var input = pane.querySelector('[data-f="name"]'); if (input) input.focus();
    }

    function byId(list, id) { return list.filter(function (x) { return x.id === id; })[0]; }
    function copy(s) { return JSON.parse(JSON.stringify(s)); }
    function tname(id) { var t = byId(T, id); return t ? t.name : ''; }
    function modeName(mode) { return S.modes.filter(function (m) { return m[0] === mode; })[0][1]; }

    function startNew(mode) {
      current = { id: null, isNew: true, kind: 'custom', name: '', provider: '', mode: mode, split: 'shares', excluded: [],
                  owner_takes: true, fixed: null, rate: null, unit: 'м²', volume: null, meters: [] };
      if (mode === 'meters') {
        // All the object's free meters switched on: the lazy landlord just names the service.
        current.meters = S.meters.filter(function (m) { return !m.service; }).map(function (m) { return m.id; });
        if (S.start && S.start.meter) current.meters = [S.start.meter];
      }
      editing = true;
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
    function meterPayer(m) {
      if (m.who === 'common') return 'Общий · ' + SPLITS.filter(function (x) { return x[0] === m.split; })[0][1];
      if (m.who === 'owner') return 'Вы';
      return tname(m.who) || 'Общий · по долям';
    }
    function meterList(s) {
      var rows = S.meters.map(function (m) {
        var taken = m.service && m.service !== s.id;
        var on = !taken && s.meters.indexOf(m.id) >= 0;
        var cls = taken ? ' is-taken' : on ? ' is-click' : ' is-off';
        return '<div class="sv-gp-row sv-mrow' + cls + '"' + (on ? ' data-meter="' + m.id + '" tabindex="0"' : '') + '>' +
          '<span class="sv-who">' + meterIcon(m.kind) + '<span class="sv-t">№ ' + esc(m.serial || '—') + '</span>' +
          '<span class="sv-sub fade">' + esc(m.name) + (m.dn ? ' · день / ночь' : '') + '</span></span>' +
          '<span class="sv-tariff">' + (m.tariff ? esc(m.tariff) : '<span class="sv-none">нет тарифа</span>') + '</span>' +
          '<span class="sv-payer"><span class="fade">' + (taken ? 'в «' + esc(m.service_name) + '»' : on ? esc(meterPayer(m)) : '—') + '</span>' +
          (on ? '<svg class="icon sv-chev-r"><use href="#i-chevron-right"/></svg>' : '') + '</span>' +
          (taken ? '<span></span>' : sw(on, 'data-meter-on="' + m.id + '"', 'Счётчик № ' + (m.serial || '') + ' в услуге')) + '</div>';
      }).join('');
      if (!S.meters.length) rows = '<div class="sv-gp-row"><span class="sv-who">У объекта пока нет счётчиков</span></div>';
      return '<div class="sv-gp"><div class="sv-gp-row sv-mrow sv-head"><span>Счётчик</span><span class="sv-r">Тариф</span><span>Кто платит</span><span class="sv-r">Вкл.</span></div>' +
        rows + '</div><div><a href="' + esc(S.urls.object) + '" data-modal class="sv-add-link">+ Добавить счётчик объекта</a></div>';
    }
    function meterWindow() {
      var m = byId(S.meters, meterOpen), d = draft, body;
      var seg = '<div class="sv-seg"><button type="button" data-who-kind="one"' + (d.who !== 'common' ? ' class="is-on"' : '') + '>Один арендатор</button>' +
        '<button type="button" data-who-kind="common"' + (d.who === 'common' ? ' class="is-on"' : '') + '>Общий — делим</button></div>';
      if (d.who !== 'common') {
        body = T.concat([{ id: 'owner', name: 'Никто — платите вы' }]).map(function (t, i) {
          var sel = d.who === t.id;
          return '<button type="button" class="sv-gp-row sv-pick-row' + (sel ? ' is-sel' : '') + (t.id === 'owner' ? ' is-owner' : '') + '" data-who="' + t.id + '">' +
            (t.id === 'owner' ? '<span></span>' : '<span class="sv-no">' + (i + 1) + '</span>') + '<span class="sv-who fade">' + esc(t.name) + '</span>' +
            '<span class="sv-ok">' + (sel ? svg(CP_ICON.check) : '') + '</span></button>';
        }).join('');
      } else {
        var r = shares(d.split, d.excluded, d.owner_takes);
        body = splitTop(d.split, 'data-msplit') + T.map(function (t, i) {
          var on = d.excluded.indexOf(t.id) < 0;
          return '<div class="sv-gp-row sv-mshare' + (on ? '' : ' is-off') + '"><span class="sv-no">' + (i + 1) + '</span><span class="sv-who fade">' + esc(t.name) + '</span>' +
            '<span class="sv-pc">' + (on ? Math.round(r.k[t.id] * 1000) / 10 + '%' : 'не платит') + '</span>' + sw(on, 'data-mpay="' + t.id + '"', t.name + ' платит') + '</div>';
        }).join('') + '<div class="sv-gp-row sv-mshare is-owner' + (r.canPass && r.takes ? ' is-live' : '') + '"><span></span><span class="sv-who">Остаётся на вас</span>' +
          '<span class="sv-pc">' + (r.owner > 0.00001 ? Math.round(r.owner * 1000) / 10 + '%' : '—') + '</span>' +
          (r.canPass ? sw(r.takes, 'data-mowner', 'Остаток на вас') : '<span></span>') + '</div>';
      }
      return '<div class="sv-back" data-meter-close><div class="sv-mw" role="dialog" aria-modal="true" aria-label="Кто платит по счётчику">' +
        '<div class="sv-mw-head">' + meterIcon(m.kind) + '<b>№ ' + esc(m.serial || '—') + '</b><span class="sv-sub">' + esc(m.tariff || 'нет тарифа') + '</span>' +
        '<button type="button" class="sv-x" data-meter-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
        '<div class="sv-mw-body"><div class="sv-sec"><h3>Кто платит</h3>' + seg + '</div><div class="sv-gp sv-gp-fixed">' + body + '</div></div>' +
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
          return '<div class="sv-pr">' + (j === 0 ? meterIcon(m.kind) : '<span></span>') + '<span class="sv-pr-nm">' +
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
        '<span class="sv-saved" data-saved>' + (s.id ? 'Сохранено' : 'Введите название — услуга сохранится сама') + '</span>' +
        (s.id ? '<button type="button" class="head-icon sv-del" data-delete title="Удалить услугу" aria-label="Удалить услугу">' +
          '<svg class="icon"><use href="#i-trash"/></svg></button>' : '') + '</div>' +
        // The same fields as everywhere (properties/_field.html): the label over a 38px box.
        (editing ? '<div class="sv-top-edit"><div class="field fl"><label for="sv-name">Название в счёте</label>' +
          '<input type="text" id="sv-name" data-f="name" value="' + esc(s.name) + '" placeholder=" " maxlength="100" autocomplete="off"></div>' +
          '<div class="field fl"><label for="sv-provider">Поставщик</label>' +
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
      if (s.mode === 'meters') b = cp('meters', '<span>Показания вводите <b>каждый месяц</b>, тариф — у счётчика (в окне объекта).</span>');
      if (s.mode === 'formula') {
        b = cp('meters', '<span class="fade sv-formula">' + esc(s.formula || 'Формула ещё не собрана') + '</span>' +
          '<a href="' + esc(s.id ? s.edit_url : S.urls.formula_new) + '" data-modal class="btn btn-primary btn-auto btn-sm">' + (s.id ? 'Изменить формулу' : 'Собрать формулу') + '</a>');
      }
      var warn = s.mode === 'area' ? '<span class="sv-badge-warn" title="Объём здесь постоянный. Если есть счётчик — выберите «По счётчикам»: расход возьмётся из показаний.">' +
        svg(CP_ICON.warn) + 'Не для счётчиков</span>' : '';
      h += block('Как начисляется · ' + modeName(s.mode) + warn, b);
      if (s.mode === 'receipt' || s.mode === 'fixed' || s.mode === 'area') {
        h += block('Делим и кто платит' + (s.mode === 'receipt' && T.length ? '<span class="sv-badge-sample">для примера ' + money(SAMPLE).replace(',00', '') + '</span>' : ''), payRows(s));
      } else if (s.mode === 'meters') {
        h += block('Счётчики объекта', meterList(s));
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
        '<button type="button" class="btn btn-primary btn-auto" data-save-next>Сохранить</button></div>';
      if (confirmDelete) {
        h += '<div class="sv-back" data-del-close><div class="sv-mw" role="dialog" aria-modal="true" aria-label="Удалить услугу">' +
          '<div class="sv-mw-head"><b>Удалить услугу?</b><button type="button" class="sv-x" data-del-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></div>' +
          '<div class="sv-mw-body"><p class="sv-note">«' + esc(s.name) + '» больше не будет в счетах; её суммы и тарифы удалятся. Счётчики объекта и их показания останутся.</p></div>' +
          '<div class="sv-mw-foot"><button type="button" class="btn btn-ghost btn-auto" data-del-close>Отмена</button>' +
          '<button type="button" class="btn btn-danger btn-auto" data-del-yes>Удалить</button></div></div></div>';
      }
      if (meterOpen != null) h += meterWindow();
      pane.innerHTML = h;
    }
    function render() { renderNav(); renderPane(); }

    // ---------- saving ----------
    var timer = null, saving = false, again = false, closed = false, afterSave = null;
    // «Сохранить»: send now (or wait for the save on its way), then go on.
    function saveThen(next) {
      if (!String(current.name || '').trim()) {
        editing = true; renderPane();
        status('Введите название услуги', 'is-error');
        pane.querySelector('[data-f="name"]').focus();
        return;
      }
      afterSave = next;
      save(true);
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
        data.meters = S.meters.map(function (m) {
          return { id: m.id, on: s.meters.indexOf(m.id) >= 0, who: m.who, split: m.split, excluded: m.excluded, owner_takes: m.owner_takes };
        });
      }
      return data;
    }
    function save(now) {
      if (!current || !String(current.name || '').trim()) return;
      clearTimeout(timer);
      timer = null;
      if (!now) { timer = setTimeout(function () { timer = null; save(true); }, 500); return; }
      if (saving) { again = true; return; }
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
        dirty = true;
        var fresh = answer.json;
        S.services = fresh.services;
        S.own_units = fresh.own_units;
        // The meters: who uses which (the window keeps its own choices of who pays).
        fresh.meters.forEach(function (m) { var mine = byId(S.meters, m.id); if (mine) { mine.service = m.service; mine.service_name = m.service_name; } });
        if (sent.isNew) { sent.id = fresh.selected; sent.isNew = false; }
        var saved = byId(S.services, sent.id);
        if (saved) { sent.kind = saved.kind; sent.edit_url = saved.edit_url; sent.delete_url = saved.delete_url; }
        renderNav();
        if (current === sent && !pane.querySelector('[data-f]:focus')) renderPane();
        status('Сохранено ✓', 'is-on');
        clearTimeout(status.t);
        status.t = setTimeout(function () { status('Сохранено'); }, 1500);
        if (again) { again = false; save(true); return; }
        done();
        if (afterSave) { var next = afterSave; afterSave = null; next(); }
      }).catch(function () { saving = false; afterSave = null; status('Нет связи — не сохранено', 'is-error'); done(); });
    }

    // ---------- clicks ----------
    box.addEventListener('click', function (e) {
      var t;
      if ((t = e.target.closest('[data-svc]'))) {
        save(true);
        current = copy(byId(S.services, +t.dataset.svc));
        editing = false; unitOpen = false; exampleOpen = false; meterOpen = null;
        render(); pane.scrollTop = 0; return;
      }
      if ((t = e.target.closest('[data-mode]'))) {
        if (current && current.isNew && !current.name) { current.mode = t.dataset.mode; }
        else { save(true); startNew(t.dataset.mode); }
        if (current.mode === 'meters' && !current.meters.length) {
          current.meters = S.meters.filter(function (m) { return !m.service; }).map(function (m) { return m.id; });
        }
        editing = true; exampleOpen = false; meterOpen = null;
        render(); pane.scrollTop = 0;
        var input = pane.querySelector('[data-f="name"]'); if (input) input.focus();
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
          m.who = draft.who; m.split = draft.split; m.excluded = draft.excluded; m.owner_takes = draft.owner_takes;
          meterOpen = null; renderPane(); save(); return;
        }
        if ((t = e.target.closest('[data-meter-close]')) && (e.target === t || t.tagName === 'BUTTON')) { meterOpen = null; return renderPane(); }
        if ((t = e.target.closest('[data-who-kind]'))) {
          draft.who = t.dataset.whoKind === 'common' ? 'common' : (draft.who !== 'common' ? draft.who : (T[0] ? T[0].id : 'owner'));
          return renderPane();
        }
        if ((t = e.target.closest('[data-who]'))) { draft.who = t.dataset.who === 'owner' ? 'owner' : +t.dataset.who; return renderPane(); }
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
        renderPane(); save();
        var vol = pane.querySelector('[data-f="volume"]'); if (vol) vol.focus();
        return;
      }
      if (unitOpen && !e.target.closest('.sv-sel-menu')) { unitOpen = false; renderPane(); }
      if ((t = e.target.closest('[data-split]'))) { current.split = t.dataset.split; renderPane(); return save(); }
      if (e.target.closest('[data-owner]')) { current.owner_takes = current.owner_takes === false; renderPane(); return save(); }
      if ((t = e.target.closest('[data-pay]'))) { toggle(current.excluded, +t.dataset.pay); renderPane(); return save(); }
      if ((t = e.target.closest('[data-meter-on]'))) { toggle(current.meters, +t.dataset.meterOn); renderPane(); return save(); }
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
      renderPane(); save();
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
      if (f === 'name' || f === 'provider') { save(); if (f === 'name' && current.isNew) renderNav(); }
      else if (NUMS[f]) save();
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
      if (e.key === 'Escape' && (meterOpen != null || exampleOpen || unitOpen || confirmDelete)) {
        e.stopPropagation(); meterOpen = null; exampleOpen = false; unitOpen = false; confirmDelete = false; renderPane(); return;
      }
      if (e.key === 'Enter' && e.target.dataset && e.target.dataset.meter) { e.preventDefault(); openMeter(+e.target.dataset.meter); return; }
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
        if (timer) save(true);  // the last change is still waiting: send it, then show it
        else if (!saving && dirty) window.location.reload();
      });
    }

    // ---------- the start ----------
    if (S.start && S.start.mode) startNew(S.start.mode);
    else if (S.start && S.start.meter) startNew('meters');
    else if (S.selected) current = copy(byId(S.services, S.selected) || S.services[0]);
    else if (S.services.length) current = copy(S.services[0]);
    render();
    if (editing) { var first = pane.querySelector('[data-f="name"]'); if (first) first.focus(); }
  };
})();
