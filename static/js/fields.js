// Fields that repeat on every page — one behaviour everywhere (2026-11-25): loaded by templates/base.html, so
// the guest pages (sign-up, login, password) have it as well as the app. app.js reads window.rentflowFields.
(function () {
  'use strict';

  // ---------- E-mail: checked when leaving the field and before a form is sent; the same rule as the server
  // (config/validators.py) ----------
  var EMAIL_LOCAL = "[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*";
  var EMAIL_HOST = '([A-Za-z0-9\\u00a1-\\uffff]([A-Za-z0-9\\u00a1-\\uffff-]{0,61}[A-Za-z0-9\\u00a1-\\uffff])?\\.)+[A-Za-z\\u00a1-\\uffff]{2,63}';
  var EMAIL_RE = new RegExp('^' + EMAIL_LOCAL + '@' + EMAIL_HOST + '$');

  function emailProblem(value) {
    if (!value || EMAIL_RE.test(value)) return '';
    var at = value.indexOf('@');
    if (at > 0 && /[^\x00-\x7f]/.test(value.slice(0, at))) return 'До «@» — только латинские буквы и цифры.';
    return 'Введите правильный адрес электронной почты.';
  }

  function dropEmailError(field) {
    field.querySelectorAll('[data-email-error]').forEach(function (node) { node.parentNode.removeChild(node); });
  }

  // Shows the problem under the field; returns it ('' — the address is right).
  function checkEmail(input) {
    var field = input.closest('.field');
    if (!field) return '';
    input.value = input.value.trim();
    dropEmailError(field);
    var problem = emailProblem(input.value);
    if (!problem || field.querySelector('.errorlist')) return problem;
    var list = document.createElement('ul');
    list.className = 'errorlist';
    list.dataset.emailError = '';
    list.dataset.clientError = '';
    var line = document.createElement('li');
    line.textContent = problem;
    list.appendChild(line);
    field.appendChild(list);
    return problem;
  }

  function isEmail(node) {
    return node && node.matches && node.matches('input[type=email]:not([disabled])');
  }

  document.addEventListener('focusout', function (event) {
    if (isEmail(event.target)) checkEmail(event.target);
  });

  document.addEventListener('input', function (event) {
    if (isEmail(event.target) && event.target.closest('.field')) dropEmailError(event.target.closest('.field'));
  });

  // Before any form is sent: a wrong address stops it; a folded block with the field opens («Информация об УК ▾»).
  document.addEventListener('submit', function (event) {
    var wrong = null;
    event.target.querySelectorAll('input[type=email]:not([disabled])').forEach(function (input) {
      if (checkEmail(input) && !wrong) wrong = input;
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

  window.rentflowFields = { emailProblem: emailProblem, checkEmail: checkEmail };
})();
