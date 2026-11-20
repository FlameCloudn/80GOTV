import { legacyAjax } from '../../shared/site-http.mjs';

// ==================== 通知轮询 ====================
export function updateBadgeCount() {
  if (!document.querySelector('.notif-bell')) return;
  legacyAjax('/notifications/unread-count', {
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    var badge = document.getElementById('notifBadge');
    if (res.count > 0) {
      if (badge) {
        badge.textContent = res.count;
      } else {
        var bell = document.querySelector('.notif-bell');
        if (bell) {
          var span = document.createElement('span');
          span.className = 'notif-badge';
          span.id = 'notifBadge';
          span.textContent = res.count;
          bell.appendChild(span);
        }
      }
    } else {
      if (badge) badge.remove();
    }
  })
  .catch(function(){});
}
