// A meter tile drawn as a real meter (2026-11-27, макет docs/mockups/2026-11-27-meter-tiles-dial.html, вариант В):
// water — a round body with «ears», electricity and gas — a square one, the rim in the kind's colour; inside the short
// kind (ХВС), the drums (the last «стало», only the last drum red), the tariff, «№ …», whose it is. One look for the
// object window (app.js) and «Выберите счётчики» of the service window (services.js).
(function () {
  'use strict';
  var SHORT = { electricity: 'Э/Э', water: 'ХВС', hot_water: 'ГВС', gas: 'ГАЗ', heating: 'Т/Э' };
  var SQUARE = { electricity: true, gas: true, heating: true };
  var LEGAL = /^(ИП|ООО|ОАО|ЗАО|ПАО|АО|НКО|Арендатор)$/i;

  function esc(text) {
    return String(text == null ? '' : text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  // «Салон "Ногти"» → «Салон», «ИП Иванов» → «Иванов»; a long word — 8 letters and «.»
  function shortWho(name) {
    var words = String(name || '').replace(/[«»"']/g, ' ').split(/\s+/).filter(function (w) { return w && !LEGAL.test(w); });
    var first = words[0] || String(name || '');
    return first.length > 9 ? first.slice(0, 8) + '.' : first;
  }
  // «478.2» → 0 0 4 7 8 | 2 (red): five drums at least, the tenths in the last one
  function drums(value, label) {
    var parts = String(value).replace(',', '.').replace(/\s/g, '').replace('-', '').split('.');
    var whole = parts[0] || '0';
    if (whole.length < 5) whole = ('00000' + whole).slice(-5);
    var tenth = (parts[1] || '0').charAt(0);
    return '<span class="md-odo">' + (label ? '<i>' + label + '</i>' : '') +
      whole.split('').map(function (c) { return '<b>' + c + '</b>'; }).join('') + '<b class="is-red">' + tenth + '</b></span>';
  }

  // o: {kind, name, serial, tariff, dial ('478.2' | '12451.6|4120.3' | ''), who: {text, cls, title}, cls, attrs, corner, title}
  function tile(o, tag) {
    var kind = o.kind || 'custom';
    var dial = String(o.dial || '');
    var odo = !dial ? '<span class="md-none">нет показаний</span>'
      : dial.indexOf('|') >= 0 ? '<span class="md-odos">' + drums(dial.split('|')[0], 'д') + drums(dial.split('|')[1], 'н') + '</span>'
      : drums(dial);
    var who = o.who || {};
    tag = tag || 'div';
    return '<' + tag + ' class="md-tile mk-' + esc(kind) + (SQUARE[kind] ? ' is-sq' : '') + (o.cls ? ' ' + o.cls : '') + '"' +
      (o.title ? ' title="' + esc(o.title) + '"' : '') + (o.attrs || '') + '>' +
      '<span class="md-ears"></span><span class="md-body">' +
      '<span class="md-kind">' + esc(SHORT[kind] || o.name || '') + '</span>' + odo +
      '<span class="md-tar' + (o.tariff ? '' : ' is-none') + '">' + esc(o.tariff || 'нет тарифа') + '</span>' +
      '<span class="md-no">№ ' + esc(o.serial || '—') + '</span>' +
      (who.text ? '<span class="who-badge md-who ' + (who.cls || '') + '"' + (who.title ? ' title="' + esc(who.title) + '"' : '') + '>' + esc(who.text) + '</span>' : '') +
      '</span>' + (o.corner || '') + '</' + tag + '>';
  }

  window.rentflowDial = { tile: tile, shortWho: shortWho, short: SHORT };
})();
