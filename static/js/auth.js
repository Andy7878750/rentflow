document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-toggle-password]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = document.getElementById(btn.dataset.togglePassword);
      if (!input) return;
      var showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.classList.toggle('is-visible', !showing);
      btn.setAttribute('aria-label', showing ? 'Показать пароль' : 'Скрыть пароль');
    });
  });

  var STRENGTH_LEVELS = {
    1: { text: 'Слабый пароль', color: '#c0392b' },
    2: { text: 'Средний пароль', color: '#e0a458' },
    3: { text: 'Хороший пароль', color: '#148f77' },
  };

  document.querySelectorAll('[data-password-strength]').forEach(function (input) {
    var field = input.closest('.field');
    var segments = field ? field.querySelectorAll('.strength-meter-segment') : [];
    var label = field ? field.querySelector('[data-password-strength-label]') : null;
    var hint = field ? field.querySelector('[data-field-hint]') : null;

    input.addEventListener('input', function () {
      var score = scorePassword(input.value);
      var level = STRENGTH_LEVELS[score];

      segments.forEach(function (seg, i) {
        var active = i < score;
        seg.classList.toggle('is-active', active);
        seg.style.background = active ? level.color : '';
      });

      if (label) {
        label.textContent = level ? level.text : '';
        label.style.color = level ? level.color : '';
      }

      if (hint) {
        hint.style.display = input.value ? 'none' : '';
      }
    });
  });

  function scorePassword(value) {
    if (!value) return 0;
    var hasLower = /[a-zа-я]/.test(value);
    var hasUpper = /[A-ZА-Я]/.test(value);
    var hasDigit = /\d/.test(value);
    var hasSpecial = /[^A-Za-zА-Яа-я0-9]/.test(value);
    var variety = [hasLower, hasUpper, hasDigit, hasSpecial].filter(Boolean).length;

    if (value.length < 8) return 1;
    if (value.length >= 12 && variety >= 3) return 3;
    if (variety >= 2) return 2;
    return 1;
  }
});
