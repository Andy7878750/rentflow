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
      closeSelects(null);
    });

    dialog.addEventListener('close', function () {
      hideTip();
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

  document.addEventListener('mouseover', function (event) {
    var help = event.target.closest && event.target.closest('.help[data-tip]');
    if (help) showTip(help);
    else if (tipOwner && document.activeElement !== tipOwner) hideTip();
  });
  document.addEventListener('focusin', function (event) {
    var help = event.target.closest && event.target.closest('.help[data-tip]');
    if (help) showTip(help);
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
    var showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
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
    var totalForms = form.querySelector('input[name$="-TOTAL_FORMS"]');
    var areaInput = form.querySelector('[data-total-area]');
    var unitInput = form.querySelector('input[name=share_unit]');
    var occupied = form.querySelector('[data-occupied]');

    form.querySelectorAll('[data-kind-select]').forEach(function (select) { initKindSelect(select, form); });

    function visibleRows() {
      return Array.prototype.filter.call(list.querySelectorAll('[data-tenant-row]'), function (row) {
        return !row.hidden;
      });
    }

    function update() {
      var isArea = unitInput.value === 'area';
      var totalArea = parseNumber(areaInput && areaInput.value);
      var sum = 0;

      list.querySelectorAll('[data-unit-select]').forEach(function (picker) {
        picker.value = unitInput.value;
      });

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
      if (event.target.matches('[data-unit-select]')) setUnit(event.target.value);
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
