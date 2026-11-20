(function () {
  var textarea = document.getElementById('forumReplyContent');
  if (!textarea) return;
  document.addEventListener('click', function (event) {
    var button = event.target.closest('.forum-quote-btn');
    if (!button) return;
    var content = (button.dataset.content || '').replace(/\s+/g, ' ').trim();
    if (content.length > 100) content = content.slice(0, 100) + '...';
    var quote = window.siteMessage('client.inline_thread.quote') + button.dataset.author + ' #' + button.dataset.floor + '：' + content + '\n\n';
    textarea.value = quote + textarea.value;
    textarea.focus();
    textarea.scrollIntoView({behavior: 'smooth', block: 'center'});
  });
})();

document.querySelector('[data-confirm-delete-thread]')?.addEventListener('submit', (event) => {
  if (!confirm(event.currentTarget.dataset.confirmDeleteThread)) event.preventDefault();
});
