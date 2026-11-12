/* App-wide behaviour: modal windows, tooltips, the object form. */
(function () {
  'use strict';

  // ---------- Numbers ----------

  function parseNumber(value) {
    var text = String(value || '').replace(/\s/g, '').replace(',', '.');
    if (!text) return null;
    var number = Number(text);
    return isFinite(number) ? number : null;
  }

  function formatNumber(number) {
    var rounded = Math.round(number * 100) / 100;
    return String(rounded).replace('.', ',');
  }

  function csrfToken(form) {
    var input = form.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  // ---------- Modal ----------
  // The <dialog> covers the whole screen and scrolls itself; the white panel inside grows
  // with its content, so there is no inner scrollbar and tooltips / menus can stick out.

  var dialog = document.querySelector('[data-modal-dialog]');

  function showInModal(html) {
    hideTip();
    closeDate();
    dialog.innerHTML = html;
    initForms(dialog);
    if (!dialog.open) dialog.showModal();
    var firstError = dialog.querySelector('.errorlist');
    var target = firstError ? firstError.closest('.field, .form-section') : null;
    if (target) {
      target.scrollIntoView({ block: 'center' });
    } else {
      dialog.scrollTop = 0;
      var first = dialog.querySelector('[data-select-trigger], input:not([type=hidden]):not([type=radio])');
      if (first) first.focus();
    }
  }

  function openModal(url) {
    fetch(url, { headers: { 'X-Modal': '1' }, credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) throw new Error(response.status);
        return response.text();
      })
      .then(showInModal)
      .catch(function () { window.location.href = url; });
  }

  if (dialog) {
    document.addEventListener('click', function (event) {
      var link = event.target.closest('a[data-modal]');
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      var dropdown = link.closest('[data-dropdown]');
      if (dropdown) dropdown.removeAttribute('open');
      openModal(link.href);
    });

    // Only × and «Отмена» close the window: a stray click outside must not lose what was typed.
    dialog.addEventListener('click', function (event) {
      if (event.target.closest('[data-modal-close]')) {
        event.preventDefault();
        dialog.close();
      }
    });

    // Escape closes an open menu or tooltip, never the whole window.
    dialog.addEventListener('cancel', function (event) {
      event.preventDefault();
      hideTip();
      closeDate();
      closeSelects(null);
      closeUnitPickers(null);
    });

    dialog.addEventListener('close', function () {
      hideTip();
      closeDate();
      dialog.innerHTML = '';
    });

    dialog.addEventListener('submit', function (event) {
      var form = event.target.closest('form[data-modal-form]');
      if (!form) return;
      event.preventDefault();
      var button = form.querySelector('[type=submit]');
      if (button) button.disabled = true;
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Modal': '1' },
        credentials: 'same-origin',
      })
        .then(function (response) {
          var redirect = response.headers.get('X-Modal-Redirect');
          if (redirect) {
            window.location.href = redirect;
            return null;
          }
          return response.text();
        })
        .then(function (html) { if (html !== null) showInModal(html); })
        .catch(function () {
          if (button) button.disabled = false;
          form.removeAttribute('data-modal-form');
          form.submit();
        });
    });
  }

  // ---------- Tooltips for «?» ----------
  // A card with a title, positioned against the viewport so it can leave the window's edges.

  var tip = null;
  var tipOwner = null;

  function hideTip() {
    if (tip) tip.remove();
    if (tipOwner) tipOwner.classList.remove('is-active');
    tip = null;
    tipOwner = null;
  }

  function showTip(help) {
    if (tipOwner === help) return;
    hideTip();
    tipOwner = help;
    help.classList.add('is-active');
    tip = document.createElement('div');
    tip.className = 'tip-card';
    tip.setAttribute('role', 'tooltip');
    if (help.dataset.tipTitle) {
      var title = document.createElement('strong');
      title.textContent = help.dataset.tipTitle;
      tip.appendChild(title);
    }
    var text = document.createElement('span');
    text.textContent = help.dataset.tip;
    tip.appendChild(text);
    // Inside an open modal the card must live in the dialog (top layer), otherwise behind it.
    (help.closest('dialog') || document.body).appendChild(tip);

    var box = help.getBoundingClientRect();
    var width = tip.offsetWidth;
    var height = tip.offsetHeight;
    var margin = 8;
    var left = Math.min(box.left, window.innerWidth - width - margin);
    var top = box.bottom + margin;
    if (top + height > window.innerHeight - margin) top = box.top - height - margin;
    tip.style.left = Math.max(margin, left) + 'px';
    tip.style.top = Math.max(margin, top) + 'px';
  }

  // «?» cards, and «Базовые» of a meter: hovering the word shows the base readings typed (saved row too).
  var TIP_OWNERS = '.help[data-tip], [data-start-toggle]';

  function tipFor(owner) {
    if (!owner.matches('[data-start-toggle]')) return true;
    var start = owner.closest('[data-start]');
    if (start.classList.contains('is-open')) return false;
    var day = start.querySelector('input[name=meter_initial]').value.trim();
    var night = start.querySelector('input[name=meter_initialn]').value.trim();
    var unitInput = owner.closest('[data-meter-row]').querySelector('input[name=meter_unit]');
    var unit = (unitInput && unitInput.value) || '';
    var two = !!owner.closest('form').querySelector('input[name=zones][value="2"]:checked');
    var value = 'Не задано';
    if (two && (day || night)) value = 'день ' + (day || '—') + ' · ночь ' + (night || '—') + (unit ? ' ' + unit : '');
    else if (day) value = day + (unit ? ' ' + unit : '');
    owner.dataset.tipTitle = 'Заданное значение';
    owner.dataset.tip = value;
    return true;
  }

  document.addEventListener('mouseover', function (event) {
    var help = event.target.closest && event.target.closest(TIP_OWNERS);
    if (help && tipFor(help)) showTip(help);
    else if (tipOwner && document.activeElement !== tipOwner) hideTip();
  });
  document.addEventListener('focusin', function (event) {
    var help = event.target.closest && event.target.closest(TIP_OWNERS);
    if (help && tipFor(help)) showTip(help);
  });
  document.addEventListener('focusout', function (event) {
    if (event.target === tipOwner) hideTip();
  });
  document.addEventListener('click', function (event) {
    // Touch screens: tap «?» to toggle.
    var help = event.target.closest('.help[data-tip]');
    if (help) {
      event.preventDefault();
      if (tipOwner === help && event.detail) hideTip();
      else showTip(help);
    }
  });
  document.addEventListener('scroll', hideTip, true);
  window.addEventListener('resize', hideTip);

  // ---------- Field helpers ----------

  document.addEventListener('click', function (event) {
    var toggle = event.target.closest('[data-reveal]');
    if (!toggle) return;
    var input = toggle.parentNode.querySelector('input');
    // Dots come from the .masked class: a real password field would invite the browser's autofill.
    var showing = !input.classList.contains('masked');
    input.classList.toggle('masked', showing);
    toggle.classList.toggle('is-visible', !showing);
    toggle.setAttribute('aria-label', showing ? 'Показать подсказку' : 'Скрыть подсказку');
  });

  // Phones: Russian numbers become +7 (912) 345-67-89; any other «+code» stays as typed.
  function formatPhone(value) {
    var trimmed = value.trim();
    var digits = trimmed.replace(/\D/g, '');
    if (!digits) return trimmed.charAt(0) === '+' ? '+' : '';
    var international = trimmed.charAt(0) === '+';
    var russian = (international && digits.charAt(0) === '7') ||
                  (!international && (digits.charAt(0) === '8' || digits.charAt(0) === '7' || digits.charAt(0) === '9'));
    if (!russian) {
      // Another country: keep the person's own spacing, just drop stray characters.
      return '+' + trimmed.replace(/^\+/, '').replace(/[^\d\s()-]/g, '');
    }
    if (digits.charAt(0) === '8' || digits.charAt(0) === '7') digits = digits.slice(1);
    digits = digits.slice(0, 10);
    var out = '+7';
    if (digits.length) out += ' (' + digits.slice(0, 3);
    if (digits.length >= 3) out += ')';
    if (digits.length > 3) out += ' ' + digits.slice(3, 6);
    if (digits.length > 6) out += '-' + digits.slice(6, 8);
    if (digits.length > 8) out += '-' + digits.slice(8, 10);
    return out;
  }

  document.addEventListener('input', function (event) {
    var input = event.target;
    if (!input.matches || !input.matches('[data-phone]')) return;
    if (event.inputType && event.inputType.indexOf('delete') === 0) return; // erase freely
    // Reformat only while typing at the end; editing the middle (e.g. the country code)
    // must not throw the cursor around or force the number back to +7.
    if (input.selectionStart !== input.value.length) return;
    input.value = formatPhone(input.value);
  });

  document.addEventListener('focusout', function (event) {
    var input = event.target;
    if (input.matches && input.matches('[data-phone]') && input.value.trim()) {
      input.value = formatPhone(input.value);
    }
  });

  // ---------- Date picker ----------
  // A card under the field: month with arrows, a click on the title switches to months
  // (and years with the arrows), «Сегодня» / «Очистить» at the bottom. Always 6 rows,
  // so the card never changes height. Typing дд.мм.гггг by hand also works.

  var MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
  var MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  var picker = null; // { card, input, toggle, view: 'days' | 'months', year, month, focus }

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function formatDate(d) { return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear(); }
  function isoDate(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }

  function parseDate(value) {
    var m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(String(value || '').trim());
    if (!m) return null;
    var d = new Date(+m[3], +m[2] - 1, +m[1]);
    return d.getMonth() === +m[2] - 1 && d.getDate() === +m[1] ? d : null;
  }

  function sameDay(a, b) {
    return !!(a && b) && a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  function closeDate() {
    if (!picker) return;
    picker.card.remove();
    if (picker.toggle) picker.toggle.classList.remove('is-active');
    picker = null;
  }

  function placeDate() {
    if (!picker) return;
    var box = picker.input.getBoundingClientRect();
    var card = picker.card;
    var margin = 8;
    var left = Math.min(box.left, window.innerWidth - card.offsetWidth - margin);
    var top = box.bottom + 6;
    if (top + card.offsetHeight > window.innerHeight - margin) top = box.top - card.offsetHeight - 6;
    card.style.left = Math.max(margin, left) + 'px';
    card.style.top = Math.max(margin, top) + 'px';
  }

  function renderDate(moveFocus) {
    var p = picker;
    var selected = parseDate(p.input.value);
    var today = new Date();
    var html = '<div class="date-head">' +
      '<button type="button" class="date-nav" data-date-step="-1" aria-label="' +
        (p.view === 'days' ? 'Предыдущий месяц' : 'Предыдущий год') + '">' +
        '<svg class="icon"><use href="#i-chevron-left"/></svg></button>' +
      '<button type="button" class="date-title" data-date-view aria-label="' +
        (p.view === 'days' ? 'Выбрать месяц и год' : 'Вернуться к дням') + '">' +
        (p.view === 'days' ? MONTHS[p.month] + ' ' + p.year : p.year) +
        '<svg class="icon"><use href="#i-chevron-down"/></svg></button>' +
      '<button type="button" class="date-nav" data-date-step="1" aria-label="' +
        (p.view === 'days' ? 'Следующий месяц' : 'Следующий год') + '">' +
        '<svg class="icon"><use href="#i-chevron-right"/></svg></button>' +
      '</div>';

    if (p.view === 'days') {
      var first = new Date(p.year, p.month, 1);
      var offset = (first.getDay() + 6) % 7; // weeks start on Monday
      var focus = p.focus && p.focus.getMonth() === p.month && p.focus.getFullYear() === p.year ? p.focus
        : selected && selected.getMonth() === p.month && selected.getFullYear() === p.year ? selected
        : today.getMonth() === p.month && today.getFullYear() === p.year ? today : first;
      p.focus = focus;
      html += '<div class="date-grid" role="grid">';
      WEEKDAYS.forEach(function (name) { html += '<span class="date-weekday">' + name + '</span>'; });
      for (var i = 0; i < 42; i++) {
        var d = new Date(p.year, p.month, 1 - offset + i);
        var classes = 'date-day';
        if (d.getMonth() !== p.month) classes += ' is-outside';
        if (i % 7 >= 5) classes += ' is-weekend';
        if (sameDay(d, today)) classes += ' is-today';
        if (sameDay(d, selected)) classes += ' is-selected';
        html += '<button type="button" class="' + classes + '" data-date-pick="' + isoDate(d) + '"' +
          ' tabindex="' + (sameDay(d, focus) ? 0 : -1) + '"' +
          ' aria-label="' + d.getDate() + ' ' + MONTHS_SHORT[d.getMonth()] + ' ' + d.getFullYear() + '"' +
          (sameDay(d, selected) ? ' aria-selected="true"' : '') + '>' + d.getDate() + '</button>';
      }
      html += '</div>';
    } else {
      html += '<div class="date-months">';
      MONTHS_SHORT.forEach(function (name, index) {
        var classes = 'date-month';
        if (selected && selected.getFullYear() === p.year && selected.getMonth() === index) classes += ' is-selected';
        if (today.getFullYear() === p.year && today.getMonth() === index) classes += ' is-today';
        html += '<button type="button" class="' + classes + '" data-date-month="' + index + '">' + name + '</button>';
      });
      html += '</div>';
    }

    html += '<div class="date-foot">' +
      '<button type="button" class="date-link is-muted" data-date-clear>Очистить</button>' +
      '<button type="button" class="date-link" data-date-today>Сегодня</button></div>';

    p.card.innerHTML = html;
    p.card.classList.toggle('is-months', p.view === 'months');
    if (moveFocus) {
      var target = p.card.querySelector(p.view === 'days' ? '.date-day[tabindex="0"]' : '.date-month.is-selected, .date-month.is-today, .date-month');
      if (target) target.focus();
    }
  }

  function setDate(d) {
    var input = picker.input;
    input.value = d ? formatDate(d) : '';
    input.dispatchEvent(new Event('change', { bubbles: true }));
    closeDate();
    input.focus();
  }

  function openDate(input, moveFocus) {
    if (picker && picker.input === input) {
      if (moveFocus) renderDate(true);
      return;
    }
    closeDate();
    hideTip();
    closeSelects(null);
    var selected = parseDate(input.value);
    var base = selected || new Date();
    var card = document.createElement('div');
    card.className = 'date-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Выбор даты');
    (input.closest('dialog') || document.body).appendChild(card);
    var toggle = input.parentNode.querySelector('[data-date-toggle]');
    if (toggle) toggle.classList.add('is-active');
    picker = { card: card, input: input, toggle: toggle, view: 'days',
               year: base.getFullYear(), month: base.getMonth(), focus: selected };

    card.addEventListener('click', function (event) {
      event.stopPropagation(); // the card re-renders itself; outside-click logic must not see it
      var p = picker;
      var button = event.target.closest('button');
      if (!button || !p) return;
      if (button.hasAttribute('data-date-step')) {
        var step = +button.dataset.dateStep;
        if (p.view === 'days') {
          var shifted = new Date(p.year, p.month + step, 1);
          p.year = shifted.getFullYear();
          p.month = shifted.getMonth();
        } else {
          p.year += step;
        }
        p.focus = null;
        renderDate(false);
      } else if (button.hasAttribute('data-date-view')) {
        p.view = p.view === 'days' ? 'months' : 'days';
        renderDate(false);
      } else if (button.hasAttribute('data-date-month')) {
        p.month = +button.dataset.dateMonth;
        p.view = 'days';
        p.focus = null;
        renderDate(true);
      } else if (button.hasAttribute('data-date-pick')) {
        var parts = button.dataset.datePick.split('-');
        setDate(new Date(+parts[0], +parts[1] - 1, +parts[2]));
      } else if (button.hasAttribute('data-date-today')) {
        setDate(new Date());
      } else if (button.hasAttribute('data-date-clear')) {
        setDate(null);
      }
    });

    card.addEventListener('keydown', function (event) {
      var p = picker;
      if (!p || p.view !== 'days' || !event.target.matches('.date-day')) return;
      var moves = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
      var d = new Date(p.focus);
      if (event.key in moves) d.setDate(d.getDate() + moves[event.key]);
      else if (event.key === 'PageUp') d.setMonth(d.getMonth() - 1);
      else if (event.key === 'PageDown') d.setMonth(d.getMonth() + 1);
      else return;
      event.preventDefault();
      p.focus = d;
      p.year = d.getFullYear();
      p.month = d.getMonth();
      renderDate(true);
    });

    renderDate(moveFocus);
    placeDate();
  }

  document.addEventListener('click', function (event) {
    var toggle = event.target.closest('[data-date-toggle]');
    if (toggle) {
      var input = toggle.parentNode.querySelector('[data-date]');
      if (picker && picker.input === input) closeDate();
      else openDate(input, true);
      return;
    }
    var field = event.target.closest('[data-date]');
    if (field) openDate(field, false);
    else closeDate();
  });

  document.addEventListener('keydown', function (event) {
    if (!picker) {
      if (event.key === 'ArrowDown' && event.target.matches && event.target.matches('[data-date]')) {
        event.preventDefault();
        openDate(event.target, true);
      }
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      var input = picker.input;
      closeDate();
      input.focus();
    } else if (event.key === 'ArrowDown' && event.target === picker.input) {
      event.preventDefault();
      renderDate(true);
    }
  });

  // Tabbing away from both the field and the card closes it.
  document.addEventListener('focusout', function (event) {
    if (!picker || !event.relatedTarget) return;
    var next = event.relatedTarget;
    if (next !== picker.input && next !== picker.toggle && !picker.card.contains(next)) closeDate();
  });

  // Typing: digits get their dots automatically (31122026 → 31.12.2026); the calendar follows.
  document.addEventListener('input', function (event) {
    var input = event.target;
    if (!input.matches || !input.matches('[data-date]')) return;
    var deleting = event.inputType && event.inputType.indexOf('delete') === 0;
    if (!deleting && input.selectionStart === input.value.length && /^[\d.]*$/.test(input.value)) {
      // «1.5.» → «01.05.»: a single digit closed by a dot gets its leading zero.
      var digits = input.value.replace(/(?<!\d)(\d)\./g, '0$1.').replace(/\D/g, '').slice(0, 8);
      var out = digits.slice(0, 2);
      if (digits.length >= 2) out += '.' + digits.slice(2, 4);
      if (digits.length >= 4) out += '.' + digits.slice(4);
      input.value = out;
    }
    var d = parseDate(input.value);
    if (picker && picker.input === input && d) {
      picker.year = d.getFullYear();
      picker.month = d.getMonth();
      picker.view = 'days';
      picker.focus = d;
      renderDate(false);
    }
  });

  document.addEventListener('scroll', function (event) {
    if (picker && !picker.card.contains(event.target)) placeDate();
  }, true);
  window.addEventListener('resize', placeDate);

  // ---------- Custom «Тип» dropdown ----------

  function closeSelects(except) {
    document.querySelectorAll('[data-kind-select].is-open').forEach(function (select) {
      if (select !== except) setSelectOpen(select, false);
    });
  }

  function setSelectOpen(select, open) {
    select.classList.toggle('is-open', open);
    select.querySelector('[data-select-menu]').hidden = !open;
    select.querySelector('[data-select-trigger]').setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  document.addEventListener('click', function (event) {
    closeSelects(event.target.closest('[data-kind-select]'));
    closeUnitPickers(event.target.closest('[data-unit-picker]'));
  });

  // ---------- % / м² picker inside the share field ----------

  function setUnitPickerOpen(picker, open) {
    picker.classList.toggle('is-open', open);
    picker.querySelector('[data-unit-menu]').hidden = !open;
    picker.querySelector('[data-unit-trigger]').setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function closeUnitPickers(except) {
    document.querySelectorAll('[data-unit-picker].is-open').forEach(function (picker) {
      if (picker !== except) setUnitPickerOpen(picker, false);
    });
  }

  document.addEventListener('keydown', function (event) {
    var picker = event.target.closest && event.target.closest('[data-unit-picker].is-open');
    if (!picker) return;
    if (event.key === 'Escape') {
      setUnitPickerOpen(picker, false);
      picker.querySelector('[data-unit-trigger]').focus();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      var options = Array.prototype.slice.call(picker.querySelectorAll('.select-option'));
      var next = options[options.indexOf(document.activeElement) + (event.key === 'ArrowDown' ? 1 : -1)];
      if (next) { event.preventDefault(); next.focus(); }
    }
  });

  function initKindSelect(select, form) {
    var kindInput = select.querySelector('input[name=kind]');
    var customInput = select.querySelector('input[name=custom_kind]');
    var trigger = select.querySelector('[data-select-trigger]');
    var label = select.querySelector('[data-select-label]');
    var list = select.querySelector('.select-list');
    var newInput = select.querySelector('[data-kind-new]');
    var addButton = select.querySelector('[data-kind-add]');
    var error = select.querySelector('[data-kind-error]');

    function rows() {
      return Array.prototype.slice.call(list.querySelectorAll('.select-row'));
    }

    function matches(row) {
      if (row.dataset.value !== kindInput.value) return false;
      return row.dataset.value !== 'custom' || row.dataset.name === customInput.value;
    }

    function render() {
      var current = null;
      rows().forEach(function (row) {
        var selected = matches(row);
        row.classList.toggle('is-selected', selected);
        row.querySelector('.select-option').setAttribute('aria-selected', selected ? 'true' : 'false');
        if (selected) current = row;
      });
      if (current) label.textContent = current.querySelector('.select-option span').textContent;
      else label.textContent = kindInput.value === 'custom' ? customInput.value : '';
    }

    function choose(row) {
      kindInput.value = row.dataset.value;
      customInput.value = row.dataset.name || '';
      render();
      setSelectOpen(select, false);
      trigger.focus();
    }

    function showError(message) {
      error.textContent = message || '';
      error.hidden = !message;
    }

    function customRow(kind) {
      var row = document.createElement('li');
      row.className = 'select-row';
      row.dataset.value = 'custom';
      row.dataset.name = kind.name;
      row.dataset.custom = '';
      row.innerHTML =
        '<button type="button" class="select-option" role="option"><span></span>' +
        '<svg class="icon select-check"><use href="#i-check"/></svg></button>' +
        '<button type="button" class="select-remove" title="Удалить вариант"><svg class="icon"><use href="#i-x"/></svg></button>';
      row.querySelector('span').textContent = kind.name;
      var remove = row.querySelector('.select-remove');
      remove.dataset.removeUrl = kind.delete_url;
      remove.setAttribute('aria-label', 'Удалить вариант «' + kind.name + '»');
      return row;
    }

    function addKind() {
      var name = newInput.value.trim();
      if (!name) return;
      var body = new FormData();
      body.append('name', name);
      body.append('csrfmiddlewaretoken', csrfToken(form));
      addButton.disabled = true;
      fetch(select.dataset.addUrl, { method: 'POST', body: body, credentials: 'same-origin' })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          addButton.disabled = false;
          if (data.error) { showError(data.error); return; }
          showError('');
          var row = rows().filter(function (r) { return r.dataset.value === 'custom' && r.dataset.name === data.name; })[0];
          if (!row) {
            row = customRow(data);
            list.insertBefore(row, list.querySelector('[data-other]'));
          }
          newInput.value = '';
          addButton.hidden = true;
          choose(row);
        })
        .catch(function () {
          addButton.disabled = false;
          showError('Не получилось сохранить. Попробуйте ещё раз.');
        });
    }

    function removeKind(row, button) {
      var body = new FormData();
      body.append('csrfmiddlewaretoken', csrfToken(form));
      fetch(button.dataset.removeUrl, { method: 'POST', body: body, credentials: 'same-origin' })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          var wasSelected = matches(row);
          row.remove();
          if (wasSelected) {
            kindInput.value = 'apartment';
            customInput.value = '';
          }
          render();
        })
        .catch(function () { showError('Не получилось удалить. Попробуйте ещё раз.'); });
    }

    trigger.addEventListener('click', function () {
      var open = !select.classList.contains('is-open');
      setSelectOpen(select, open);
      showError('');
      if (open) {
        var selected = list.querySelector('.is-selected .select-option') || list.querySelector('.select-option');
        if (selected) selected.focus();
      }
    });

    list.addEventListener('click', function (event) {
      var remove = event.target.closest('.select-remove');
      var row = event.target.closest('.select-row');
      if (!row) return;
      if (remove) removeKind(row, remove);
      else if (event.target.closest('.select-option')) choose(row);
    });

    // Arrow keys move between options.
    select.addEventListener('keydown', function (event) {
      if (!select.classList.contains('is-open')) {
        if (event.key === 'ArrowDown' && event.target === trigger) {
          event.preventDefault();
          trigger.click();
        }
        return;
      }
      if (event.key === 'Escape') {
        setSelectOpen(select, false);
        trigger.focus();
        return;
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      var options = Array.prototype.slice.call(list.querySelectorAll('.select-option')).concat([newInput]);
      var index = options.indexOf(document.activeElement);
      var next = options[index + (event.key === 'ArrowDown' ? 1 : -1)];
      if (next) {
        event.preventDefault();
        next.focus();
      }
    });

    newInput.addEventListener('input', function () {
      addButton.hidden = !newInput.value.trim();
      showError('');
    });
    newInput.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault(); // never submit the whole form from here
        addKind();
      }
    });
    addButton.addEventListener('click', addKind);

    render();
  }

  // ---------- Object form ----------

  function initPropertyForm(form) {
    var list = form.querySelector('[data-tenant-list]');
    var template = form.querySelector('[data-tenant-template]');
    var totalForms = form.querySelector('input[name="tenants-TOTAL_FORMS"]');
    var areaInput = form.querySelector('[data-total-area]');
    var unitInput = form.querySelector('input[name=share_unit]');
    var occupied = form.querySelector('[data-occupied]');

    form.querySelectorAll('[data-kind-select]').forEach(function (select) { initKindSelect(select, form); });

    // The whole form, not only the list: in the object window a row may sit in the small window.
    function visibleRows() {
      return Array.prototype.filter.call(form.querySelectorAll('[data-tenant-row]'), function (row) {
        return !row.hidden;
      });
    }

    function update() {
      var isArea = unitInput.value === 'area';
      var totalArea = parseNumber(areaInput && areaInput.value);
      var sum = 0;

      form.querySelectorAll('[data-tenant-row] [data-unit-picker]').forEach(function (picker) {
        picker.querySelector('[data-unit-label]').textContent = isArea ? 'м²' : '%';
        picker.querySelectorAll('[data-unit-value]').forEach(function (row) {
          var selected = row.dataset.unitValue === unitInput.value;
          row.classList.toggle('is-selected', selected);
          row.querySelector('.select-option').setAttribute('aria-selected', selected ? 'true' : 'false');
        });
      });

      visibleRows().forEach(function (row) {
        var value = parseNumber(row.querySelector('[data-share]').value);
        var hint = row.querySelector('[data-share-hint]');
        if (value !== null) sum += value;
        var text = '';
        if (value !== null && totalArea) {
          text = isArea ? '~' + formatNumber(value / totalArea * 100) + '%'
                        : '~' + formatNumber(value * totalArea / 100) + ' м²';
        }
        hint.textContent = text;
      });

      var over = isArea ? (totalArea && sum > totalArea) : sum > 100;
      if (isArea) {
        occupied.textContent = totalArea
          ? 'занято ' + formatNumber(sum) + ' из ' + formatNumber(totalArea) + ' м²'
          : 'занято ' + formatNumber(sum) + ' м² · укажите площадь объекта';
      } else {
        occupied.textContent = 'занято ' + formatNumber(sum) + '%';
      }
      occupied.classList.toggle('is-over', Boolean(over));
    }

    // The unit is one for the whole object: changing it in any row converts every row.
    function setUnit(unit) {
      if (unit === unitInput.value) return;
      var totalArea = parseNumber(areaInput && areaInput.value);
      if (totalArea) {
        visibleRows().forEach(function (row) {
          var input = row.querySelector('[data-share]');
          var value = parseNumber(input.value);
          if (value === null) return;
          input.value = formatNumber(unit === 'area' ? value * totalArea / 100 : value / totalArea * 100);
        });
      }
      unitInput.value = unit;
      update();
    }

    function removeRow(row) {
      var del = row.querySelector('input[name$="-DELETE"]');
      if (del) del.checked = true;
      row.hidden = true;
      if (!visibleRows().length && !form.querySelector('[data-items]')) addRow();
      update();
    }

    function addRow() {
      var index = Number(totalForms.value);
      var html = template.innerHTML.replace(/__prefix__/g, index);
      list.insertAdjacentHTML('beforeend', html);
      totalForms.value = index + 1;
      update();
      return list.lastElementChild;
    }

    form.addEventListener('change', function (event) {
      if (event.target.name === 'occupancy') {
        form.classList.toggle('is-owner', event.target.value === 'owner');
      }
    });

    form.addEventListener('input', function (event) {
      if (event.target.matches('[data-share], [data-total-area]')) update();
    });
    form.propertyUpdate = update;

    // Enter moves to the next field instead of saving half-filled data; Ctrl+Enter saves.
    form.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' || event.defaultPrevented) return;
      var target = event.target;
      if (!target.matches('input:not([type=hidden]):not([type=radio]):not([type=checkbox])')) return;
      event.preventDefault();
      if (event.ctrlKey || event.metaKey) {
        form.requestSubmit();
        return;
      }
      var fields = Array.prototype.filter.call(
        form.querySelectorAll('input:not([type=hidden]):not([type=radio]):not([type=checkbox]):not([data-kind-new]), [data-select-trigger], [type=submit]'),
        function (el) { return !el.disabled && el.offsetParent !== null; }
      );
      var next = fields[fields.indexOf(target) + 1];
      if (next) next.focus();
    });

    form.addEventListener('click', function (event) {
      var unitTrigger = event.target.closest('[data-unit-trigger]');
      if (unitTrigger) {
        var picker = unitTrigger.closest('[data-unit-picker]');
        var open = !picker.classList.contains('is-open');
        setUnitPickerOpen(picker, open);
        if (open) (picker.querySelector('.is-selected .select-option') || picker.querySelector('.select-option')).focus();
        return;
      }
      var unitRow = event.target.closest('[data-unit-value]');
      if (unitRow) {
        var owner = unitRow.closest('[data-unit-picker]');
        setUnit(unitRow.dataset.unitValue);
        setUnitPickerOpen(owner, false);
        owner.querySelector('[data-unit-trigger]').focus();
        return;
      }
      var remove = event.target.closest('[data-tenant-remove]');
      if (remove) {
        removeRow(remove.closest('[data-tenant-row]'));
        return;
      }
      if (event.target.closest('[data-tenant-add]')) {
        var row = addRow();
        var name = row.querySelector('input[type=text]');
        if (name) name.focus();
      }
    });

    update();
  }

  // ---------- Object window: meters and tenants as info rows, each filled in a small window ----------
  // Every meter / tenant keeps its form fields hidden in the object form (data-item-store) and is
  // shown as one info row. «+ Добавить …», ✎ or a click on the row moves its fields into the small
  // window (data-subwin) and back; everything is saved with the object.

  function initItems(form) {
    var sub = form.querySelector('[data-subwin]');
    var body = sub.querySelector('[data-subwin-body]');
    var blocks = {};
    form.querySelectorAll('[data-items]').forEach(function (block) { blocks[block.dataset.items] = block; });
    var PREFIX = { meter: 'meters', tenant: 'tenants' };
    var current = null;  // the item in the small window: {item, kind, holder, isNew, snap, number}

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function val(item, suffix) {
      var input = item.querySelector('input[name$="-' + suffix + '"]');
      return input ? input.value.trim() : '';
    }
    function setVal(item, suffix, value) {
      var input = item.querySelector('input[name$="-' + suffix + '"]');
      if (input) input.value = value;
    }
    function indexOf(item) {
      var input = item.querySelector('input[name$="-id"]');
      var match = input && input.name.match(/-(\d+)-id$/);
      return match ? match[1] : '';
    }
    // How meter rows name their tenant: «pk:12» once saved, «new:3» for a new row of this form.
    function tenantKey(item) {
      var id = val(item, 'id');
      return id ? 'pk:' + id : 'new:' + indexOf(item);
    }
    // The store's items in order; the one in the small window stands in for its placeholder.
    function items(kind) {
      var store = blocks[kind] && blocks[kind].querySelector('[data-item-store]');
      if (!store) return [];
      return Array.prototype.map.call(store.children, function (child) {
        return current && child === current.holder ? current.item : child;
      }).filter(function (item) { return item.matches('[data-item]') && !item.hidden; });
    }
    function tenantName(key) {
      var tenant = items('tenant').filter(function (item) { return tenantKey(item) === key; })[0];
      return tenant ? val(tenant, 'name') || 'арендатор' : null;
    }
    function isDayNight(item) {
      var checked = item.querySelector('[data-day-night]:checked');
      return Boolean(checked && checked.value === '1');
    }
    function meterWho(item) {
      var owner = val(item, 'owner');
      if (form.classList.contains('is-owner') || !owner) return { text: 'общий', cls: '' };
      var name = owner === 'free' ? null : tenantName(owner);
      return name ? { text: name, cls: 'is-tenant' } : { text: 'свободен', cls: 'is-free' };
    }
    function startText(item) {
      var day = val(item, 'initial');
      var night = val(item, 'initial_night');
      if (!day) return '';
      return (isDayNight(item) ? day + ' / ' + (night || '—') : day) + ' ' + val(item, 'unit');
    }
    function shareUnit() {
      var input = form.querySelector('input[name=share_unit]');
      return input && input.value === 'area' ? 'м²' : '%';
    }

    // ---- info rows ----

    function cell(cls, label, value, empty) {
      var span = el('span', 'info-cell ' + (cls || ''));
      if (value) {
        if (label) span.appendChild(el('span', 'info-label', label + ' '));
        span.appendChild(document.createTextNode(value));
      } else {
        span.appendChild(el('span', 'info-none', empty || '—'));
      }
      return span;
    }

    function infoRow(item, number, kind) {
      var row = el('div', 'info-row info-' + kind);
      row.tabIndex = 0;
      row.setAttribute('role', 'button');
      row.itemRef = item;
      row.appendChild(el('span', 'inum', String(number)));
      if (kind === 'meter') {
        var main = el('span', 'info-cell info-main', val(item, 'name'));
        if (isDayNight(item)) main.appendChild(el('span', 'info-label', ' день/ночь'));
        row.appendChild(main);
        row.appendChild(cell('info-serial', '№', val(item, 'serial'), '№ —'));
        row.appendChild(cell('info-start', 'старт', startText(item), 'старт —'));
        var who = meterWho(item);
        row.appendChild(el('span', 'who-badge ' + who.cls, who.text));
        row.title = 'Изменить счётчик';
      } else {
        row.appendChild(el('span', 'info-cell info-main', val(item, 'name')));
        var share = val(item, 'share');
        var hint = item.querySelector('[data-share-hint]');
        var shareCell = cell('info-share', '', share ? share + (shareUnit() === '%' ? '%' : ' м²') : '', 'доля —');
        if (share && hint && hint.textContent) shareCell.appendChild(el('span', 'info-label', ' · ' + hint.textContent.replace('~', '≈ ')));
        row.appendChild(shareCell);
        row.appendChild(cell('info-until', 'до', val(item, 'contract_until'), 'договор —'));
        row.appendChild(cell('info-phone', '', val(item, 'phone'), 'телефон —'));
        row.title = 'Изменить арендатора';
      }
      if (item.querySelector('.errorlist')) {
        row.classList.add('has-error');
        row.title = 'Есть ошибка — откройте и исправьте';
      }
      var edit = el('button', 'icon-button info-edit');
      edit.type = 'button';
      edit.setAttribute('aria-label', 'Изменить');
      edit.innerHTML = '<svg class="icon"><use href="#i-edit"/></svg>';
      var remove = el('button', 'icon-button info-remove');
      remove.type = 'button';
      remove.dataset.infoRemove = '';
      remove.setAttribute('aria-label', 'Удалить');
      remove.title = 'Удалить';
      remove.innerHTML = '<svg class="icon"><use href="#i-x"/></svg>';
      row.appendChild(edit);
      row.appendChild(remove);
      return row;
    }

    function render() {
      ['meter', 'tenant'].forEach(function (kind) {
        var block = blocks[kind];
        if (!block) return;
        var list = block.querySelector('[data-info-list]');
        list.innerHTML = '';
        var all = items(kind);
        all.forEach(function (item, i) { list.appendChild(infoRow(item, i + 1, kind)); });
        if (!all.length) {
          list.appendChild(el('p', 'info-empty', kind === 'meter' ? 'Счётчиков пока нет' : 'Арендаторов пока нет'));
        }
        var count = block.querySelector('[data-items-count]');
        if (count) count.textContent = all.length ? all.length + ' шт.' : '';
      });
    }

    // ---- a meter's own controls ----

    function syncMeter(item) {
      var dn = isDayNight(item);
      var night = item.querySelector('[data-night-field]');
      if (night) night.hidden = !dn;
      var dayLabel = item.querySelector('[data-day-label]');
      if (dayLabel) dayLabel.hidden = !dn;
      var name = val(item, 'name');
      var label = item.querySelector('[data-msel-label]');
      if (label) label.textContent = name;
      item.querySelectorAll('[data-msel] .select-row').forEach(function (row) {
        row.classList.toggle('is-selected', row.dataset.name === name);
      });
      var unit = val(item, 'unit');
      if (!unit) {
        // An old meter without a unit: its kind's usual one, else the first of the menu.
        var known = item.querySelector('[data-msel] .select-row.is-selected');
        unit = (known && known.dataset.unit) || 'кВт·ч';
        setVal(item, 'unit', unit);
      }
      var fixed = val(item, 'kind') !== 'custom';
      item.querySelectorAll('[data-munit]').forEach(function (picker) {
        picker.querySelector('[data-munit-label]').textContent = unit;
        picker.classList.toggle('is-fixed', fixed);
        picker.querySelector('[data-munit-trigger]').disabled = fixed;
        picker.querySelectorAll('[data-munit-value]').forEach(function (row) {
          row.classList.toggle('is-selected', row.dataset.munitValue === unit);
        });
      });
      var badge = item.querySelector('[data-subwin-badge]');
      if (badge) badge.textContent = name + (dn ? ' · день / ночь' : '');
    }

    function closeMenus(except) {
      form.querySelectorAll('[data-msel].is-open, [data-munit].is-open').forEach(function (pick) {
        if (pick === except) return;
        pick.classList.remove('is-open');
        var menu = pick.querySelector('[data-msel-menu], [data-munit-menu]');
        if (menu) menu.hidden = true;
      });
    }

    function toggleMenu(pick) {
      var menu = pick.querySelector('[data-msel-menu], [data-munit-menu]');
      var open = menu.hidden;
      closeMenus(pick);
      menu.hidden = !open;
      pick.classList.toggle('is-open', open);
      if (open) {
        var first = pick.querySelector('.is-selected .select-option') || pick.querySelector('.select-option');
        if (first) first.focus();
      }
    }

    function chooseKind(item, row) {
      setVal(item, 'kind', row.dataset.kind);
      setVal(item, 'name', row.dataset.name);
      if (row.dataset.unit) setVal(item, 'unit', row.dataset.unit);
      else if (!val(item, 'unit')) setVal(item, 'unit', 'кВт·ч');
      closeMenus(null);
      syncMeter(item);
      item.querySelector('[data-msel-trigger]').focus();
    }

    // «свой вариант…»: offered in every meter's menu from now on.
    function addKind(item) {
      var input = item.querySelector('[data-msel-new]');
      var name = input.value.trim();
      if (!name) return;
      var lists = Array.prototype.slice.call(form.querySelectorAll('[data-msel] .select-list'));
      var template = blocks.meter.querySelector('[data-item-template]');
      if (template) lists = lists.concat(Array.prototype.slice.call(template.content.querySelectorAll('.select-list')));
      var mine = null;
      lists.forEach(function (list) {
        var found = Array.prototype.filter.call(list.querySelectorAll('.select-row'), function (row) {
          return row.dataset.name.toLowerCase() === name.toLowerCase();
        })[0];
        if (!found) {
          found = el('li', 'select-row');
          found.dataset.kind = 'custom';
          found.dataset.name = name;
          found.dataset.unit = '';
          found.innerHTML = '<button type="button" class="select-option" role="option"><span></span>' +
            '<svg class="icon select-check"><use href="#i-check"/></svg></button>';
          found.querySelector('span').textContent = name;
          list.appendChild(found);
        }
        if (item.contains(list)) mine = found;
      });
      input.value = '';
      item.querySelector('[data-msel-add]').hidden = true;
      chooseKind(item, mine);
    }

    // ---- the tenant's meters (ticks under the tenant's fields) ----

    function tenantMeters(item) {
      var key = tenantKey(item);
      var section = el('section', 'form-section tenant-meters');
      var head = el('div', 'form-section-head');
      var title = el('h2');
      title.dataset.tmTitle = '';
      var count = el('span', 'head-badge');
      count.dataset.tmCount = '';
      head.appendChild(title);
      head.appendChild(count);
      section.appendChild(head);
      var sectionBody = el('div', 'form-section-body');
      section.appendChild(sectionBody);
      var meters = items('meter');
      if (!meters.length) {
        sectionBody.appendChild(el('p', 'form-note', 'На объекте пока нет счётчиков — добавьте их в блоке «Счётчики».'));
        return section;
      }
      var list = el('div', 'tm-list');
      meters.forEach(function (meter, i) {
        var owner = val(meter, 'owner');
        var busy = owner && owner !== 'free' && owner !== key ? tenantName(owner) : null;
        var row = el('label', 'tm-row' + (busy ? ' is-busy' : ''));
        var box = el('input');
        box.type = 'checkbox';
        box.checked = owner === key;
        box.disabled = Boolean(busy);
        box.meterRef = meter;
        row.appendChild(box);
        row.appendChild(el('span', 'inum', String(i + 1)));
        row.appendChild(el('span', 'info-cell info-main', val(meter, 'name')));
        row.appendChild(cell('', '№', val(meter, 'serial'), '№ —'));
        row.appendChild(cell('', 'старт', startText(meter), 'старт —'));
        var who;
        if (busy) who = el('span', 'who-badge is-tenant', busy);
        else if (owner && owner !== key) who = el('span', 'who-badge is-free', 'свободен');
        else if (!owner) who = el('span', 'who-badge', 'общий');
        else who = el('span');
        row.appendChild(who);
        list.appendChild(row);
      });
      sectionBody.appendChild(list);
      sectionBody.appendChild(el('p', 'form-note', 'Отметьте счётчики, по которым платит этот арендатор. Неотмеченные — общие: по ним платят по долям.'));
      return section;
    }

    function syncTenantMeters() {
      if (!current || current.kind !== 'tenant') return;
      var title = sub.querySelector('[data-tm-title]');
      if (title) title.textContent = 'Счётчики · ' + (val(current.item, 'name') || 'арендатор ' + current.number);
      var count = sub.querySelector('[data-tm-count]');
      var ticked = sub.querySelectorAll('.tm-row input:checked').length;
      if (count) count.textContent = ticked ? 'отмечено ' + ticked : '';
    }

    function applyTicks() {
      var key = tenantKey(current.item);
      sub.querySelectorAll('.tm-row input').forEach(function (box) {
        if (box.disabled) return;
        var owner = val(box.meterRef, 'owner');
        if (box.checked) setVal(box.meterRef, 'owner', key);
        else if (owner === key) setVal(box.meterRef, 'owner', '');
      });
    }

    // ---- the small window ----

    function snapshot(item) {
      return Array.prototype.map.call(item.querySelectorAll('input'), function (input) {
        return [input, input.value, input.checked];
      });
    }

    function freeShare(except) {
      var used = items('tenant').reduce(function (sum, item) {
        return item === except ? sum : sum + (parseNumber(val(item, 'share')) || 0);
      }, 0);
      if (shareUnit() === '%') return Math.max(0, 100 - used);
      var areaInput = form.querySelector('[data-total-area]');
      var area = areaInput ? parseNumber(areaInput.value) : null;
      return area ? Math.max(0, area - used) : null;
    }

    function openItem(item, isNew) {
      var kind = item.dataset.item;
      var number = items(kind).indexOf(item) + 1;
      var holder = el('span');
      holder.hidden = true;
      item.parentNode.replaceChild(holder, item);
      body.innerHTML = '';
      body.appendChild(item);
      current = { item: item, kind: kind, holder: holder, isNew: isNew, snap: snapshot(item), number: number };
      var title = sub.querySelector('[data-subwin-title]');
      if (kind === 'meter') {
        title.textContent = isNew ? 'Новый счётчик' : 'Счётчик ' + number;
        var head = item.querySelector('.form-section-head');
        if (head && !head.querySelector('[data-subwin-badge]')) {
          var badge = el('span', 'head-badge');
          badge.dataset.subwinBadge = '';
          head.appendChild(badge);
        }
        syncMeter(item);
      } else {
        title.textContent = isNew ? 'Новый арендатор' : 'Арендатор ' + number;
        body.appendChild(tenantMeters(item));
        syncTenantMeters();
      }
      var free = kind === 'tenant' ? freeShare(item) : null;
      var unit = shareUnit() === '%' ? '%' : ' м²';
      sub.querySelector('[data-subwin-sub]').textContent = free === null ? ''
        : free > 0 ? ' · можно до ' + formatNumber(free) + unit : ' · объект уже занят полностью';
      var del = sub.querySelector('[data-subwin-delete]');
      del.hidden = isNew;
      del.textContent = kind === 'meter' ? 'Удалить счётчик' : 'Удалить арендатора';
      sub.hidden = false;
      if (form.propertyUpdate) form.propertyUpdate();
      initFades(sub);
      var error = item.querySelector('.errorlist');
      var focus = error ? error.closest('.field') && error.closest('.field').querySelector('input:not([type=hidden])') : null;
      if (!focus) {
        focus = kind === 'meter' ? item.querySelector('[data-msel-trigger]')
          : item.querySelector('input:not([type=hidden]):not([type=radio]):not([type=checkbox])');
      }
      if (focus) focus.focus();
    }

    function closeSub() {
      body.innerHTML = '';
      sub.hidden = true;
      current = null;
      closeMenus(null);
      hideTip();
      closeDate();
    }

    function putBack() {
      current.holder.parentNode.replaceChild(current.item, current.holder);
      closeSub();
    }

    function clientError(field, text) {
      if (!field || field.querySelector('[data-client-error]')) return;
      var list = el('ul', 'errorlist');
      list.dataset.clientError = '';
      list.appendChild(el('li', '', text));
      field.appendChild(list);
    }

    function check(item) {
      var empty = [];
      var need = item.dataset.item === 'meter'
        ? ['initial'].concat(isDayNight(item) ? ['initial_night'] : [])
        : ['name', 'share'];
      need.forEach(function (suffix) {
        var input = item.querySelector('input[name$="-' + suffix + '"]');
        if (input && !input.value.trim()) {
          clientError(input.closest('.field'), 'Заполните поле.');
          empty.push(input);
        }
      });
      if (empty.length) empty[0].focus();
      return !empty.length;
    }

    function done() {
      if (!check(current.item)) return;
      if (current.kind === 'tenant') applyTicks();
      putBack();
      render();
    }

    function cancel() {
      if (current.isNew) {
        var total = form.querySelector('input[name="' + PREFIX[current.kind] + '-TOTAL_FORMS"]');
        current.holder.parentNode.removeChild(current.holder);
        total.value = Number(total.value) - 1;
        closeSub();
      } else {
        current.snap.forEach(function (entry) { entry[0].value = entry[1]; entry[0].checked = entry[2]; });
        current.item.querySelectorAll('[data-client-error]').forEach(function (node) { node.parentNode.removeChild(node); });
        if (current.kind === 'meter') syncMeter(current.item);
        putBack();
      }
      if (form.propertyUpdate) form.propertyUpdate();
      render();
    }

    function removeItem(item) {
      var del = item.querySelector('input[name$="-DELETE"]');
      if (del) del.checked = true;
      item.hidden = true;
      if (item.dataset.item === 'tenant') {
        // A tenant moves out: their meters stay with the premises as free ones.
        var key = tenantKey(item);
        items('meter').forEach(function (meter) {
          if (val(meter, 'owner') === key) setVal(meter, 'owner', key.indexOf('pk:') === 0 ? 'free' : '');
        });
      }
      if (form.propertyUpdate) form.propertyUpdate();
    }

    function addItem(kind) {
      var block = blocks[kind];
      var total = form.querySelector('input[name="' + PREFIX[kind] + '-TOTAL_FORMS"]');
      var index = Number(total.value);
      var html = block.querySelector('[data-item-template]').innerHTML.replace(/__prefix__/g, index);
      var store = block.querySelector('[data-item-store]');
      store.insertAdjacentHTML('beforeend', html);
      total.value = index + 1;
      var item = store.lastElementChild;
      if (kind === 'tenant' && shareUnit() === '%') {
        var free = freeShare(null);
        if (free > 0) setVal(item, 'share', formatNumber(free));
      }
      openItem(item, true);
    }

    // ---- events ----

    form.addEventListener('click', function (event) {
      var target = event.target;
      var add = target.closest('[data-item-add]');
      if (add) { addItem(add.closest('[data-items]').dataset.items); return; }

      var infoRemove = target.closest('[data-info-remove]');
      if (infoRemove) {
        removeItem(infoRemove.closest('.info-row').itemRef);
        render();
        return;
      }
      var info = target.closest('.info-row');
      if (info) { openItem(info.itemRef, false); return; }

      if (!current) return;
      if (target.closest('[data-subwin-done]')) { done(); return; }
      if (target.closest('[data-subwin-cancel]')) { event.preventDefault(); cancel(); return; }
      if (target.closest('[data-subwin-delete]')) {
        var gone = current.item;
        putBack();
        removeItem(gone);
        render();
        return;
      }

      var item = current.item;
      var msel = target.closest('[data-msel]');
      var munit = target.closest('[data-munit]');
      if (msel) {
        if (target.closest('[data-msel-trigger]')) toggleMenu(msel);
        else if (target.closest('[data-msel-add]')) addKind(item);
        else if (target.closest('.select-row')) chooseKind(item, target.closest('.select-row'));
        return;
      }
      if (munit) {
        var unitRow = target.closest('[data-munit-value]');
        if (unitRow) {
          setVal(item, 'unit', unitRow.dataset.munitValue);
          closeMenus(null);
          syncMeter(item);
          munit.querySelector('[data-munit-trigger]').focus();
        } else if (target.closest('[data-munit-trigger]')) {
          toggleMenu(munit);
        }
        return;
      }
      closeMenus(null);
    });

    form.addEventListener('keydown', function (event) {
      var target = event.target;
      var info = target.closest && target.closest('.info-row');
      if (info && target === info && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        openItem(info.itemRef, false);
        return;
      }
      if (!current || !sub.contains(target)) return;
      if (event.key === 'Escape') {
        if (form.querySelector('[data-msel].is-open, [data-munit].is-open')) {
          event.preventDefault();
          closeMenus(null);
        }
        return;
      }
      if (event.key !== 'Enter') return;
      if (target.matches('[data-msel-new]')) {
        event.preventDefault();
        addKind(current.item);
        return;
      }
      if (!target.matches('input:not([type=hidden]):not([type=checkbox]):not([type=radio])')) return;
      // Enter: the next field of the small window; after the last one — «Готово».
      event.preventDefault();
      var fields = Array.prototype.filter.call(
        body.querySelectorAll('input:not([type=hidden]):not([type=radio]):not([type=checkbox]):not([data-msel-new])'),
        function (input) { return !input.disabled && input.offsetParent !== null; });
      var next = fields[fields.indexOf(target) + 1];
      if (next) next.focus();
      else done();
    }, true);

    form.addEventListener('input', function (event) {
      var field = event.target.closest && event.target.closest('.field');
      if (field) field.querySelectorAll('[data-client-error]').forEach(function (node) { node.parentNode.removeChild(node); });
      if (event.target.matches('[data-msel-new]')) {
        event.target.closest('.select-add').querySelector('[data-msel-add]').hidden = !event.target.value.trim();
      }
      if (current && current.kind === 'tenant' && event.target.matches('input[name$="-name"]')) syncTenantMeters();
    });

    form.addEventListener('change', function (event) {
      if (!current) {
        if (event.target.name === 'occupancy') render();
        return;
      }
      if (event.target.matches('[data-day-night]')) syncMeter(current.item);
      if (event.target.closest('.tm-row')) syncTenantMeters();
    });

    // The object can't be sent while a small window is open: «Готово» first.
    form.addEventListener('submit', function (event) {
      if (current) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);

    form.querySelectorAll('[data-item="meter"]').forEach(syncMeter);
    render();
    // The server found a mistake: open the first item that has it.
    var broken = Array.prototype.filter.call(form.querySelectorAll('[data-item-store] [data-item]'), function (item) {
      return !item.hidden && item.querySelector('.errorlist');
    })[0];
    if (broken) openItem(broken, false);
  }

  function initForms(root) {
    root.querySelectorAll('[data-property-form]').forEach(initPropertyForm);
    root.querySelectorAll('[data-subwin]').forEach(function (sub) { initItems(sub.closest('form')); });
    initFades(root);
    initMeters(root);
  }

  // ---------- Service window ----------

  // «Единица»: a small menu that writes into a hidden input.
  function setPickOpen(pick, open) {
    pick.classList.toggle('is-open', open);
    pick.querySelector('[data-pick-menu]').hidden = !open;
    pick.querySelector('[data-pick-trigger]').setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  document.addEventListener('click', function (event) {
    var current = event.target.closest && event.target.closest('[data-pick]');
    document.querySelectorAll('[data-pick].is-open').forEach(function (pick) {
      if (pick !== current) setPickOpen(pick, false);
    });
    if (!current) return;
    if (event.target.closest('[data-pick-trigger]')) {
      var open = !current.classList.contains('is-open');
      setPickOpen(current, open);
      if (open) (current.querySelector('.is-selected .select-option') || current.querySelector('.select-option')).focus();
      return;
    }
    var row = event.target.closest('[data-pick-value]');
    if (row) {
      current.querySelector('input').value = row.dataset.pickValue;
      var pickLabel = current.querySelector('[data-pick-label]');
      pickLabel.textContent = row.dataset.pickLabel || row.dataset.pickValue;
      if (pickLabel.classList.contains('fade')) markFade(pickLabel);
      current.querySelectorAll('[data-pick-value]').forEach(function (r) { r.classList.toggle('is-selected', r === row); });
      setPickOpen(current, false);
      current.querySelector('[data-pick-trigger]').focus();
    }
  });

  document.addEventListener('keydown', function (event) {
    var pick = event.target.closest && event.target.closest('[data-pick].is-open');
    if (!pick) return;
    if (event.key === 'Escape') {
      event.stopPropagation();
      setPickOpen(pick, false);
      pick.querySelector('[data-pick-trigger]').focus();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      var options = Array.prototype.slice.call(pick.querySelectorAll('.select-option'));
      var next = options[options.indexOf(document.activeElement) + (event.key === 'ArrowDown' ? 1 : -1)];
      if (next) { event.preventDefault(); next.focus(); }
    }
  }, true);

  // Meter number: an ordinary field; typing in it → green frame and ✓; typed and left or ✓ → saved
  // (blue frame, ✎); ✎ opens it again; left empty → back to «не указан».
  function setSerialState(serial, state) {
    var input = serial.querySelector('input');
    if (state === 'locked' && !input.value.trim()) state = 'empty';
    serial.dataset.state = state;
    input.readOnly = state === 'locked';
    serial.querySelector('[data-serial-toggle]').setAttribute('aria-label', state === 'locked' ? 'Изменить номер' : 'Готово');
  }

  function editSerial(serial) {
    setSerialState(serial, 'edit');
    var input = serial.querySelector('input');
    input.focus();
    input.select();
  }

  document.addEventListener('mousedown', function (event) {
    // Keep the focus in the field, so «✓» doesn't first save it through blur and then reopen it.
    if (event.target.closest && event.target.closest('[data-serial-toggle]')) event.preventDefault();
  });

  document.addEventListener('click', function (event) {
    var add = event.target.closest && event.target.closest('[data-serial-add]');
    if (add) { editSerial(add.closest('[data-serial]')); return; }
    var toggle = event.target.closest && event.target.closest('[data-serial-toggle]');
    if (!toggle) return;
    var serial = toggle.closest('[data-serial]');
    if (serial.dataset.state === 'locked') editSerial(serial);
    else setSerialState(serial, 'locked');
  });

  // Into an empty number → typing (green); a click into a saved one counts as nothing.
  document.addEventListener('focusin', function (event) {
    var serial = event.target.closest && event.target.closest('[data-serial]');
    if (serial && event.target.matches('input') && serial.dataset.state === 'empty') setSerialState(serial, 'edit');
  });

  // Leaving a typed number saves it.
  document.addEventListener('focusout', function (event) {
    var serial = event.target.closest && event.target.closest('[data-serial]');
    if (serial && event.target.matches('input') && serial.dataset.state === 'edit') setSerialState(serial, 'locked');
  });

  // «Как делим» shows up (no meter, or one common meter) with nothing picked → «По долям».
  document.addEventListener('change', function (event) {
    var input = event.target;
    if (!input.matches || !input.matches('.rform input[name=metered], .rform input[name=layout]')) return;
    var form = input.form;
    if (form.querySelector('input[name=split]:checked')) return;
    var first = form.querySelector('input[name=split]');
    if (first) first.checked = true;
  });

  // The unit picked for the service shows next to its price.
  document.addEventListener('click', function (event) {
    var row = event.target.closest && event.target.closest('.rform [data-pick-value]');
    if (!row) return;
    row.closest('form').querySelectorAll('[data-unit-text]').forEach(function (el) { el.textContent = row.dataset.pickValue; });
  });

  // Enter in the service window moves to the next field (a number gets locked on the way).
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' || event.defaultPrevented) return;
    var target = event.target;
    var form = target.closest && target.closest('form.rform');
    if (!form || !target.matches('input[type=text], input:not([type])')) return;
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) { form.requestSubmit(); return; }
    var fields = Array.prototype.filter.call(
      form.querySelectorAll('input[type=text]:not([readonly]), [type=submit]'),
      function (el) { return !el.disabled && el.offsetParent !== null; }
    );
    var index = fields.indexOf(target);
    if (index >= 0 && fields[index + 1]) fields[index + 1].focus();
  });

  // Names that don't fit fade out at the end (.fade.is-clipped); the full name shows on hover.
  var fadeObserver = window.ResizeObserver ? new ResizeObserver(function (entries) {
    entries.forEach(function (entry) { markFade(entry.target); });
  }) : null;

  function markFade(el) {
    var clipped = el.scrollWidth > el.clientWidth + 1;
    el.classList.toggle('is-clipped', clipped);
    if (clipped) el.title = el.textContent.trim();
    else el.removeAttribute('title');
  }

  function initFades(root) {
    root.querySelectorAll('.fade').forEach(function (el) {
      markFade(el);
      if (fadeObserver) fadeObserver.observe(el);
    });
  }
  initFades(document);

  // Object window: «Информация об УК ▾» opens and closes the management company fields.
  document.addEventListener('click', function (event) {
    var toggle = event.target.closest && event.target.closest('[data-uk-toggle]');
    if (!toggle) return;
    var box = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!box) return;
    var open = box.hidden;
    box.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      var first = box.querySelector('input:not([type=hidden])');
      if (first) first.focus();
    }
  });

  // Object cards: a click anywhere opens the object, except on links, buttons and menus.
  document.addEventListener('click', function (event) {
    var card = event.target.closest && event.target.closest('[data-card-href]');
    if (!card || event.target.closest('a, button, summary, details, input, label, [data-card-skip]')) return;
    if (window.getSelection && String(window.getSelection())) return;  // selecting text to copy
    if (event.ctrlKey || event.metaKey) {
      window.open(card.getAttribute('data-card-href'), '_blank');
    } else {
      window.location.href = card.getAttribute('data-card-href');
    }
  });

  // ---------- Object page: monthly input saves itself, bills recalc ----------

  var monthForm = document.querySelector('[data-month-form]');
  var selectedPayer = null;

  function showPayer(id) {
    selectedPayer = String(id);
    document.querySelectorAll('[data-payer]').forEach(function (link) {
      link.classList.toggle('is-active', link.getAttribute('data-payer') === selectedPayer);
    });
    document.querySelectorAll('[data-bill]').forEach(function (bill) {
      bill.hidden = bill.getAttribute('data-bill') !== selectedPayer;
    });
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[data-payer]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    showPayer(link.getAttribute('data-payer'));
    history.replaceState(null, '', link.href);
  });

  if (monthForm) {
    var status = monthForm.querySelector('[data-save-status]');
    var timer = null;
    var pending = null;

    var active = document.querySelector('a[data-payer].is-active');
    if (active) selectedPayer = active.getAttribute('data-payer');

    // Only the read-only parts are swapped, so the field being typed in keeps focus.
    function applyPage(html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      document.querySelectorAll('[data-live]').forEach(function (el) {
        var fresh = el.id && doc.getElementById(el.id);
        if (fresh) el.replaceWith(fresh);
      });
      document.querySelectorAll('.mreceipt').forEach(function (card) {
        var fresh = doc.getElementById(card.id);
        if (fresh) card.classList.toggle('is-missing', fresh.classList.contains('is-missing'));
      });
      if (selectedPayer !== null && document.querySelector('[data-bill="' + selectedPayer + '"]')) {
        showPayer(selectedPayer);
      }
      initFades(document);
    }

    function save() {
      timer = null;
      if (pending) pending.abort();
      pending = new AbortController();
      status.textContent = 'Сохраняю…';
      fetch(monthForm.action, {
        method: 'POST',
        body: new FormData(monthForm),
        headers: { 'X-Live': '1' },
        credentials: 'same-origin',
        signal: pending.signal
      })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.text();
        })
        .then(function (html) {
          applyPage(html);
          status.textContent = 'Сохранено';
        })
        .catch(function (error) {
          if (error.name !== 'AbortError') status.textContent = 'Не сохранилось — нажмите «Сохранить»';
        });
    }

    monthForm.addEventListener('input', function () {
      status.textContent = '';
      clearTimeout(timer);
      timer = setTimeout(save, 700);
    });
    monthForm.addEventListener('submit', function (event) {
      event.preventDefault();
      clearTimeout(timer);
      save();
    });
    // Enter moves to the next number instead of submitting.
    monthForm.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' || !event.target.matches('.num-input')) return;
      event.preventDefault();
      var inputs = Array.prototype.slice.call(monthForm.querySelectorAll('.num-input'));
      var next = inputs[inputs.indexOf(event.target) + 1];
      if (next) next.focus(); else event.target.blur();
    });
    window.addEventListener('beforeunload', function () {
      if (!timer) return;
      clearTimeout(timer);
      var data = new FormData(monthForm);
      data.append('beacon', '1');  // leaving the page: just store, no answer needed
      navigator.sendBeacon(monthForm.action, data);
    });
  }

  // Drop-downs of radios in the service window: «Счётчики», «Вводим показания / расход».
  function setDropOpen(drop, open) {
    drop.classList.toggle('is-open', open);
    drop.querySelector('[data-drop-menu]').hidden = !open;
    drop.querySelector('[data-drop-trigger]').setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  document.addEventListener('click', function (event) {
    var current = event.target.closest && event.target.closest('[data-drop]');
    document.querySelectorAll('[data-drop].is-open').forEach(function (drop) {
      if (drop !== current) setDropOpen(drop, false);
    });
    if (!current || !event.target.closest('[data-drop-trigger]')) return;
    var open = !current.classList.contains('is-open');
    setDropOpen(current, open);
    if (open) (current.querySelector('input:checked') || current.querySelector('input')).focus();
  });

  document.addEventListener('change', function (event) {
    var drop = event.target.closest && event.target.closest('[data-drop]');
    if (!drop) return;
    drop.querySelector('[data-drop-label]').textContent = event.target.closest('label').textContent.trim();
  });

  document.addEventListener('keydown', function (event) {
    var drop = event.target.closest && event.target.closest('[data-drop].is-open');
    if (!drop) return;
    if (event.key === 'Escape' || event.key === 'Enter' || event.key === ' ' || event.key === 'Tab') {
      if (event.key !== 'Tab') { event.preventDefault(); event.stopPropagation(); }
      setDropOpen(drop, false);
      if (event.key !== 'Tab') drop.querySelector('[data-drop-trigger]').focus();
    }
  }, true);

  // A click on an answer picks it and closes the menu.
  document.addEventListener('click', function (event) {
    var option = event.target.closest && event.target.closest('[data-drop] .select-option');
    if (!option || event.target.matches('input')) return;
    var drop = option.closest('[data-drop]');
    setTimeout(function () { setDropOpen(drop, false); }, 0);
  });

  // ---------- «Счётчики» of the service window: a free list of meters ----------

  function metersLabel(count) {
    var word = 'счётчиков';
    if (count % 10 === 1 && count % 100 !== 11) word = 'счётчик';
    else if (count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14)) word = 'счётчика';
    return count + ' ' + word;
  }

  // The count in the head, and the hidden layout radios: only common meters, only tenants', or both.
  function updateMeters(form) {
    var block = form.querySelector('[data-meters]');
    if (!block) return;
    var rows = block.querySelectorAll('[data-meter-list] [data-meter-row]');
    block.querySelector('[data-meter-count]').textContent = metersLabel(rows.length);
    var common = false, own = false;
    rows.forEach(function (row) {
      if (row.querySelector('input[name=meter_who]').value) own = true; else common = true;
    });
    var layout = own && common ? 'both' : own ? 'tenants' : 'common';
    var radio = form.querySelector('input[name=layout][value=' + layout + ']');
    if (radio && !radio.checked) {
      radio.checked = true;
      radio.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  // The night tariff repeats the meter's unit: «₽/м³».
  function echoUnit(row, unit) {
    row.querySelectorAll('[data-unit-echo]').forEach(function (el) { el.textContent = unit; });
  }

  function setMkindOpen(pick, open) {
    pick.classList.toggle('is-open', open);
    pick.querySelector('[data-mkind-menu]').hidden = !open;
    pick.querySelector('[data-mkind-trigger]').setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  // A kind picked: its name, and its usual unit for the tariff.
  function chooseMkind(pick, option) {
    pick.querySelector('input[name=meter_kind]').value = option.dataset.kind;
    pick.querySelector('input[name=meter_name]').value = option.dataset.name;
    var kindLabel = pick.querySelector('[data-mkind-label]');
    kindLabel.textContent = option.dataset.name;
    markFade(kindLabel);
    meterChanged(pick.closest('[data-meter-row]'));
    pick.querySelectorAll('.select-row').forEach(function (row) { row.classList.toggle('is-selected', row === option); });
    var unit = option.dataset.unit;
    var unitPick = pick.closest('[data-meter-row]').querySelector('.munit');
    if (unit && unitPick) {
      unitPick.querySelector('input').value = unit;
      unitPick.querySelector('[data-pick-label]').textContent = unit;
      unitPick.querySelectorAll('[data-pick-value]').forEach(function (row) {
        row.classList.toggle('is-selected', row.dataset.pickValue === unit);
      });
      echoUnit(pick.closest('[data-meter-row]'), unit);
    }
    setMkindOpen(pick, false);
    pick.querySelector('[data-mkind-trigger]').focus();
    formulaSoon(pick.closest('form'), 0);
  }

  // «свой вариант…»: a new kind with the landlord's own name, for this meter.
  function addMkind(pick) {
    var input = pick.querySelector('[data-mkind-new]');
    var name = input.value.trim();
    if (!name) return;
    var list = pick.querySelector('.select-list');
    var option = Array.prototype.filter.call(list.querySelectorAll('.select-row'), function (row) {
      return row.dataset.name.toLowerCase() === name.toLowerCase();
    })[0];
    if (!option) {
      option = document.createElement('li');
      option.className = 'select-row';
      option.dataset.kind = 'custom';
      option.dataset.name = name;
      option.dataset.unit = '';
      option.innerHTML = '<button type="button" class="select-option" role="option"><span></span>' +
        '<svg class="icon select-check"><use href="#i-check"/></svg></button>';
      option.querySelector('span').textContent = name;
      list.appendChild(option);
    }
    input.value = '';
    pick.querySelector('[data-mkind-add]').hidden = true;
    chooseMkind(pick, option);
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target.closest) return;
    var current = target.closest('[data-mkind]');
    document.querySelectorAll('[data-mkind].is-open').forEach(function (pick) {
      if (pick !== current) setMkindOpen(pick, false);
    });
    if (current) {
      if (target.closest('[data-mkind-trigger]')) {
        var open = !current.classList.contains('is-open');
        setMkindOpen(current, open);
        if (open) (current.querySelector('.is-selected .select-option') || current.querySelector('.select-option')).focus();
      } else if (target.closest('[data-mkind-add]')) {
        addMkind(current);
      } else if (target.closest('.select-row')) {
        chooseMkind(current, target.closest('.select-row'));
      }
      return;
    }

    var add = target.closest('[data-meter-add]');
    if (add) {
      var block = add.closest('[data-meters]');
      var row = block.querySelector('[data-meter-template]').content.firstElementChild.cloneNode(true);
      block.querySelector('[data-meter-list]').appendChild(row);
      initFades(row);
      dayPlaceholders(add.closest('form'));
      updateMeters(add.closest('form'));
      formulaSoon(add.closest('form'), 0);
      row.querySelector('[data-mkind-trigger]').focus();
      return;
    }

    var remove = target.closest('[data-meter-remove]');
    if (remove) { removeMeter(remove.closest('[data-meter-row]')); return; }

    var save = target.closest('[data-meter-save]');
    if (save) {
      var saveRow = save.closest('[data-meter-row]');
      if (saveRow.dataset.state === 'saved') {
        lockMeter(saveRow, false);
        saveRow.querySelector('input[name=meter_serial]').focus();
      } else {
        saveMeter(saveRow);
      }
      return;
    }

    var unitRow = target.closest('.munit [data-pick-value]');
    if (unitRow) echoUnit(unitRow.closest('[data-meter-row]'), unitRow.dataset.pickValue);

    // «Чей» picked (the pick handler above has already written it).
    var who = target.closest('.mwho [data-pick-value]');
    if (who) updateMeters(who.closest('form'));
    if (unitRow || who) meterChanged(target.closest('[data-meter-row]'));
  });

  // A meter row: «✓» saves it to the object; any change after that asks to save again.
  function meterChanged(row) {
    if (row && row.dataset.state === 'saved') row.dataset.state = 'new';
  }

  // A saved row is locked: its fields read only, its menus closed; the button turns into ✎.
  function lockMeter(row, locked) {
    row.dataset.state = locked ? 'saved' : 'new';
    row.querySelectorAll('input[type=text]').forEach(function (input) { input.readOnly = locked; });
    var button = row.querySelector('[data-meter-save]');
    button.setAttribute('aria-label', locked ? 'Изменить счётчик' : 'Сохранить счётчик');
    button.title = locked ? 'Изменить' : 'Сохранить';
  }

  // Day / night: the first tariff and start fields say «день», the second ones «ночь».
  function dayPlaceholders(form) {
    var two = !!form.querySelector('input[name=zones][value="2"]:checked');
    form.querySelectorAll('[data-placeholder-day]').forEach(function (input) {
      if (!input.dataset.placeholderOne) input.dataset.placeholderOne = input.placeholder;
      input.placeholder = two ? input.dataset.placeholderDay : input.dataset.placeholderOne;
    });
  }

  function initMeters(root) {
    root.querySelectorAll('[data-meter-row][data-state=saved]').forEach(function (row) { lockMeter(row, true); });
    root.querySelectorAll('form.rform').forEach(dayPlaceholders);
  }

  document.addEventListener('change', function (event) {
    if (event.target.matches && event.target.matches('.rform input[name=zones]')) dayPlaceholders(event.target.form);
  });

  // «Базовые»: a link that opens a small card with the meter's base readings (day and night for two tariffs).
  function setStartOpen(start, open) {
    start.querySelector('[data-start-card]').hidden = !open;
    start.querySelector('[data-start-toggle]').setAttribute('aria-expanded', open ? 'true' : 'false');
    start.classList.toggle('is-open', open);
  }

  function startDone(start) {
    setStartOpen(start, false);
    start.querySelector('[data-start-toggle]').focus();
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!target.closest) return;
    var current = target.closest('[data-start]');
    document.querySelectorAll('[data-start].is-open').forEach(function (start) {
      if (start !== current) setStartOpen(start, false);
    });
    if (!current) return;
    if (target.closest('[data-start-toggle]')) {
      // A saved row is locked: the word only shows its value on hover.
      if (current.closest('[data-meter-row]').dataset.state === 'saved') return;
      hideTip();
      var open = !current.classList.contains('is-open');
      setStartOpen(current, open);
      if (open) current.querySelector('[data-start-card] input').focus();
    } else if (target.closest('[data-start-done]')) {
      startDone(current);
    }
  });

  function meterBlock(row) {
    return row.closest('[data-meters]');
  }

  function saveMeter(row) {
    var block = meterBlock(row);
    var body = new FormData();
    row.querySelectorAll('input[name^=meter_]').forEach(function (input) { body.append(input.name, input.value); });
    body.append('csrfmiddlewaretoken', csrfToken(row.closest('form')));
    row.dataset.state = 'saving';
    fetch(block.dataset.saveUrl, { method: 'POST', body: body, credentials: 'same-origin' })
      .then(function (response) { if (!response.ok) throw new Error(response.status); return response.json(); })
      .then(function (data) {
        row.querySelector('input[name=meter_id]').value = data.id;
        lockMeter(row, true);
      })
      .catch(function () { row.dataset.state = 'error'; });
  }

  function removeMeter(row) {
    var block = meterBlock(row);
    var form = row.closest('form');
    var id = row.querySelector('input[name=meter_id]').value;
    function drop() {
      row.remove();
      updateMeters(form);
      formulaSoon(form, 0);
    }
    if (!id) { drop(); return; }
    var body = new FormData();
    body.append('receipt', block.dataset.receipt || '');
    body.append('csrfmiddlewaretoken', csrfToken(form));
    fetch(block.dataset.deleteUrl.replace('/0/', '/' + id + '/'), { method: 'POST', body: body, credentials: 'same-origin' })
      .then(function (response) { if (!response.ok) throw new Error(response.status); drop(); })
      .catch(function () { row.dataset.state = 'error'; });
  }

  document.addEventListener('input', function (event) {
    var meterRow = event.target.closest && event.target.closest('[data-meter-row]');
    if (meterRow && event.target.name && event.target.name.indexOf('meter_') === 0) meterChanged(meterRow);
    if (!event.target.matches || !event.target.matches('[data-mkind-new]')) return;
    event.target.closest('[data-mkind]').querySelector('[data-mkind-add]').hidden = !event.target.value.trim();
  });

  document.addEventListener('keydown', function (event) {
    var target = event.target;
    // Enter in the «Базовые» card: done (day → night first, when there are two fields).
    if (event.key === 'Enter' && target.matches && target.matches('[data-start-card] input')) {
      event.preventDefault();
      event.stopPropagation();
      var card = target.closest('[data-start-card]');
      var inputs = Array.prototype.filter.call(card.querySelectorAll('input'), function (i) { return i.offsetParent; });
      var next = inputs[inputs.indexOf(target) + 1];
      if (next) next.focus(); else startDone(target.closest('[data-start]'));
      return;
    }
    if (event.key === 'Escape' && target.closest && target.closest('[data-start-card]')) {
      event.preventDefault();
      event.stopPropagation();
      startDone(target.closest('[data-start]'));
      return;
    }
    var pick = target.closest && target.closest('[data-mkind].is-open');
    if (!pick) return;
    if (event.key === 'Enter' && target.matches('[data-mkind-new]')) {
      event.preventDefault();
      event.stopPropagation();
      addMkind(pick);
    } else if (event.key === 'Escape') {
      event.stopPropagation();
      setMkindOpen(pick, false);
      pick.querySelector('[data-mkind-trigger]').focus();
    }
  }, true);

  // «Формула» of the service window: the server recounts it from the form as it is now.
  var formulaTimer = null;
  var formulaRequest = 0;

  function refreshFormula(form) {
    var block = form.querySelector('[data-formula]');
    if (!block) return;
    var ticket = ++formulaRequest;
    fetch(block.dataset.formulaUrl, {
      method: 'POST',
      body: new FormData(form),
      headers: { 'X-CSRFToken': csrfToken(form) },
      credentials: 'same-origin',
    })
      .then(function (response) { return response.ok ? response.text() : null; })
      .then(function (html) {
        // Only the latest answer counts; an older one may arrive after it.
        if (html === null || ticket !== formulaRequest) return;
        var current = form.querySelector('[data-formula]');
        if (current) current.outerHTML = html;
      })
      .catch(function () {});
  }

  function formulaSoon(form, delay) {
    clearTimeout(formulaTimer);
    formulaTimer = setTimeout(function () { refreshFormula(form); }, delay);
  }

  ['input', 'change'].forEach(function (type) {
    document.addEventListener(type, function (event) {
      var form = event.target.closest && event.target.closest('form.rform');
      // Inside «Арендаторы» only the «платит» switches change the answer.
      var inside = event.target.closest('[data-formula]');
      if (form && (!inside || event.target.name === 'pays')) formulaSoon(form, type === 'input' ? 300 : 0);
    });
  });

  document.addEventListener('click', function (event) {
    // The unit picker writes a hidden input: no change event, so recount by hand.
    var unit = event.target.closest && event.target.closest('.rform [data-pick-value]');
    if (unit) { formulaSoon(unit.closest('form'), 0); return; }
    var who = event.target.closest && event.target.closest('[data-formula-for]');
    if (!who) return;
    var form = who.closest('form');
    form.querySelector('input[name=formula_for]').value = who.dataset.formulaFor;
    formulaSoon(form, 0);
  });

  initForms(document);
})();
