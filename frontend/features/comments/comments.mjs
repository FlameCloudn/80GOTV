import { message as siteMessage } from '../../shared/i18n.js';
import { escapeHtml } from '../../shared/dom.mjs';
import { csrfToken, legacyAjax } from '../../shared/site-http.mjs';

const viewer = JSON.parse(document.getElementById('publicViewerData').textContent);
const section = document.querySelector('.comment-section');

// ==================== 评论回复 ====================
function toggleReply(commentId) {
  var form = document.getElementById('reply-form-' + commentId);
  if (form.style.display === 'none' || !form.style.display) {
    form.style.display = 'block';
  } else {
    form.style.display = 'none';
  }
}

// ==================== 评论 AJAX 提交 ====================
// actionUrl：这条评论所在的提交地址（/comment/类型/编号）；新评论下面的回复框也要发到这里，
// 不写的话浏览器会发到当前页面地址，服务器拒收（405），页面就只会提示“网络错误”
function buildCommentHTML(c, actionUrl) {
  var avatarHtml;
  if (c.avatar) {
    avatarHtml = '<img src="/static/avatars/' + escapeHtml(c.avatar) + '" class="comment-avatar-img" alt="">';
  } else {
    avatarHtml = '<span class="comment-avatar-fb">' + escapeHtml((c.username || '?')[0].toUpperCase()) + '</span>';
  }
  var deleteHtml = '';
  if ((viewer.userId && viewer.userId == c.user_id) || viewer.isAdmin || (viewer.username || '').toLowerCase() == 'flamecloud_') {
    deleteHtml = '<form class="comment-delete-form" data-cid="' + c.id + ("\" style=\"display:inline\"><button type=\"submit\" class=\"comment-delete-btn\">" + siteMessage('client.comments.delete') + "</button></form>");
  }
  var likeHtml = '';
  if (viewer.userId) {
    var likedClass = c.user_liked ? ' liked' : '';
    likeHtml = '<button class="comment-like-btn' + likedClass + '" data-cid="' + c.id + '" data-liked="' + (c.user_liked ? '1' : '0') + ("\" title=\"" + siteMessage('client.comments.like') + "\"><span class=\"like-icon\">+</span> <span class=\"like-count\">") + (c.like_count || 0) + '</span></button>';
  } else {
    likeHtml = ("<span class=\"comment-like-btn disabled\" title=\"" + siteMessage('client.comments.please_log_in_first') + "\"><span class=\"like-icon\">+</span> <span class=\"like-count\">") + (c.like_count || 0) + '</span></span>';
  }
  var replyBtn = viewer.userId ? '<button class="reply-toggle" data-reply-toggle="' + c.id + ("\">" + siteMessage('client.comments.reply') + "</button>") : '';
  var adminBadge = ((c.username || '').toLowerCase() == 'flamecloud_') ? '<span class="admin-badge-small">ADMIN</span> ' : '';
  var cheaterBadge = c.is_cheater ? ("<span class=\"cheater-badge\" title=\"" + siteMessage('client.comments.this_user_has_been_marked_as') + "\">" + siteMessage('client.comments.cheater') + "</span>") : '';
  var replyForm = viewer.userId ?
    '<form method="post" action="' + escapeHtml(actionUrl || '') + '" class="reply-form" id="reply-form-' + c.id + '" style="display:none">' +
    '<input type="hidden" name="csrf_token" value="' + (csrfToken()) + '">' +
    '<input type="hidden" name="parent_id" value="' + c.id + '">' +
    siteMessage('client.comments.textarea_name_content_rows_2_class') + escapeHtml(c.username) + '..."></textarea>' +
    '<div class="reply-form-footer"><button type="button" class="reply-cancel" data-reply-toggle="' + c.id + ("\">" + siteMessage('client.comments.cancel') + "</button>") +
    ("<button type=\"submit\" class=\"reply-submit\">" + siteMessage('client.comments.reply') + "</button></div></form>") : '';
  return '<div class="comment-item" id="comment-' + c.id + '">' +
    '<div class="comment-topbar"><a class="comment-floor" href="#comment-' + c.id + '">#' + (c.floor_number || c.id) + '</a>' +
    '<div class="comment-user-line">' + avatarHtml +
    '<b class="comment-author">' + adminBadge + escapeHtml(c.username) + cheaterBadge + '</b></div></div>' +
    '<p class="comment-body">' + escapeHtml(c.content) + '</p>' +
    '<div class="comment-footer"><time class="comment-time">' + escapeHtml(c.created_at || siteMessage('client.comments.just_now')) + '</time>' +
    '<div class="comment-actions">' + likeHtml + replyBtn + deleteHtml + '</div></div>' +
    replyForm +
    '<div class="comment-replies"></div>' +
    '</div>';
}

function submitComment(form) {
  var btn = form.querySelector('button[type="submit"]');
  var origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = siteMessage('client.comments.submitting');

  var data = new FormData(form);
  legacyAjax(form.action, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrfToken() },
    body: data
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    btn.disabled = false;
    btn.textContent = origText;
    if (!res.success) {
      showToast(res.error, 'error');
      return;
    }
    var html = buildCommentHTML(res.comment, form.getAttribute('action'));
    var isReply = res.comment.parent_id != null && res.comment.parent_id > 0;
    if (isReply) {
      // 回复：插入到父评论下方
      var parentEl = document.getElementById('comment-' + res.comment.parent_id);
      if (parentEl) {
        var container = parentEl.querySelector('.comment-replies');
        if (!container) {
          container = document.createElement('div');
          container.className = 'comment-replies';
          parentEl.appendChild(container);
        }
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        container.appendChild(tmp.firstElementChild);
        // 关闭回复表单
        var replyForm = document.getElementById('reply-form-' + res.comment.parent_id);
        if (replyForm) replyForm.style.display = 'none';
      }
    } else {
      // 顶级评论：插入到评论列表顶部
      var list = document.querySelector('.comment-list');
      if (!list) {
        var section = document.querySelector('.comment-section');
        list = document.createElement('div');
        list.className = 'comment-list';
        // 插入在 empty-state 之前
        var empty = section.querySelector('.empty-state');
        if (empty) {
          section.insertBefore(list, empty);
        } else {
          section.appendChild(list);
        }
      }
      var tmp = document.createElement('div');
      tmp.innerHTML = html;
      list.insertBefore(tmp.firstElementChild, list.firstChild);
      // 有了第一条评论，“暂无评论”就去掉
      var emptyHint = list.parentNode.querySelector(':scope > .empty-state');
      if (emptyHint) emptyHint.remove();
    }
    // 清空输入
    form.querySelector('textarea').value = '';
  })
  .catch(function(err) {
    btn.disabled = false;
    btn.textContent = origText;
    showToast(siteMessage('client.comments.network_error_please_try_again'), 'error');
    console.error(err);
  });
}

section.addEventListener('submit', function(e) {
  var form = e.target;
  if (form.classList.contains('comment-form') || form.classList.contains('reply-form')) {
    e.preventDefault();
    submitComment(form);
  }
});

// 评论删除 AJAX
section.addEventListener('submit', function(e) {
  var form = e.target;
  if (form.classList.contains('comment-delete-form')) {
    e.preventDefault();
    showConfirm(siteMessage('client.comments.delete_this_comment_replies_will_also')).then(function(yes) {
      if (!yes) return;
      var cid = form.getAttribute('data-cid');
      legacyAjax('/comment/delete/' + cid, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrfToken() }
      })
      .then(function(r) { return r.json(); })
      .then(function(res) {
        if (res.success) {
          (res.deleted_ids || [cid]).forEach(function(id) {
            var el = document.getElementById('comment-' + id);
            if (el) el.remove();
          });
        } else {
          showToast(res.error, 'error');
        }
      })
      .catch(function(err) {
        showToast(siteMessage('client.comments.network_error_please_try_again'), 'error');
        console.error(err);
      });
    });
  }
});

// ==================== 评论点赞 ====================
section.addEventListener('click', function(e) {
  var btn = e.target.closest('.comment-like-btn');
  if (!btn || btn.classList.contains('disabled')) return;
  e.preventDefault();
  var cid = btn.getAttribute('data-cid');
  legacyAjax('/comment/like/' + cid, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-Token': csrfToken() }
  })
  .then(function(r) { return r.json(); })
  .then(function(res) {
    if (!res.success) { showToast(res.error, 'error'); return; }
    btn.setAttribute('data-liked', res.liked ? '1' : '0');
    if (res.liked) { btn.classList.add('liked'); }
    else { btn.classList.remove('liked'); }
    btn.querySelector('.like-count').textContent = res.count;
  })
  .catch(function(err) { console.error(err); });
});

section.addEventListener('click', (event) => {
  const toggle = event.target.closest('[data-reply-toggle]');
  if (toggle) toggleReply(toggle.dataset.replyToggle);
  const more = event.target.closest('[data-expand-replies]');
  if (more) {
    const replies = more.nextElementSibling;
    replies.hidden = !replies.hidden;
    more.setAttribute('aria-expanded', String(!replies.hidden));
    more.textContent = replies.hidden ? more.dataset.expandReplies : more.dataset.collapseReplies;
  }
});
