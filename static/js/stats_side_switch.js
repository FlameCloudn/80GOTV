(function () {
  var ajaxLinkSelector = [
    '.hltv-tabs a[href^="/stats"]',
    '.stats-side-tabs a[href*="side="]',
    '.player-stat-controls a.seg[href*="side="]'
  ].join(',');
  var ajaxFormSelector = '.stats-filter-strip, .player-filter-strip';

  function isAjaxLink(link) {
    if (!link || !link.href) return false;
    try {
      var url = new URL(link.href, window.location.href);
      return url.origin === window.location.origin;
    } catch (e) {
      return false;
    }
  }

  function formUrl(form) {
    var method = String(form.method || 'get').toLowerCase();
    if (method !== 'get') return null;
    var action = form.getAttribute('action') || window.location.pathname;
    var url = new URL(action, window.location.href);
    var data = new FormData(form);
    url.search = '';
    data.forEach(function (value, key) {
      url.searchParams.append(key, value);
    });
    return url.href;
  }

  function copyAttributes(from, to) {
    Array.prototype.forEach.call(from.attributes, function (attr) {
      to.setAttribute(attr.name, attr.value);
    });
  }

  async function runScripts(container) {
    var scripts = Array.prototype.slice.call(container.querySelectorAll('script'));
    for (var i = 0; i < scripts.length; i += 1) {
      var oldScript = scripts[i];
      var newScript = document.createElement('script');
      copyAttributes(oldScript, newScript);
      if (oldScript.src) {
        await new Promise(function (resolve) {
          newScript.onload = resolve;
          newScript.onerror = resolve;
          oldScript.replaceWith(newScript);
        });
      } else {
        newScript.textContent = oldScript.textContent;
        oldScript.replaceWith(newScript);
      }
    }
  }

  async function replacePageParts(html, url) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var nextMain = doc.querySelector('.main-col');
    var nextSide = doc.querySelector('.side-col');
    var curMain = document.querySelector('.main-col');
    var curSide = document.querySelector('.side-col');
    var nextLayout = doc.querySelector('.layout');
    var curLayout = document.querySelector('.layout');

    if (!nextMain || !curMain) {
      window.location.href = url;
      return;
    }

    curMain.innerHTML = nextMain.innerHTML;
    if (nextSide && curSide) curSide.innerHTML = nextSide.innerHTML;
    if (nextLayout && curLayout) curLayout.className = nextLayout.className;
    if (doc.title) document.title = doc.title;

    await runScripts(curMain);
    if (curSide) await runScripts(curSide);
    if (window.applySiteI18n) window.applySiteI18n();
    document.dispatchEvent(new CustomEvent('stats-side-switched', { detail: { url: url } }));
  }

  async function loadPartial(url, loadingElement) {
    var container = loadingElement || document.querySelector('.main-col');
    if (container) container.classList.add('is-loading');

    try {
      var response = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      var html = await response.text();
      await replacePageParts(html, url);
    } catch (err) {
      window.location.href = url;
    } finally {
      if (container) container.classList.remove('is-loading');
    }
  }

  document.addEventListener('click', function (event) {
    var link = event.target.closest(ajaxLinkSelector);
    if (!isAjaxLink(link)) return;
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    event.preventDefault();
    var container = link.closest('.hltv-tabs, .stats-side-tabs, .player-stat-controls') || link.parentElement;
    loadPartial(link.href, container);
  });

  document.addEventListener('change', function (event) {
    var form = event.target.closest(ajaxFormSelector);
    if (!form || !event.target.matches('select,input')) return;
    var url = formUrl(form);
    if (!url) return;

    event.preventDefault();
    event.stopPropagation();
    if (event.stopImmediatePropagation) event.stopImmediatePropagation();
    loadPartial(url, form);
  }, true);

  document.addEventListener('submit', function (event) {
    var form = event.target.closest(ajaxFormSelector);
    if (!form) return;
    var url = formUrl(form);
    if (!url) return;

    event.preventDefault();
    loadPartial(url, form);
  });

})();
