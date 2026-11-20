(function () {
  'use strict';

  const loaded = new WeakSet();
  const messages = Object.create(null);

  // Classic scripts and ES modules read the same explicit, page-scoped messages.
  window.siteMessage = function (key, values = {}) {
    if (!Object.hasOwn(messages, key)) {
      for (const node of document.querySelectorAll('script[data-site-messages]')) {
        if (loaded.has(node)) continue;
        Object.assign(messages, JSON.parse(node.textContent));
        loaded.add(node);
      }
    }
    if (!Object.hasOwn(messages, key)) throw new Error(`Missing message: ${key}`);
    return messages[key].replace(/\{\{|\}\}|\{([a-z][a-z0-9_]*)\}/g, function (match, name) {
      if (!name) return match[0];
      if (!Object.hasOwn(values, name)) throw new Error(`Missing message parameter: ${key}.${name}`);
      return String(values[name]);
    });
  };

  function migrateLegacyPreference(settings) {
    if (settings.saved) return;
    let legacy;
    try {
      legacy = localStorage.getItem('siteLang');
    } catch {
      return;
    }
    if (!['en', 'zh', 'auto'].includes(legacy)) return;

    const body = new URLSearchParams({ language: legacy, legacy: '1', csrf_token: settings.csrfToken });
    fetch(settings.url, { method: 'POST', body }).then(function (response) {
      if (response.status !== 204) return;
      try {
        localStorage.removeItem('siteLang');
      } catch {
        // The saved server preference still wins if browser storage is read-only.
      }
      if (legacy !== 'auto' && legacy !== settings.language) location.reload();
    }).catch(function () {
      // Leave the old value available for migration on the next navigation.
    });
  }

  function init() {
    const config = document.getElementById('siteLocale');
    if (!config) return;
    const settings = JSON.parse(config.textContent);
    const form = document.querySelector('form[data-site-language]');
    if (form) {
      form.querySelector('[data-language-submit]').hidden = true;
      form.elements.language.addEventListener('change', function () { form.requestSubmit(); });
      form.addEventListener('submit', function () {
        form.elements.next.value = location.pathname + location.search + location.hash;
      });
    }
    migrateLegacyPreference(settings);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
