// Fields that repeat on every page — one behaviour everywhere (2026-11-25): loaded by templates/base.html, so
// the guest pages (sign-up, login, password) have it as well as the app. app.js reads window.rentflowFields.
(function () {
  'use strict';

  // ---------- Every field is checked when leaving it (2026-11-27), not only on «Создать» / «Готово»:
  // a number, a date, an e-mail, a required field. The same rules as the server. ----------
  var EMAIL_LOCAL = "[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*";
  var EMAIL_HOST = '([A-Za-z0-9\\u00a1-\\uffff]([A-Za-z0-9\\u00a1-\\uffff-]{0,61}[A-Za-z0-9\\u00a1-\\uffff])?\\.)+[A-Za-z\\u00a1-\\uffff]{2,63}';
  var EMAIL_RE = new RegExp('^' + EMAIL_LOCAL + '@' + EMAIL_HOST + '$');

  function emailProblem(value) {
    if (!value || EMAIL_RE.test(value)) return '';
    var at = value.indexOf('@');
    if (at > 0 && /[^\x00-\x7f]/.test(value.slice(0, at))) return 'До «@» — только латинские буквы и цифры.';
    return 'Введите правильный адрес электронной почты.';
  }

  // a number as people type it: «12 450», «12450,5» (LooseDecimalField)
  function numberProblem(value) {
    if (!value) return '';
    var plain = value.replace(/[\s  ]/g, '').replace(',', '.');
    return /^-?(\d+(\.\d*)?|\.\d+)$/.test(plain) ? '' : 'Введите число.';
  }

  function dateProblem(value) {
    if (!value) return '';
    var m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(value);
    if (m) {
      var d = new Date(+m[3], m[2] - 1, +m[1]);
      if (d.getFullYear() === +m[3] && d.getMonth() === m[2] - 1 && d.getDate() === +m[1]) return '';
    }
    return 'Введите дату в виде дд.мм.гггг.';
  }

  function isRequired(input) {
    var field = input.closest('.field');
    return input.required || !!(field && field.querySelector('label .req'));
  }

  // What is wrong with the value ('' — nothing). `withEmpty` — an empty required field counts too.
  function problem(input, withEmpty) {
    var value = input.value.trim();
    if (!value) return withEmpty && isRequired(input) ? 'Заполните поле.' : '';
    if (input.type === 'email') return emailProblem(value);
    if (input.hasAttribute('data-date')) return dateProblem(value);
    if (input.getAttribute('inputmode') === 'decimal') return numberProblem(value);
    return '';
  }

  function checkable(node) {
    return node && node.matches && node.matches('input:not([type=hidden]):not([type=radio]):not([type=checkbox]):not([disabled])')
      && node.closest('.field');
  }

  function dropError(field) {
    field.querySelectorAll('[data-client-error]').forEach(function (node) { node.parentNode.removeChild(node); });
  }

  // Shows the problem under the field; returns it ('' — the value is right).
  function check(input, withEmpty) {
    var field = input.closest('.field');
    if (!field) return '';
    if (input.type === 'email') input.value = input.value.trim();
    // a field with two inputs (day / night): the error is the field's, so both are looked at
    var said = '';
    field.querySelectorAll('input:not([type=hidden]):not([type=radio]):not([type=checkbox]):not([disabled])').forEach(function (one) {
      if (!said) said = problem(one, withEmpty && one === input);
    });
    dropError(field);
    if (!said || field.querySelector('.errorlist')) return said;
    var list = document.createElement('ul');
    list.className = 'errorlist';
    list.dataset.clientError = '';
    var line = document.createElement('li');
    line.textContent = said;
    list.appendChild(line);
    field.appendChild(list);
    return said;
  }

  // leaving a field: its value is checked; an empty required one — only after it was typed in and cleared
  document.addEventListener('focusout', function (event) {
    var input = event.target;
    if (checkable(input)) check(input, input.dataset.touched === '1');
  });

  // typing: the old error under the field (ours or the server's) goes — it is checked again on leaving
  document.addEventListener('input', function (event) {
    var input = event.target;
    if (!checkable(input)) return;
    input.dataset.touched = '1';
    var field = input.closest('.field');
    field.querySelectorAll('.errorlist').forEach(function (node) { node.parentNode.removeChild(node); });
  });

  // Before any form is sent: a wrong value stops it; a folded block with the field opens («Информация об УК ▾»).
  // Fields kept for the small windows (meter, tenant) are checked by their own «Готово».
  document.addEventListener('submit', function (event) {
    var wrong = null;
    event.target.querySelectorAll('input:not([type=hidden]):not([type=radio]):not([type=checkbox]):not([disabled])').forEach(function (input) {
      if (!input.closest('.field') || input.closest('[data-item-store]')) return;
      if (check(input, false) && !wrong) wrong = input;
    });
    if (!wrong) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    var box = wrong.closest('[hidden]');
    if (box) {
      var toggle = box.id && document.querySelector('[aria-controls="' + box.id + '"]');
      if (toggle) toggle.click(); else box.hidden = false;
    }
    wrong.focus();
  }, true);

  window.rentflowFields = { emailProblem: emailProblem, problem: problem, check: check };
})();
