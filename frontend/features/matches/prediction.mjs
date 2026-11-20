import { message as siteMessage } from '../../shared/i18n.js';
import { csrfToken, legacyAjax } from '../../shared/site-http.mjs';

const section = document.querySelector('[data-vote-url]');

function submitVote(btn) {
  var votedFor = btn.getAttribute('data-vote');
  btn.disabled = true;
  var label = btn.querySelector('[data-vote-label]');
  btn.textContent = siteMessage('client.prediction.submitting');
  var formData = new FormData();
  formData.append('voted_for', votedFor);
  formData.append('csrf_token', csrfToken());
  var s1 = section.querySelector('#score1');
  var s2 = section.querySelector('#score2');
  if (s1 && s1.value) formData.append('score1', s1.value);
  if (s2 && s2.value) formData.append('score2', s2.value);
  legacyAjax(section.dataset.voteUrl, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrfToken() },
    body: formData
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    if (res.ok) {
      location.reload();
    } else {
      showToast(res.msg, 'error');
      btn.disabled = false;
      btn.replaceChildren(label);
    }
  })
  .catch(function() {
    showToast(siteMessage('client.prediction.network_error_please_try_again'), 'error');
    btn.disabled = false;
    btn.replaceChildren(label);
  });
}

section?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-vote]');
  if (button) submitVote(button);
});
