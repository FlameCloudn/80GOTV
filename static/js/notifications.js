(function () {
  'use strict';

  var bell = document.getElementById('notifBell');
  var popup = document.getElementById('notifPopup');
  var list = document.getElementById('notifPopupList');
  var count = document.getElementById('notifPopupCount');
  var closeButton = document.getElementById('notifPopupClose');
  var markAllButton = document.getElementById('notifMarkAll');

  if (!bell || !popup || !list || !window._curUserId) return;

  function setBadge(unread) {
    var badge = document.getElementById('notifBadge');
    if (unread > 0) {
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'notif-badge';
        badge.id = 'notifBadge';
        bell.appendChild(badge);
      }
      badge.textContent = unread > 99 ? '99+' : String(unread);
      count.textContent = unread + ' 条未读';
    } else {
      if (badge) badge.remove();
      count.textContent = '没有未读通知';
    }
  }

  function setEmpty(message) {
    list.replaceChildren();
    var empty = document.createElement('div');
    empty.className = 'notif-popup-empty';
    empty.textContent = message;
    list.appendChild(empty);
  }

  function notificationIcon(type) {
    var wrapper = document.createElement('span');
    wrapper.className = 'notif-popup-item-icon';
    wrapper.setAttribute('aria-hidden', 'true');
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    if (type === 'reply') {
      path.setAttribute('d', 'M21 12a8 8 0 0 1-8 8H5l-3 2 1-5a8 8 0 1 1 18-5Z');
    } else if (type === 'system') {
      path.setAttribute('d', 'M3 11v4h4l10 4V7L7 11H3Zm4 4 2 6h3l-2-5');
    } else {
      path.setAttribute('d', 'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4');
    }
    svg.appendChild(path);
    wrapper.appendChild(svg);
    return wrapper;
  }

  function postRead(id) {
    return fetch('/notifications/read/' + id, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRF-Token': window._csrfToken || ''
      }
    }).then(function (response) {
      if (!response.ok) throw new Error('通知操作失败');
      return response.json();
    });
  }

  function updateVisibleUnread(delta) {
    var badge = document.getElementById('notifBadge');
    var current = badge ? parseInt(badge.textContent, 10) || 0 : 0;
    setBadge(Math.max(0, current + delta));
  }

  function buildItem(notification) {
    var item = document.createElement('article');
    item.className = 'notif-popup-item' + (notification.read ? '' : ' unread');
    item.dataset.id = notification.id;
    item.appendChild(notificationIcon(notification.type));

    var content = document.createElement('div');
    content.className = 'notif-popup-item-content';
    var link = document.createElement('a');
    link.className = 'notif-popup-item-link';
    link.href = notification.url || '/notifications';
    link.textContent = notification.message || '通知';
    var time = document.createElement('time');
    time.textContent = notification.created_at || '';
    content.appendChild(link);
    content.appendChild(time);

    var actions = document.createElement('div');
    actions.className = 'notif-popup-item-actions';
    if (!notification.read) {
      var readButton = document.createElement('button');
      readButton.type = 'button';
      readButton.textContent = '标为已读';
      readButton.addEventListener('click', function () {
        readButton.disabled = true;
        postRead(notification.id).then(function () {
          item.classList.remove('unread');
          readButton.remove();
          updateVisibleUnread(-1);
        }).catch(function () { readButton.disabled = false; });
      });
      actions.appendChild(readButton);
    }

    var ignoreButton = document.createElement('button');
    ignoreButton.type = 'button';
    ignoreButton.textContent = '忽略';
    ignoreButton.addEventListener('click', function () {
      ignoreButton.disabled = true;
      postRead(notification.id).then(function () {
        if (item.classList.contains('unread')) updateVisibleUnread(-1);
        item.remove();
        if (!list.querySelector('.notif-popup-item')) setEmpty('暂无通知');
      }).catch(function () { ignoreButton.disabled = false; });
    });
    actions.appendChild(ignoreButton);

    link.addEventListener('click', function () {
      if (!notification.read) {
        fetch('/notifications/read/' + notification.id, {
          method: 'POST',
          credentials: 'same-origin',
          keepalive: true,
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRF-Token': window._csrfToken || ''
          }
        });
      }
    });

    item.appendChild(content);
    item.appendChild(actions);
    return item;
  }

  function loadNotifications() {
    setEmpty('加载中...');
    return fetch('/api/front/notifications', {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (response) {
      if (!response.ok) throw new Error('通知加载失败');
      return response.json();
    }).then(function (data) {
      if (!data.authenticated) {
        closePopup();
        return;
      }
      setBadge(Number(data.unread) || 0);
      list.replaceChildren();
      if (!data.notifications || !data.notifications.length) {
        setEmpty('暂无通知');
        return;
      }
      data.notifications.forEach(function (notification) {
        list.appendChild(buildItem(notification));
      });
    }).catch(function () {
      setEmpty('通知加载失败，请稍后再试');
    });
  }

  function positionPopup() {
    var rect = bell.getBoundingClientRect();
    popup.style.top = Math.round(rect.bottom + 6) + 'px';
    popup.style.right = Math.round(Math.max(8, window.innerWidth - rect.right)) + 'px';
  }

  function closePopup() {
    popup.hidden = true;
    bell.setAttribute('aria-expanded', 'false');
  }

  function openPopup() {
    positionPopup();
    popup.hidden = false;
    bell.setAttribute('aria-expanded', 'true');
    loadNotifications();
  }

  function togglePopup() {
    if (popup.hidden) openPopup();
    else closePopup();
  }

  bell.addEventListener('click', function (event) {
    event.stopPropagation();
    togglePopup();
  });
  closeButton.addEventListener('click', closePopup);
  markAllButton.addEventListener('click', function () {
    markAllButton.disabled = true;
    fetch('/notifications/read-all', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRF-Token': window._csrfToken || ''
      }
    }).then(function (response) {
      if (!response.ok) throw new Error('通知操作失败');
      return response.json();
    }).then(function () {
      list.querySelectorAll('.notif-popup-item.unread').forEach(function (item) {
        item.classList.remove('unread');
        var firstButton = item.querySelector('.notif-popup-item-actions button');
        if (firstButton && firstButton.textContent === '标为已读') firstButton.remove();
      });
      setBadge(0);
    }).finally(function () { markAllButton.disabled = false; });
  });
  document.addEventListener('click', function (event) {
    if (!popup.hidden && !popup.contains(event.target)) closePopup();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !popup.hidden) {
      closePopup();
      bell.focus();
    }
  });
  window.addEventListener('resize', function () {
    if (!popup.hidden) positionPopup();
  });

  window.toggleNotifPopup = togglePopup;
  window.loadNotifs = loadNotifications;
  window.markRead = function (id, element) {
    return postRead(id).then(function () {
      if (element) element.classList.remove('unread');
      if (typeof window.updateBadgeCount === 'function') window.updateBadgeCount();
    });
  };
  window.markAllRead = function () { markAllButton.click(); };
})();
