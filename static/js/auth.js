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

  document.querySelectorAll('[data-password-strength]').forEach(function (input) {
    var field = input.closest('.field');
    var segments = field ? field.querySelectorAll('.strength-meter-segment') : [];
    input.addEventListener('input', function () {
      var score = scorePassword(input.value);
      segments.forEach(function (seg, i) {
        seg.classList.toggle('is-active', i < score);
      });
    });
  });

  function scorePassword(value) {
    if (!value) return 0;
    var score = 1;
    if (value.length >= 8) score++;
    if (/\d/.test(value) && /[a-zA-Zа-яА-Я]/.test(value)) score++;
    if (value.length >= 12 && /[^A-Za-zА-Яа-я0-9]/.test(value)) score++;
    return Math.min(score, 4);
  }
});
