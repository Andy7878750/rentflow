/* App-wide behaviour: modal windows and the object form. */
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

  // ---------- Modal ----------

  var dialog = document.querySelector('[data-modal-dialog]');

  function showInModal(html) {
    dialog.innerHTML = html;
    initForms(dialog);
    if (!dialog.open) dialog.showModal();
    var firstError = dialog.querySelector('.errorlist');
    var target = firstError ? firstError.closest('.field, .form-section') : null;
    if (target) {
      target.scrollIntoView({ block: 'center' });
    } else {
      var first = dialog.querySelector('input:not([type=hidden]):not([type=radio]), select');
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
      link.closest('[data-dropdown]') && link.closest('[data-dropdown]').removeAttribute('open');
      openModal(link.href);
    });

    dialog.addEventListener('click', function (event) {
      // Click on the dark backdrop (the dialog element itself) or a close control.
      if (event.target === dialog || event.target.closest('[data-modal-close]')) {
        event.preventDefault();
        dialog.close();
      }
    });

    dialog.addEventListener('close', function () { dialog.innerHTML = ''; });

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

  // ---------- Field helpers (delegated, so they work inside the modal too) ----------

  document.addEventListener('click', function (event) {
    var toggle = event.target.closest('[data-reveal]');
    if (!toggle) return;
    var input = toggle.parentNode.querySelector('input');
    var showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
    toggle.classList.toggle('is-visible', !showing);
    toggle.setAttribute('aria-label', showing ? 'Показать подсказку' : 'Скрыть подсказку');
  });

  // +7 (912) 345-67-89 for Russian numbers; anything starting with another +code is left as typed.
  function formatPhone(value) {
    var digits = value.replace(/\D/g, '');
    if (!digits) return '';
    if (value.trim().charAt(0) === '+' && digits.charAt(0) !== '7') return '+' + digits;
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
    if (event.inputType && event.inputType.indexOf('delete') === 0) return; // let people erase freely
    input.value = formatPhone(input.value);
  });

  // ---------- Object form ----------

  function initPropertyForm(form) {
    var list = form.querySelector('[data-tenant-list]');
    var template = form.querySelector('[data-tenant-template]');
    var totalForms = form.querySelector('input[name$="-TOTAL_FORMS"]');
    var areaInput = form.querySelector('[data-total-area]');
    var occupied = form.querySelector('[data-occupied]');

    function unit() {
      var checked = form.querySelector('input[name=share_unit]:checked');
      return checked ? checked.value : 'percent';
    }

    function visibleRows() {
      return Array.prototype.filter.call(list.querySelectorAll('[data-tenant-row]'), function (row) {
        return !row.hidden;
      });
    }

    function update() {
      var isArea = unit() === 'area';
      var totalArea = parseNumber(areaInput && areaInput.value);
      var sum = 0;

      visibleRows().forEach(function (row) {
        var value = parseNumber(row.querySelector('[data-share]').value);
        var hint = row.querySelector('[data-share-hint]');
        if (value !== null) sum += value;
        var text = '';
        if (value !== null && totalArea) {
          text = isArea ? '= ' + formatNumber(value / totalArea * 100) + '%'
                        : '= ' + formatNumber(value * totalArea / 100) + ' м²';
        }
        hint.textContent = text;
      });

      form.querySelectorAll('[data-share-label]').forEach(function (label) {
        label.firstChild.nodeValue = isArea ? 'Площадь, м² ' : 'Доля, % ';
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

    // Switching % ↔ m² converts what was typed, when the object's area is known.
    function convertShares(toArea) {
      var totalArea = parseNumber(areaInput && areaInput.value);
      if (!totalArea) return;
      visibleRows().forEach(function (row) {
        var input = row.querySelector('[data-share]');
        var value = parseNumber(input.value);
        if (value === null) return;
        input.value = formatNumber(toArea ? value * totalArea / 100 : value / totalArea * 100);
      });
    }

    function removeRow(row) {
      var del = row.querySelector('input[name$="-DELETE"]');
      if (del) del.checked = true;
      row.hidden = true;
      if (!visibleRows().length) addRow();
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
      if (event.target.name === 'share_unit') {
        convertShares(event.target.value === 'area');
        update();
      }
    });

    form.addEventListener('input', function (event) {
      if (event.target.matches('[data-share], [data-total-area]')) update();
    });

    form.addEventListener('click', function (event) {
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

  function initForms(root) {
    root.querySelectorAll('[data-property-form]').forEach(initPropertyForm);
  }

  initForms(document);
})();
