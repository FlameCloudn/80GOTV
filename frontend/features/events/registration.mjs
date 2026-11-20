import { message as siteMessage } from '../../shared/i18n.js';
import { csrfToken } from '../../shared/site-http.mjs';

// ==================== 赛事报名队伍：页面内更新 ====================
(function() {
  const section = document.getElementById('eventRegistrationSection');
  if (!section) return;
  function submitRegistrationForm(form) {
    var button = form.querySelector('button[type="submit"]');
    var originalText = button ? button.textContent : '';
    if (button) {
      button.disabled = true;
      button.textContent = siteMessage('client.registration.processing');
    }

    // A registration rejection can also be a 403; show the server's actual explanation.
    return fetch(form.action, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRF-Token': csrfToken(),
        'X-80GOTV-UI': '1'
      },
      body: new FormData(form)
    })
    .then(function(response) {
      return response.json().catch(function() {
        throw new Error(siteMessage('client.registration.the_server_returned_an_unrecognized_response'));
      });
    })
    .then(function(result) {
      if (!result.success) {
        window.showToast(result.error || siteMessage('client.registration.operation_failed'), 'error');
        return;
      }

      if (section && typeof result.html === 'string') {
        section.innerHTML = result.html;
      }
      window.showToast(result.message || siteMessage('client.registration.operation_successful'), 'success');
    })
    .catch(function(error) {
      window.showToast(error.message || siteMessage('client.registration.network_error_please_try_again_later'), 'error');
    })
    .finally(function() {
      if (button && document.body.contains(button)) {
        button.disabled = false;
        button.textContent = originalText;
      }
    });
  }

  section.addEventListener('submit', function(event) {
    var form = event.target.closest('.event-reg-ajax-form');
    if (!form) return;
    event.preventDefault();

    var confirmMessage = form.getAttribute('data-confirm');
    if (confirmMessage) {
      window.showConfirm(confirmMessage).then(function(confirmed) {
        if (confirmed) submitRegistrationForm(form);
      });
      return;
    }
    submitRegistrationForm(form);
  });
})();
