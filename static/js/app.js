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

  // Digit groups while typing: «17580» → «17 580», «55.7» → «55,7» (as the server shows numbers); the caret stays
  // after the same digit. Every number field of the app (2026-11-24: was only on the object page — the meter window kept «55.7»).
  function groupDigits(input) {
    var value = input.value;
    var caret = input.selectionStart == null ? value.length : input.selectionStart;
    var before = value.slice(0, caret).replace(/[^\d,.\-]/g, '').length;
    var clean = value.replace(/[\s ]/g, '').replace('.', ',');
    var match = clean.match(/^(-?)(\d+)(.*)$/);
    if (!match) return;
    var grouped = match[1] + match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + match[3];
    if (grouped === value) return;
    input.value = grouped;
    var pos = 0, seen = 0;
    while (pos < grouped.length && seen < before) {
      if (/[\d,.\-]/.test(grouped[pos])) seen++;
      pos++;
    }
    if (document.activeElement === input) input.setSelectionRange(pos, pos);
  }

  document.addEventListener('input', function (event) {
    var input = event.target;
    if (!input.isConnected || !input.matches) return;  // the service window redraws its fields on every key
    if (input.matches('input[inputmode="decimal"]:not(.num-input-coef)')) groupDigits(input);
  }, true);

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

  // «+ Добавить счётчик объекта» in the service window: the object window opens instead, and after its
  // «Сохранить» or «Отмена» the service window comes back with everything typed (the draft is kept in services.js).
  var serviceReturn = null;

  function returnToService() {
    var back = serviceReturn;
    serviceReturn = null;
    openModal(back.get);
  }

  if (dialog) {
    // «Все счётчики»: a click anywhere on a row opens its window (the service, or the object).
    document.addEventListener('click', function (event) {
      var row = event.target.closest && event.target.closest('tr[data-row-modal]');
      if (!row || event.target.closest('a, button, summary, details, input, label')) return;
      if (window.getSelection && String(window.getSelection())) return;
      openModal(row.getAttribute('data-row-modal'));
    });

    document.addEventListener('click', function (event) {
      var link = event.target.closest('a[data-modal]');
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      var dropdown = link.closest('[data-dropdown]');
      if (dropdown) dropdown.removeAttribute('open');
      if (link.hasAttribute('data-svc-return')) {
        // the new service window (2026-11-20): after the object window — back to it (the draft is kept in services.js)
        serviceReturn = { get: link.getAttribute('data-svc-return') };
      } else if (!dialog.contains(link)) {
        serviceReturn = null;
      }
      openModal(link.href);
    });

    // Only × and «Отмена» close the window: a stray click outside must not lose what was typed.
    dialog.addEventListener('click', function (event) {
      if (event.target.closest('[data-modal-close]')) {
        event.preventDefault();
        if (serviceReturn) returnToService();
        else { serviceReturn = null; dialog.close(); }
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
      // The pressed button's own name goes too («Не оплачено» in the payment window is name="unpay").
      var body = new FormData(form);
      if (event.submitter && event.submitter.name) body.append(event.submitter.name, event.submitter.value);
      if (button) button.disabled = true;
      fetch(form.action, {
        method: 'POST',
        body: body,
        headers: { 'X-Modal': '1' },
        credentials: 'same-origin',
      })
        .then(function (response) {
          var redirect = response.headers.get('X-Modal-Redirect');
          if (redirect && serviceReturn) {
            returnToService();  // the object is saved: back to the service window being filled in
            return null;
          }
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

  // E-mail: one check for the whole site — static/js/fields.js (2026-11-25).

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
          // the other unit, exact — both are stored (2026-11-24: no «≈»)
          text = isArea ? formatNumber(value / totalArea * 100) + '%'
                        : formatNumber(value * totalArea / 100) + ' м²';
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

    // A meter tile: an icon coloured by its kind (light — turquoise, cold water — blue, hot water — red…),
    // the name, then № · start and whose it is. Edit and × show on hover.
    var METER_ICONS = {
      electricity: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/></svg>',
      water: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.5c-.3 0-.6.2-.8.4C9.4 5.3 5.5 10.4 5.5 14.5a6.5 6.5 0 0 0 13 0c0-4.1-3.9-9.2-5.7-11.6-.2-.2-.5-.4-.8-.4z"/></svg>',
      heating: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 6v12M12 6v12M16 6v12M6 18v3M18 18v3"/></svg>',
      gas: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2s5 4.6 5 10a5 5 0 0 1-10 0c0-2.4 1.3-4.3 2.3-5.4.2 1.6 1 2.6 1.9 2.6C12.6 9.2 11 5.9 12 2z"/></svg>',
      custom: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="13" r="8"/><path d="M12 13l4-4M12 5V3"/></svg>'
    };
    METER_ICONS.hot_water = METER_ICONS.water;
    function meterKind(item) {
      var kind = val(item, 'kind');
      return METER_ICONS[kind] ? kind : 'custom';
    }

    // The start reading: a «play» icon instead of the word «старт».
    function startCell(item) {
      var start = el('span', 'info-cell info-start');
      start.title = 'Начальное показание';
      start.innerHTML = '<svg class="mt-start" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M7 5l12 7-12 7z"/></svg>';
      var startValue = startText(item);
      start.appendChild(startValue ? document.createTextNode(startValue) : el('span', 'info-none', '—'));
      return start;
    }

    // A meter row (2026-11-24, the style of the service window's list): the kind's icon — the same outline icon as there;
    // the name; under it smaller «№ … · tariff»; under that whose it is in a badge; ✎ × at the end. 76px.
    function meterTile(item, row) {
      var kind = meterKind(item);
      row.className = 'info-row meter-tile mk-' + kind;
      var icon = el('span', 'mt-icon');
      icon.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#' + (kind === 'custom' ? 'i-gauge' : 'i-r-' + kind) + '"/></svg>';
      row.appendChild(icon);
      var body = el('span', 'mt-body');
      var top = el('span', 'mt-top');
      var main = el('span', 'info-cell info-main', val(item, 'name'));
      if (isDayNight(item)) main.appendChild(el('span', 'info-label', ' день / ночь'));
      top.appendChild(main);
      body.appendChild(top);
      var line = el('span', 'mt-line');
      line.appendChild(cell('info-serial', '№', val(item, 'serial'), '№ —'));
      // Its tariff (2026-11-19): «9,6 / 4,2 ₽/кВт·ч», or a red «нет тарифа».
      var day = val(item, 'tariff'), nightTariff = val(item, 'tariff_night');
      // In a «По расходу» service (2026-11-23) no tariff is needed: «из квитанции», grey.
      var fromReceipt = !day && 'byUsage' in item.dataset;
      var tariff = el('span', 'info-cell mt-tariff-cell' + (day || fromReceipt ? '' : ' is-none'),
        day ? (isDayNight(item) ? day + ' / ' + (nightTariff || '—') : day) + ' ₽/' + val(item, 'unit') : fromReceipt ? 'из квитанции' : 'нет тарифа');
      line.appendChild(tariff);
      body.appendChild(line);
      // Whose it is — the third line (2026-11-24: less noise next to the name).
      var who = meterWho(item);
      var whoEl = el('span', 'who-badge mt-who ' + who.cls, who.text);
      whoEl.title = who.text;
      body.appendChild(whoEl);
      row.appendChild(body);
      var acts = el('span', 'mt-acts');
      row.appendChild(acts);
      row.title = 'Изменить счётчик';
      return acts;
    }

    function infoRow(item, number, kind) {
      var row = el('div', 'info-row info-' + kind);
      row.tabIndex = 0;
      row.setAttribute('role', 'button');
      row.itemRef = item;
      var buttons = row;
      if (kind === 'meter') {
        buttons = meterTile(item, row);
      } else {
        row.appendChild(el('span', 'inum', String(number)));
        row.appendChild(el('span', 'info-cell info-main', val(item, 'name')));
        var share = val(item, 'share');
        var hint = item.querySelector('[data-share-hint]');
        var shareCell = cell('info-share', '', share ? share + (shareUnit() === '%' ? '%' : ' м²') : '', 'доля —');
        if (share && hint && hint.textContent) shareCell.appendChild(el('span', 'info-label share-alt', ' · ' + hint.textContent));
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
      buttons.appendChild(edit);
      buttons.appendChild(remove);
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
        if (kind === 'meter') {
          // «+ Добавить счётчик» — the last tile, dashed, the size of a meter tile (2026-11-27)
          var addCell = el('button', 'meter-add-cell', '+ Добавить счётчик');
          addCell.type = 'button';
          addCell.dataset.itemAdd = '';
          list.appendChild(addCell);
        } else if (!all.length) {
          list.appendChild(el('p', 'info-empty', kind === 'meter' ? 'Счётчиков пока нет' : 'Арендаторов пока нет'));
        }
        var count = block.querySelector('[data-items-count]');
        if (count) count.textContent = all.length ? all.length + ' шт.' : '';
        // the object window's menu: «Счётчики 2», «Арендаторы 3»
        var navCount = form.querySelector('[data-ocount="' + kind + '"]');
        if (navCount) navCount.textContent = all.length || '';
      });
    }

    // ---- a meter's own controls ----

    function syncMeter(item) {
      var dn = isDayNight(item);
      // The start reading and the tariff (2026-11-19): both have a night field and «· день» on the day one.
      item.querySelectorAll('[data-night-field]').forEach(function (night) { night.hidden = !dn; });
      item.querySelectorAll('[data-day-label]').forEach(function (dayLabel) { dayLabel.hidden = !dn; });
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
      item.querySelectorAll('[data-tariff-unit]').forEach(function (span) { span.textContent = unit; });
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
      if (current && current.item === item) syncHead();
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
            '<svg class="icon select-check"><use href="#i-check"/></svg></button>' +
            '<button type="button" class="select-remove" data-msel-remove title="Убрать вариант" aria-label="Убрать вариант">' +
            '<svg class="icon"><use href="#i-x"/></svg></button>';
          found.querySelector('span').textContent = name;
          list.appendChild(found);
        }
        if (item.contains(list)) mine = found;
      });
      input.value = '';
      item.querySelector('[data-msel-add]').hidden = true;
      chooseKind(item, mine);
    }

    // × at an own variant: gone from every menu; this meter goes back to the first kind.
    function removeKind(item, row) {
      var name = row.dataset.name;
      var lists = Array.prototype.slice.call(form.querySelectorAll('[data-msel] .select-list'));
      var template = blocks.meter.querySelector('[data-item-template]');
      if (template) lists = lists.concat(Array.prototype.slice.call(template.content.querySelectorAll('.select-list')));
      lists.forEach(function (list) {
        list.querySelectorAll('.select-row').forEach(function (other) {
          if (other.dataset.kind === 'custom' && other.dataset.name === name) other.parentNode.removeChild(other);
        });
      });
      if (val(item, 'kind') === 'custom' && val(item, 'name') === name) {
        chooseKind(item, item.querySelector('[data-msel] .select-row'));
      } else {
        syncMeter(item);
      }
    }

    // ---- the tenant's meters: read-only (2026-11-13) ----
    // A tenant is seated on a meter in the service window, not here. This block only shows the meters
    // the tenant pays by — no ticks, nothing to change; empty — a note where they will show up.

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
      var mine = [];
      items('meter').forEach(function (meter, i) {
        if (key && val(meter, 'owner') === key) mine.push([meter, i]);
      });
      count.textContent = mine.length ? mine.length + ' шт.' : '';
      if (!mine.length) {
        sectionBody.appendChild(el('p', 'form-note tm-empty', 'Здесь будут счётчики, привязанные к этому арендатору.'));
        return section;
      }
      var list = el('div', 'tm-list');
      mine.forEach(function (pair) {
        var meter = pair[0];
        var row = el('div', 'tm-row is-readonly');
        row.appendChild(el('span', 'inum', String(pair[1] + 1)));
        var kind = meterKind(meter);
        var icon = el('span', 'tm-icon mk-' + kind);
        icon.innerHTML = METER_ICONS[kind];
        row.appendChild(icon);
        row.appendChild(el('span', 'info-cell info-main', val(meter, 'name')));
        row.appendChild(cell('', '№', val(meter, 'serial'), '№ —'));
        row.appendChild(startCell(meter));
        list.appendChild(row);
      });
      sectionBody.appendChild(list);
      return section;
    }

    // The small window's grey head (2026-11-23): what is typed — the tenant's name and, after it, the share
    // in short («45% · 49,5 м²»; nothing typed yet — «можно до 55%»); a meter — its kind and №.
    function syncHead() {
      if (!current) return;
      var item = current.item;
      var title = sub.querySelector('[data-subwin-title]');
      var note = sub.querySelector('[data-subwin-sub]');
      var name, text = '', warn = false;
      if (current.kind === 'tenant') {
        name = val(item, 'name').trim();
        var unit = shareUnit() === '%' ? '%' : ' м²';
        var share = parseNumber(val(item, 'share'));
        var free = freeShare(item);
        if (share !== null) {
          var hint = item.querySelector('[data-share-hint]');
          text = formatNumber(share) + unit + (hint && hint.textContent ? ' · ' + hint.textContent : '');
          if (free !== null && share > free) { text += ' · можно до ' + formatNumber(free) + unit; warn = true; }
        } else if (free !== null) {
          text = free > 0 ? 'можно до ' + formatNumber(free) + unit : 'объект занят полностью';
          warn = !(free > 0);
        }
        title.textContent = name || (current.isNew ? 'Новый арендатор' : 'Арендатор ' + current.number);
      } else {
        var serial = val(item, 'serial').trim().replace(/^№\s*/, '');
        name = val(item, 'name');
        title.textContent = current.isNew && !serial ? 'Новый счётчик' : name;
        text = serial ? '№ ' + serial : '';
      }
      title.classList.toggle('is-empty', !name);
      // in a badge (2026-11-23): blue; more than is free / the object full — orange
      note.textContent = text;
      note.hidden = !text;
      note.className = 'subwin-sub badge ' + (warn ? 'badge-warn' : 'badge-info');
    }

    function syncTenantMeters() {
      if (!current || current.kind !== 'tenant') return;
      var title = sub.querySelector('[data-tm-title]');
      if (title) title.textContent = 'Счётчики · ' + (val(current.item, 'name') || 'арендатор ' + current.number);
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
      if (kind === 'meter') {
        var head = item.querySelector('.form-section-head');
        if (head && !head.querySelector('[data-subwin-badge]')) {
          var badge = el('span', 'head-badge');
          badge.dataset.subwinBadge = '';
          head.appendChild(badge);
        }
        syncMeter(item);
      } else {
        body.appendChild(tenantMeters(item));
        syncTenantMeters();
      }
      syncHead();
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
        ? ['initial'].concat(isDayNight(item) ? ['initial_night'] : [])  // the tariff is optional (2026-11-23)
        : ['name', 'share'];
      need.forEach(function (suffix) {
        var input = item.querySelector('input[name$="-' + suffix + '"]');
        if (input && !input.value.trim()) {
          clientError(input.closest('.field'), 'Заполните поле.');
          empty.push(input);
        }
      });
      // a number, a date, an e-mail — the same check as on leaving the field (fields.js)
      item.querySelectorAll('input:not([type=hidden]):not([type=radio]):not([type=checkbox])').forEach(function (input) {
        if (input.closest('.field') && window.rentflowFields.check(input, false)) empty.push(input);
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

    // A meter a service counts by can't be deleted: say so in a small window, with the way to the service.
    // («Общий» / a tenant is only who pays by it; the tie to a service is the switch in that service.)
    function meterInService(item) {
      if (item.dataset.item !== 'meter' || !item.dataset.services) return false;
      var many = item.dataset.services.indexOf('», «') !== -1;
      var note = el('div', 'subwin subwin-note');
      note.innerHTML =
        '<div class="subwin-panel" role="alertdialog" aria-modal="true" aria-labelledby="note-title">' +
        '<header class="modal-head"><div><h1 id="note-title">Счётчик привязан к услуге</h1></div>' +
        '<button type="button" class="icon-button modal-close" data-note-close aria-label="Закрыть"><svg class="icon"><use href="#i-x"/></svg></button></header>' +
        '<p class="note-text"></p>' +
        '<div class="form-actions"><button type="button" class="btn btn-ghost btn-auto" data-note-close>Понятно</button>' +
        '<a class="btn btn-primary btn-auto" data-modal>Открыть услугу</a></div></div>';
      note.querySelector('.note-text').textContent = 'По этому счётчику ' + (many ? 'считаются услуги ' : 'считается услуга ') +
        item.dataset.services + '. Зайдите в услугу и выключите в ней этот счётчик — после этого его можно удалить.';
      note.querySelector('a[data-modal]').href = item.dataset.serviceUrl;
      note.addEventListener('click', function (event) {
        if (event.target.closest('[data-note-close]') || event.target.closest('a[data-modal]') || event.target === note) note.remove();
      });
      (form.closest('dialog') || document.body).appendChild(note);
      note.querySelector('[data-note-close]').focus();
      return true;
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
        if (meterInService(infoRemove.closest('.info-row').itemRef)) return;
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
        if (meterInService(current.item)) return;
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
        else if (target.closest('[data-msel-remove]')) removeKind(item, target.closest('.select-row'));
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
      if (current && current.item.contains(event.target)) syncHead();
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
    // «Тарифы» → a meter's row (2026-11-23): the object window opens right on that meter's small window.
    else if (form.dataset.openMeter) {
      var idInput = form.querySelector('[data-item-store] [data-item="meter"] input[name$="-id"][value="' + form.dataset.openMeter + '"]');
      if (idInput) openItem(idInput.closest('[data-item]'), false);
    }
  }

  // ---------- The object window (2026-11-22): the service window's frame — parts on the left, one save for all ----------
  function formState(form) {
    var pairs = [];
    new FormData(form).forEach(function (value, key) { if (key !== 'csrfmiddlewaretoken') pairs.push(key + '=' + value); });
    return pairs.join('&');
  }

  function initObjectWindow(form) {
    if (form.dataset.objwinReady) return;
    form.dataset.objwinReady = '1';
    var start = '';
    setTimeout(function () { start = formState(form); }, 0);  // once the rows of meters and tenants are drawn
    // The form stays one long sheet, as before (2026-11-22); the menu rolls a part up as far as the sheet goes, and while
    // scrolling the part you are in is lit in the menu. Scrolled to the end by hand — the last part is lit.
    var pane = form.querySelector('.svcwin-pane');
    var top = form.querySelector('.sv-top');
    var parts = Array.prototype.slice.call(form.querySelectorAll('[data-part]'));
    var rolling = false;
    function headH() { return top ? top.offsetHeight : 0; }
    function light(name) {
      form.querySelectorAll('[data-opart]').forEach(function (b) { b.classList.toggle('is-on', b.dataset.opart === name); });
    }
    function partTop(sec) { return sec.offsetTop - headH() - 20; }
    // A click in the menu puts that part at the top ALWAYS (2026-11-24): when the sheet is too short, an empty room is added
    // under the last part — just enough; scrolling back up the room shrinks again, so there is never more than is needed.
    var room = document.createElement('div');
    room.className = 'objwin-room';
    room.setAttribute('aria-hidden', 'true');
    if (parts.length) parts[parts.length - 1].after(room);
    function fitRoom() {
      var bottom = pane.scrollHeight - room.offsetHeight;  // where the sheet ends without the room
      room.style.height = Math.max(0, Math.ceil(pane.scrollTop + pane.clientHeight - bottom)) + 'px';
    }
    form.addEventListener('click', function (event) {
      var part = event.target.closest('[data-opart]');
      if (!part || !pane) return;
      var sec = form.querySelector('[data-part="' + part.dataset.opart + '"]');
      light(part.dataset.opart);
      var to = Math.max(0, partTop(sec));
      var bottom = pane.scrollHeight - room.offsetHeight;
      room.style.height = Math.max(room.offsetHeight, Math.ceil(to + pane.clientHeight - bottom)) + 'px';
      rolling = true;
      pane.scrollTo({ top: to, behavior: 'smooth' });
      // the room is fitted again only once the roll has ended — never in the middle of it (it would cut the roll short)
      clearTimeout(form.rollTimer);
      form.rollTimer = setTimeout(function () { rolling = false; }, 1500);
    });
    if (pane) pane.addEventListener('scrollend', function () { if (rolling) { clearTimeout(form.rollTimer); rolling = false; } fitRoom(); });
    if (pane) {
      pane.addEventListener('scroll', function () {
        if (rolling) return;
        fitRoom();
        var at = parts[0];
        parts.forEach(function (sec) { if (partTop(sec) <= pane.scrollTop + 8) at = sec; });
        if (pane.scrollTop > 0 && !room.offsetHeight && pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 2) at = parts[parts.length - 1];
        light(at.dataset.part);
      });
      // The part with an error: rolled up to it once drawn.
      var open = form.querySelector('[data-opart].is-on');
      if (open && open.dataset.opart !== 'object') {
        setTimeout(function () {
          var to = Math.max(0, partTop(form.querySelector('[data-part="' + open.dataset.opart + '"]')));
          room.style.height = Math.max(0, Math.ceil(to + pane.clientHeight - (pane.scrollHeight - room.offsetHeight))) + 'px';
          pane.scrollTop = to;
        }, 0);
      }
    }
    // The name in the head follows the field.
    var name = form.querySelector('input[name=name]');
    var head = form.querySelector('[data-oname]');
    if (name && head) {
      name.addEventListener('input', function () { head.textContent = name.value.trim() || 'Новый объект'; });
    }
    // Another object (or a new one) from the menu: with unsaved changes — ask first, as the service window does.
    form.addEventListener('click', function (event) {
      var go = event.target.closest('[data-obj-go]');
      if (!go || formState(form) === start) return;
      event.preventDefault();
      event.stopPropagation();
      var ask = document.createElement('div');
      ask.className = 'sv-back';
      ask.innerHTML = '<div class="sv-mw" role="dialog" aria-modal="true" aria-label="Сохранить изменения?">' +
        '<div class="sv-mw-head"><b>Сохранить изменения?</b></div>' +
        '<div class="sv-mw-body"><p class="sv-note">В этом объекте есть несохранённые изменения. Если перейти, они пропадут.</p></div>' +
        '<div class="sv-mw-foot"><button type="button" class="btn btn-ghost btn-auto sv-ask-drop" data-ask-drop>Не сохранять</button>' +
        '<button type="button" class="btn btn-ghost btn-auto" data-ask-stay>Отмена</button>' +
        '<button type="button" class="btn btn-primary btn-auto" data-ask-save>Сохранить</button></div></div>';
      form.appendChild(ask);
      ask.addEventListener('click', function (e) {
        if (e.target.closest('[data-ask-drop]')) { ask.remove(); openModal(go.href); return; }
        if (e.target.closest('[data-ask-save]')) { ask.remove(); form.requestSubmit(); return; }
        if (e.target.closest('[data-ask-stay]') || e.target === ask) ask.remove();
      });
      ask.querySelector('[data-ask-save]').focus();
    }, true);
  }

  function initForms(root) {
    root.querySelectorAll('[data-property-form]').forEach(initPropertyForm);
    root.querySelectorAll('[data-objwin]').forEach(initObjectWindow);
    root.querySelectorAll('[data-subwin]').forEach(function (sub) { initItems(sub.closest('form')); });
    initFades(root);
    if (window.initServiceWindow) window.initServiceWindow(root);  // «Услуги · объект» (services.js)
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

  // «Все услуги», «Тарифы», «Счётчики» (2026-11-23): filters right in the row of column names — th[data-filter]:
  // a funnel after the name; a click — the column's values to choose one («Все» — off), the choice lights the name
  // as a plaque. A value is the cell's data-v, else its link or tag («Тест Круг», «по долям»). A menu offers only the
  // values left by the other filters; a long one (9+) gets a search line on top. The object (data-filter-key="obj")
  // is remembered for all three pages.
  var FILTER_OBJ = 'rentflow.tableObject';
  function cellValue(cell) {
    if (!cell) return '';
    if (cell.dataset.v) return cell.dataset.v.trim();
    var el = cell.querySelector('a, .tag');
    return (el || cell).textContent.replace(/\s+/g, ' ').trim();
  }
  document.querySelectorAll('table.svc-table').forEach(function (table) {
    var heads = Array.prototype.slice.call(table.querySelectorAll('thead th[data-filter]'));
    if (!heads.length) return;
    var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
    var none = document.createElement('tr');
    none.className = 'tbl-none';
    none.hidden = true;
    none.innerHTML = '<td colspan="' + table.querySelectorAll('thead th').length + '">Ничего не найдено. <button type="button" class="link-button">Сбросить фильтры</button></td>';
    table.querySelector('tbody').appendChild(none);
    var filters = heads.map(function (th) {
      var col = Array.prototype.indexOf.call(th.parentNode.children, th);
      var f = { th: th, col: col, value: '', key: th.dataset.filterKey || '', label: th.textContent.trim() };
      th.innerHTML = '';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'th-filter';
      btn.innerHTML = '<span></span><svg class="icon"><use href="#i-filter"/></svg>';
      btn.querySelector('span').textContent = f.label;
      th.appendChild(btn);
      f.btn = btn;
      if (f.key === 'obj') {
        var saved = '';
        try { saved = localStorage.getItem(FILTER_OBJ) || ''; } catch (e) {}
        if (saved && rows.some(function (r) { return cellValue(r.children[col]) === saved; })) f.value = saved;
      }
      return f;
    });
    function passes(row, skip) {
      return filters.every(function (f) { return f === skip || !f.value || cellValue(row.children[f.col]) === f.value; });
    }
    function apply() {
      var shown = 0;
      rows.forEach(function (row) {
        var ok = passes(row, null);
        row.hidden = !ok;
        if (ok) shown += 1;
      });
      none.hidden = !!shown;
      filters.forEach(function (f) {
        f.btn.classList.toggle('is-on', !!f.value);
        f.btn.title = f.value ? f.label + ': ' + f.value : 'Фильтр: ' + f.label;
      });
    }
    var menu = null;
    function closeMenu() { if (menu) { menu.remove(); menu = null; } filters.forEach(function (f) { f.btn.classList.remove('is-open'); }); }
    function setValue(f, value) {
      f.value = value;
      if (f.key === 'obj') { try { localStorage.setItem(FILTER_OBJ, value); } catch (e) {} }
      apply();
    }
    function openMenu(f) {
      closeMenu();
      f.btn.classList.add('is-open');
      menu = document.createElement('div');
      menu.className = 'th-menu';
      var values = [];
      rows.forEach(function (r) {
        var v = cellValue(r.children[f.col]);
        if (v && values.indexOf(v) < 0 && passes(r, f)) values.push(v);
      });
      values.sort(function (a, b) { return a.localeCompare(b, 'ru'); });
      if (values.length > 8) {
        menu.innerHTML = '<label class="tbl-search"><svg class="icon"><use href="#i-search"/></svg><input type="search" autocomplete="off" placeholder="Найти"></label>';
      }
      [''].concat(values).forEach(function (v) {
        var item = document.createElement('button');
        item.type = 'button';
        item.className = 'th-item' + (v === f.value ? ' is-on' : '');
        item.dataset.v = v;
        item.innerHTML = '<span class="fade"></span><svg class="icon"><use href="#i-check"/></svg>';
        item.querySelector('span').textContent = v || 'Все';
        item.addEventListener('click', function () { setValue(f, v); closeMenu(); });
        menu.appendChild(item);
      });
      document.body.appendChild(menu);
      var r = f.btn.getBoundingClientRect();
      menu.style.top = (r.bottom + 6) + 'px';
      menu.style.left = Math.max(8, Math.min(r.left, innerWidth - menu.offsetWidth - 8)) + 'px';
      var field = menu.querySelector('input');
      if (field) {
        field.addEventListener('input', function () {
          var q = field.value.trim().toLowerCase();
          menu.querySelectorAll('.th-item').forEach(function (it) {
            it.hidden = !!q && (!it.dataset.v || it.dataset.v.toLowerCase().indexOf(q) < 0);
          });
        });
        field.addEventListener('keydown', function (e) {
          if (e.key !== 'Enter') return;
          e.preventDefault();
          var first = menu.querySelector('.th-item:not([hidden])' + (field.value.trim() ? '[data-v]:not([data-v=""])' : ''));
          if (first) first.click();
        });
        field.focus();
      }
    }
    filters.forEach(function (f) {
      f.btn.addEventListener('click', function (e) {
        e.stopPropagation();
        if (f.btn.classList.contains('is-open')) closeMenu(); else openMenu(f);
      });
    });
    none.querySelector('button').addEventListener('click', function () {
      filters.forEach(function (f) { if (f.value) setValue(f, ''); });
    });
    document.addEventListener('click', function (e) { if (menu && !menu.contains(e.target)) closeMenu(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });
    window.addEventListener('scroll', function (e) { if (menu && !menu.contains(e.target)) closeMenu(); }, true);
    window.addEventListener('resize', closeMenu);
    apply();
  });

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

  // «Оплаты» (variant А): a cell is marked right in place — the small check (paid today / not paid), the date typed or
  // picked in the calendar; «?» opens the note window. The server answers with the board drawn anew.
  var payBoard = document.querySelector('[data-pay-board]');
  if (payBoard) {
    var payBody = payBoard.querySelector('[data-pay-body]');
    var noteBack = document.querySelector('[data-pay-note-back]');
    var noteCell = null;
    // Every change posts and gets the board drawn anew; resolves with the response (its headers say more).
    var postBoard = function (url, fields) {
      var body = new FormData();
      Object.keys(fields).forEach(function (key) { body.append(key, fields[key]); });
      body.append('view', payBoard.dataset.month);
      return fetch(url, {
        method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrfToken(payBoard) }
      }).then(function (response) {
        if (!response.ok) throw new Error('payments: ' + response.status);
        return response.text().then(function (html) {
          closeDate();
          payBody.innerHTML = html;
          initFades(payBody);  // the new names fade out too, not only the ones the page came with
          return response;
        });
      });
    };
    var postCell = function (cell, fields) { return postBoard(cell.dataset.url, fields); };
    var tileByCode = function (code) { return payBody.querySelector('.pay-sq[data-code="' + code + '"]'); };

    // The receipt window (2026-11-25): the name, its services with «×», «Разъединить».
    var bundleBack = document.querySelector('[data-pay-bundle-back]');
    var bundleCode = null, bundleName = '';
    var fillBundle = function (tile) {
      bundleBack.querySelector('[data-pay-bundle-title]').textContent = tile.dataset.title;
      bundleBack.querySelector('[data-pay-bundle-sub]').textContent = tile.dataset.sub + ' · одна квитанция, один платёж';
      var list = bundleBack.querySelector('[data-pay-bundle-list]');
      list.innerHTML = tile.querySelector('[data-pay-parts]').innerHTML;
      bundleBack.hidden = false;  // measured visible, or nothing is «clipped»
      initFades(list);
      list.querySelectorAll('.pay-part').forEach(function (row) {
        var out = document.createElement('button');
        out.type = 'button'; out.className = 'pay-out'; out.textContent = '×';
        out.title = 'Вынуть из квитанции'; out.setAttribute('data-pay-out', row.dataset.id);
        row.appendChild(out);
      });
      var total = document.createElement('div');
      total.className = 'pay-part is-total';
      total.innerHTML = '<span class="fade">Квитанция</span><span class="pay-part-sum"></span>';
      total.querySelector('.pay-part-sum').textContent = tile.querySelector('.pay-sum').textContent.trim();
      list.appendChild(total);
    };
    var openBundle = function (tile, fresh) {
      bundleCode = tile.dataset.code;
      bundleName = tile.dataset.title;
      fillBundle(tile);
      var input = bundleBack.querySelector('[data-pay-bundle-name]');
      input.value = bundleName;
      bundleBack.hidden = false;
      if (fresh) { input.focus(); input.select(); }
    };
    // Closing saves a changed name (Готово, Enter, Esc, a click outside — all the same: nothing is lost).
    var closeBundle = function () {
      if (bundleBack.hidden) return;
      var tile = bundleCode && tileByCode(bundleCode);
      var name = bundleBack.querySelector('[data-pay-bundle-name]').value.trim();
      bundleBack.hidden = true;
      bundleCode = null;
      if (tile && name && name !== bundleName) postBoard(tile.dataset.bundleUrl, { name: name });
    };
    bundleBack.addEventListener('input', function (event) {
      if (!event.target.matches('[data-pay-bundle-name]')) return;
      bundleBack.querySelector('[data-pay-bundle-title]').textContent = event.target.value.trim() || 'Квитанция';
    });
    bundleBack.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === 'Escape') { event.preventDefault(); closeBundle(); }
    });
    bundleBack.addEventListener('click', function (event) {
      if (event.target === bundleBack || event.target.closest('[data-pay-bundle-done]')) { closeBundle(); return; }
      var tile = bundleCode && tileByCode(bundleCode);
      if (!tile) return;
      if (event.target.closest('[data-pay-bundle-split]')) {
        bundleBack.hidden = true;
        postBoard(tile.dataset.bundleUrl, { split: '1' });
        return;
      }
      var out = event.target.closest('[data-pay-out]');
      if (out) {
        var code = bundleCode;
        postBoard(tile.dataset.bundleUrl, { out: out.getAttribute('data-pay-out') }).then(function () {
          var again = tileByCode(code);  // one service left — the receipt is gone, so is the window
          if (again) fillBundle(again); else { bundleBack.hidden = true; bundleCode = null; }
        });
      }
    });

    // Drag a tile onto another tile of the same object — one receipt, as apps into a folder on a phone (2026-11-25).
    // Other objects' tiles go pale: nothing to drop there. Dropped onto a service — a new receipt, its window opens.
    var drag = null, press = null, dragged = false;
    var dropOff = function () {
      payBody.querySelectorAll('.is-drop, .is-off, .is-src').forEach(function (el) { el.classList.remove('is-drop', 'is-off', 'is-src'); });
    };
    payBoard.addEventListener('pointerdown', function (event) {
      var tile = event.target.closest('.pay-sq[data-code]');
      if (!tile || event.button || event.target.closest('[data-pay-toggle], [data-pay-note], input')) return;
      press = { tile: tile, x: event.clientX, y: event.clientY };
    });
    document.addEventListener('pointermove', function (event) {
      if (!drag) {
        if (!press || Math.abs(event.clientX - press.x) + Math.abs(event.clientY - press.y) < 6) return;
        var tile = press.tile, box = tile.getBoundingClientRect();
        var ghost = tile.cloneNode(true);
        ghost.classList.add('pay-ghost');
        ghost.classList.remove('is-folder');
        ghost.style.left = box.left + 'px';
        ghost.style.top = box.top + 'px';
        document.body.appendChild(ghost);
        var row = tile.closest('[data-pay-row]');
        tile.classList.add('is-src');
        payBody.querySelectorAll('.pay-sq[data-code]').forEach(function (other) {
          if (other.closest('[data-pay-row]') !== row) other.classList.add('is-off');
        });
        drag = { tile: tile, ghost: ghost, row: row, dx: press.x - box.left, dy: press.y - box.top, over: null };
        press = null;
      }
      drag.ghost.style.left = (event.clientX - drag.dx) + 'px';
      drag.ghost.style.top = (event.clientY - drag.dy) + 'px';
      var hit = document.elementFromPoint(event.clientX, event.clientY);
      var over = hit && hit.closest('.pay-sq[data-code]');
      if (over && (over === drag.tile || over.closest('[data-pay-row]') !== drag.row)) over = null;
      if (over !== drag.over) {
        if (drag.over) drag.over.classList.remove('is-drop');
        if (over) over.classList.add('is-drop');
        drag.over = over;
      }
    });
    document.addEventListener('pointerup', function () {
      press = null;
      if (!drag) return;
      var done = drag;
      drag = null;
      dragged = true;
      setTimeout(function () { dragged = false; });
      done.ghost.remove();
      if (!done.over) { dropOff(); return; }
      postBoard(payBoard.dataset.mergeUrl, { src: done.tile.dataset.code, dst: done.over.dataset.code }).then(function (response) {
        var made = response.headers.get('X-Pay-Bundle');
        var tile = made ? tileByCode('b' + made) : null;
        if (!tile) tile = done.over.dataset.code.charAt(0) === 'b' ? tileByCode(done.over.dataset.code) : null;
        if (tile) tile.classList.add('is-just');
        if (made && tile) openBundle(tile, true);
      }).catch(dropOff);
    });
    // A drag ends with a click on the tile under it: not a click.
    payBoard.addEventListener('click', function (event) {
      if (dragged) { event.preventDefault(); event.stopPropagation(); }
    }, true);
    payBoard.addEventListener('click', function (event) {
      var toggle = event.target.closest('[data-pay-toggle]');
      if (toggle) {
        var cell = toggle.closest('[data-pay-tile]');
        postCell(cell, { paid: cell.classList.contains('is-paid') ? '0' : '1' });
        return;
      }
      var open = event.target.closest('[data-pay-open]');
      if (open) { openBundle(open.closest('[data-pay-tile]')); return; }
      var q = event.target.closest('[data-pay-note]');
      if (!q) return;
      noteCell = q.closest('[data-pay-tile]');
      noteBack.querySelector('[data-pay-note-title]').textContent = 'Пометка · ' + noteCell.dataset.title;
      noteBack.querySelector('[data-pay-note-sub]').textContent = noteCell.dataset.sub;
      noteBack.querySelector('[data-pay-note-text]').value = noteCell.dataset.note || '';
      noteBack.querySelector('[data-pay-note-carry]').checked = noteCell.dataset.carry === '1';
      noteBack.querySelector('[data-pay-note-clear]').hidden = !noteCell.dataset.note;
      noteBack.hidden = false;
      noteBack.querySelector('[data-pay-note-text]').focus();
    });
    var closeNote = function () { noteBack.hidden = true; noteCell = null; };
    noteBack.addEventListener('click', function (event) {
      if (event.target === noteBack || event.target.closest('[data-pay-note-cancel]')) { closeNote(); return; }
      if (!noteCell) return;
      var cell = noteCell;
      if (event.target.closest('[data-pay-note-clear]')) {
        postCell(cell, { note: '', carry: '0' }).then(closeNote);
      } else if (event.target.closest('[data-pay-note-save]')) {
        postCell(cell, {
          note: noteBack.querySelector('[data-pay-note-text]').value,
          carry: noteBack.querySelector('[data-pay-note-carry]').checked ? '1' : '0'
        }).then(closeNote);
      }
    });
    document.addEventListener('keydown', function (event) {
      if (noteBack.hidden) return;
      if (event.key === 'Escape') closeNote();
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) noteBack.querySelector('[data-pay-note-save]').click();
    });
    payBoard.addEventListener('change', function (event) {
      if (!event.target.matches('[data-pay-date]')) return;
      // A date typed or picked in the calendar; cleared — not paid.
      var day = event.target.value.trim();
      postCell(event.target.closest('[data-pay-tile]'), { paid: day ? '1' : '0', paid_on: day });
    });
    payBoard.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && event.target.matches('[data-pay-date]')) { event.preventDefault(); event.target.blur(); }
    });
  }

  // «Поделиться» under the bill (2026-11-17). The PDF file goes to the phone's share sheet (Telegram, WhatsApp…)
  // where the browser can share files; the menu also has WhatsApp / Telegram with the bill as text, and «copy».
  // Delegated: the bill is redrawn live after each input.
  var shareFile = function (box) {
    return fetch(box.dataset.pdf, { credentials: 'same-origin' })
      .then(function (response) { return response.blob(); })
      .then(function (blob) { return new File([blob], box.dataset.file, { type: 'application/pdf' }); });
  };
  var closeShare = function () {
    document.querySelectorAll('[data-share-menu]').forEach(function (menu) {
      menu.hidden = true;
      var opener = menu.parentNode.querySelector('[data-share-open]');
      if (opener) opener.setAttribute('aria-expanded', 'false');
    });
  };
  document.addEventListener('click', function (event) {
    var box = event.target.closest('[data-share]');
    if (!box) { closeShare(); return; }
    var menu = box.querySelector('[data-share-menu]');
    if (event.target.closest('[data-share-open]')) {
      var open = menu.hidden;
      closeShare();
      menu.hidden = !open;
      event.target.closest('[data-share-open]').setAttribute('aria-expanded', open ? 'true' : 'false');
      // Where files can't be shared (a desktop browser), «Отправить PDF…» would do nothing: hidden.
      var probe = new File([''], 'a.pdf', { type: 'application/pdf' });
      menu.querySelector('[data-share-file]').hidden = !(navigator.canShare && navigator.canShare({ files: [probe] }));
      return;
    }
    if (event.target.closest('[data-share-file]')) {
      shareFile(box).then(function (file) {
        return navigator.share({ files: [file], title: box.dataset.file });
      }).catch(function () {});
      closeShare();
      return;
    }
    var to = event.target.closest('[data-share-to]');
    // «Поделиться» issues the bill (2026-11-25, «Счета»): the text alone doesn't fetch the PDF — fetching it issues.
    if (to || event.target.closest('[data-share-copy]')) fetch(box.dataset.pdf, { credentials: 'same-origin' }).catch(function () {});
    if (to) {
      var text = encodeURIComponent(box.dataset.text);
      to.href = to.dataset.shareTo === 'whatsapp'
        ? 'https://wa.me/?text=' + text
        : 'https://t.me/share/url?url=' + text;  // Telegram needs «url»: the message itself goes there
      setTimeout(closeShare, 0);
      return;
    }
    var copy = event.target.closest('[data-share-copy]');
    if (copy && navigator.clipboard) {
      navigator.clipboard.writeText(box.dataset.text).then(function () {
        var label = copy.lastChild;
        var was = label.textContent;
        label.textContent = 'Скопировано';
        copy.classList.add('is-done');
        setTimeout(function () { label.textContent = was; copy.classList.remove('is-done'); closeShare(); }, 1200);
      });
    }
  });
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeShare(); });

  // «Посмотреть»: the bill's PDF in a modal window, not a new tab (2026-11-17). Built once, on the first click.
  var pdfView = null;
  var closePdfView = function () {
    if (!pdfView || pdfView.hidden) return;
    pdfView.hidden = true;
    pdfView.querySelector('iframe').src = 'about:blank';
  };
  document.addEventListener('click', function (event) {
    var link = event.target.closest('[data-pdf-view]');
    if (!link) return;
    event.preventDefault();
    if (!pdfView) {
      pdfView = document.createElement('div');
      pdfView.className = 'pdf-view-back';
      pdfView.innerHTML = '<div class="pdf-view" role="dialog" aria-modal="true"><div class="pdf-view-head"><h3></h3>' +
        '<a data-pdf-download><svg class="icon"><use href="#i-download"/></svg>Скачать</a>' +
        '<button type="button" class="pdf-view-close" aria-label="Закрыть">×</button></div><iframe title="Счёт PDF"></iframe></div>';
      document.body.appendChild(pdfView);
      pdfView.addEventListener('click', function (e) {
        if (e.target === pdfView || e.target.closest('.pdf-view-close')) closePdfView();
      });
    }
    var box = link.closest('[data-share]');
    pdfView.querySelector('h3').textContent = link.dataset.title || 'Счёт';
    var download = pdfView.querySelector('[data-pdf-download]');
    download.href = box ? box.dataset.pdf : link.href.replace(/[&?]inline=1/, '');
    if (box) download.setAttribute('download', box.dataset.file);
    // The viewer's own toolbar and thumbnails off («Скачать» is in our head), the page fits the width.
    pdfView.querySelector('iframe').src = link.href + '#toolbar=0&navpanes=0&view=FitH';
    pdfView.hidden = false;
  });
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closePdfView(); });

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

  // Whose bill (2026-11-25, variant В): the payer's name in the bill's head opens the list of payers with their sums.
  function closeWho() {
    document.querySelectorAll('[data-who-menu]').forEach(function (menu) {
      menu.hidden = true;
      var opener = menu.parentNode.querySelector('[data-who-open]');
      if (opener) opener.setAttribute('aria-expanded', 'false');
    });
  }
  document.addEventListener('click', function (event) {
    var opener = event.target.closest && event.target.closest('[data-who-open]');
    if (opener) {
      var menu = opener.parentNode.querySelector('[data-who-menu]');
      var open = menu.hidden;
      closeWho();
      menu.hidden = !open;
      opener.setAttribute('aria-expanded', open ? 'true' : 'false');
      return;
    }
    if (!(event.target.closest && event.target.closest('[data-who-menu]'))) closeWho();
  });
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closeWho(); });

  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[data-payer]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey) return;
    closeWho();
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
      // «Стало» below «было»: the field turns red (the value stays as typed).
      monthForm.querySelectorAll('.mread .num-input[name]').forEach(function (input) {
        var fresh = doc.querySelector('.mread .num-input[name="' + input.name + '"]');
        if (fresh) input.classList.toggle('is-bad', fresh.classList.contains('is-bad'));
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

    monthForm.addEventListener('input', function (event) {
      status.textContent = '';
      clearTimeout(timer);
      timer = setTimeout(save, 700);
    });
    monthForm.addEventListener('submit', function (event) {
      event.preventDefault();
      clearTimeout(timer);
      save();
    });

    // The service cards change places (2026-11-17, variant Г of the user): «⇅ Порядок» folds the cards into short rows
    // (#morder), dragged by the whole row (mouse or finger): the row rides under the pointer, the others slide aside
    // (FLIP). «Готово» puts the cards in the same order, stores it (receipt_order) and redraws the bill on the right.
    var section = monthForm.closest('.obj-month');
    function orderRows() { return Array.prototype.slice.call(monthForm.querySelectorAll('[data-order-row]')); }
    function idsOf(items) { return items.map(function (item) { return item.dataset.receiptId; }).join(','); }
    var orderBefore = '';
    section.addEventListener('click', function (event) {
      if (event.target.closest('[data-order-on]')) {
        orderBefore = idsOf(orderRows());
        section.classList.add('is-ordering');
        return;
      }
      if (!event.target.closest('[data-order-off]')) return;
      section.classList.remove('is-ordering');
      var ids = orderRows().map(function (row) { return row.dataset.receiptId; });
      if (ids.join(',') === orderBefore) return;
      var body = new FormData();
      body.append('order', ids.join(','));
      // The compact input (2026-11-18) groups the services by what is typed: after a new order the page is drawn again,
      // so the groups and the bill on the right follow it.
      fetch(monthForm.dataset.orderUrl, {
        method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrfToken(monthForm) }
      }).then(function () { location.reload(); });
    });
    var SLIDE = 'transform .22s cubic-bezier(.2, .7, .3, 1)';
    // Move rows in the page, then let each one (but `skip`) glide from where it was to where it is now.
    function slide(mutate, skip) {
      var rows = orderRows().filter(function (row) { return row !== skip; });
      var was = rows.map(function (row) { return row.getBoundingClientRect().top; });
      mutate();
      rows.forEach(function (row, i) {
        var shift = was[i] - row.getBoundingClientRect().top;
        if (!shift) return;
        row.style.transition = 'none';
        row.style.transform = 'translateY(' + shift + 'px)';
        row.getBoundingClientRect();  // apply the start position before the transition
        row.style.transition = SLIDE;
        row.style.transform = '';
      });
    }
    var moving = null;
    monthForm.addEventListener('pointerdown', function (event) {
      var row = event.target.closest('[data-order-row]');
      if (!row || (event.button !== undefined && event.button > 0)) return;
      event.preventDefault();
      moving = { row: row, startY: event.clientY, home: row.getBoundingClientRect().top + window.scrollY, dy: 0 };
      row.style.transition = 'none';
      row.classList.add('is-moving');
      document.body.classList.add('is-dragging');
      row.setPointerCapture(event.pointerId);
    });
    // The row stays exactly under the pointer: its offset = how far the pointer went − how far its slot moved.
    function follow(clientY) {
      var slot = moving.row.getBoundingClientRect().top + window.scrollY - moving.dy;
      moving.dy = clientY - moving.startY - (slot - moving.home);
      moving.row.style.transform = 'translateY(' + moving.dy + 'px)';
    }
    monthForm.addEventListener('pointermove', function (event) {
      if (!moving) return;
      follow(event.clientY);
      // A neighbour gives way once the dragged row's middle passes the neighbour's resting middle;
      // a quick flick passes several rows at once.
      var rest = function (row) {
        var box = row.getBoundingClientRect(), m = new DOMMatrixReadOnly(getComputedStyle(row).transform);
        return box.top - m.m42 + box.height / 2;
      };
      for (var step = 0; step < 50; step++) {
        var r = moving.row.getBoundingClientRect(), middle = r.top + r.height / 2;
        // only inside its own block (2026-11-23): the neighbours are the rows of the same group
        var rows = Array.prototype.slice.call(moving.row.parentNode.querySelectorAll('[data-order-row]')), at = rows.indexOf(moving.row);
        var prev = rows[at - 1], next = rows[at + 1];
        if (prev && middle < rest(prev)) slide(function () { prev.before(moving.row); }, moving.row);
        else if (next && middle > rest(next)) slide(function () { next.after(moving.row); }, moving.row);
        else break;
        follow(event.clientY);
      }
    });
    function dropRow() {
      if (!moving) return;
      var row = moving.row;
      row.style.transition = SLIDE;
      row.style.transform = '';  // glides into its new slot
      document.body.classList.remove('is-dragging');
      setTimeout(function () { row.classList.remove('is-moving'); row.style.transition = ''; }, 220);
      moving = null;
    }
    monthForm.addEventListener('pointerup', dropRow);
    monthForm.addEventListener('pointercancel', dropRow);

    // «н×0,6» in a night field of «По расходу»: a small window «Ночь дешевле дня» — type the weight, «Сохранить»
    // stores it on the service and the bills recount (2026-11-16).
    var nwCard = null;
    function closeNightWeight() { if (nwCard) nwCard.remove(); nwCard = null; }

    monthForm.addEventListener('click', function (event) {
      var btn = event.target.closest('[data-night-weight]');
      if (!btn) return;
      event.preventDefault();
      closeNightWeight();
      nwCard = document.createElement('div');
      nwCard.className = 'nw-card';
      nwCard.setAttribute('role', 'dialog');
      nwCard.innerHTML =
        '<h3>Ночь дешевле дня</h3>' +
        '<p>Сумма делится по расходу. Сколько «весит» ночной кВт·ч по сравнению с дневным: 1 — так же, ' +
        '0,6 — ночью тариф примерно на 40% дешевле. Действует для всех счётчиков день / ночь этой услуги.</p>' +
        '<div class="nw-row"><span>Ночной кВт·ч =</span><input class="num-input" inputmode="decimal" placeholder="1"><span>дневного</span></div>' +
        '<p class="nw-error" hidden></p>' +
        '<div class="nw-acts"><button type="button" class="btn btn-ghost btn-auto" data-nw-cancel>Отмена</button>' +
        '<button type="button" class="btn btn-primary btn-auto" data-nw-save>Сохранить</button></div>';
      document.body.appendChild(nwCard);
      var input = nwCard.querySelector('input');
      input.value = btn.dataset.value || '';
      var r = btn.getBoundingClientRect();
      var h = nwCard.offsetHeight;
      nwCard.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 310)) + 'px';
      nwCard.style.top = (r.bottom + 8 + h > window.innerHeight ? Math.max(8, r.top - h - 8) : r.bottom + 8) + 'px';
      input.focus();
      input.select();

      function store() {
        var body = new FormData();
        body.append('value', input.value);
        fetch(btn.dataset.nightWeight, {
          method: 'POST', body: body, credentials: 'same-origin',
          headers: { 'X-CSRFToken': csrfToken(monthForm) }
        })
          .then(function (response) { return response.json().then(function (data) { return { ok: response.ok, data: data }; }); })
          .then(function (result) {
            if (!result.ok) {
              var error = nwCard.querySelector('.nw-error');
              error.textContent = result.data.error;
              error.hidden = false;
              return;
            }
            // Every night field of this service shows the new weight; then the bills recount.
            monthForm.querySelectorAll('[data-night-weight="' + btn.dataset.nightWeight + '"]').forEach(function (other) {
              other.textContent = result.data.label;
              other.dataset.value = result.data.value;
            });
            closeNightWeight();
            monthForm.dispatchEvent(new Event('input'));
          });
      }
      nwCard.querySelector('[data-nw-save]').addEventListener('click', store);
      nwCard.querySelector('[data-nw-cancel]').addEventListener('click', closeNightWeight);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); store(); }
        if (e.key === 'Escape') closeNightWeight();
      });
    });

    document.addEventListener('mousedown', function (event) {
      if (nwCard && !nwCard.contains(event.target) && !event.target.closest('[data-night-weight]')) closeNightWeight();
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

  initForms(document);
})();
