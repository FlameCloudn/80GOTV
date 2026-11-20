import { csrfToken, legacyAjax } from '../../shared/site-http.mjs';
import { updateBadgeCount } from './badge.mjs';

function markRead(notifId, el) {
  legacyAjax('/notifications/read/' + notifId, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrfToken() }
  }).then(function(r){ return r.json(); }).then(function(res){
    if (res.success) {
      el.classList.remove('unread');
      var btn = el.querySelector('.notif-mark-read');
      if (btn) btn.remove();
      updateBadgeCount();
    }
  });
}

function markAllRead() {
  legacyAjax('/notifications/read-all', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrfToken() }
  }).then(function(r){ return r.json(); }).then(function(res){
    if (res.success) {
      document.querySelectorAll('.notif-item.unread').forEach(function(el){
        el.classList.remove('unread');
        var btn = el.querySelector('.notif-mark-read');
        if (btn) btn.remove();
      });
      updateBadgeCount();
    }
  });
}
document.querySelector('[data-mark-all-read]')?.addEventListener('click', markAllRead);
document.querySelector('.notif-list')?.addEventListener('click', event => {
  const button = event.target.closest('[data-mark-read]');
  if (!button) return;
  event.preventDefault();
  const item = button.closest('.notif-item');
  markRead(item.dataset.id, item);
});
