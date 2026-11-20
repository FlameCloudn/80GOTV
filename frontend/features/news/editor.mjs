import { csrfToken } from '../../shared/site-http.mjs';

(function () {
  // 正文用 Quill 富文本编辑器；编辑器没加载出来时退回普通文本框，照样能保存
  var form = document.getElementById('newsForm');
  var editorElement = document.getElementById('editor');
  var contentTextarea = document.getElementById('contentTextarea');
  // 编辑器的问题（加载失败、图片上传失败）用右上角提示，不在正文下面放整块红条
  function showEditorMessage(message, type) {
    window.showToast(message, type || 'error', { key: 'news-editor' });
  }
  if (!window.Quill) {
    showEditorMessage(window.siteMessage('client.inline_news_form.the_rich_text_editor_failed_to'), 'warning');
    return;
  }
  var BlockEmbed = Quill.import('blots/block/embed');
  // 引用是编辑器可识别的整体内容，不能直接塞进 DOM 后任由 Quill 当作未知格式移除。
  class SiteReference extends BlockEmbed {
    static create(value) {
      var node = super.create();
      var link = document.createElement('a');
      var label = document.createElement('span');
      var title = document.createElement('strong');
      var url = String(value.url || '');
      link.setAttribute('href', /^(?:\/(?!\/)|https?:\/\/)/i.test(url) && !/[\x00-\x20\\]/.test(url) ? url : '#');
      link.setAttribute('tabindex', '-1');
      label.className = 'news-reference-type';
      label.textContent = (value.label || window.siteMessage('client.inline_news_form.page'));
      title.className = 'news-reference-title';
      title.textContent = value.title || value.label || window.siteMessage('client.inline_news_form.page');
      link.appendChild(label);
      link.appendChild(title);
      node.appendChild(link);
      node.setAttribute('contenteditable', 'false');
      return node;
    }
    static value(node) {
      var link = node.querySelector('a');
      var label = node.querySelector('.news-reference-type');
      var title = node.querySelector('.news-reference-title');
      return {
        url: link ? link.getAttribute('href') : '',
        label: label ? label.textContent : '',
        title: title ? title.textContent : '',
      };
    }
  }
  SiteReference.blotName = 'siteReference';
  SiteReference.tagName = 'div';
  SiteReference.className = 'news-reference';
  Quill.register(SiteReference);
  editorElement.hidden = false;
  contentTextarea.hidden = true;
  contentTextarea.setAttribute('data-error-target', '#editor .ql-editor');
  var quill = new Quill('#editor', {
    theme: 'snow',
    placeholder: window.siteMessage('client.inline_news_form.news_body'),
    modules: {clipboard: {matchVisual: false}, toolbar: {
      container: [
        ['bold', 'italic', 'underline', 'strike'],
        [{'header': 1}, {'header': 2}],
        [{'list': 'ordered'}, {'list': 'bullet'}],
        [{'align': []}],
        ['link', 'image'],
        ['clean']
      ],
      handlers: {image: function () {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.onchange = function () {
          var file = input.files && input.files[0];
          if (!file) return;
          var fd = new FormData();
          fd.append('image', file);
          fd.append('csrf_token', csrfToken());
          var range = quill.getSelection(true) || {index: quill.getLength()};
          fetch('/admin/upload/image', {
            method: 'POST',
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            body: fd
          }).then(function (response) {
            return response.json().then(function (data) {
              if (!response.ok) throw new Error(data.error || window.siteMessage('client.inline_news_form.image_upload_failed'));
              return data;
            });
          }).then(function (data) {
            quill.insertEmbed(range.index, 'image', data.url);
          }).catch(function (error) {
            showEditorMessage(error.message || window.siteMessage('client.inline_news_form.image_upload_failed'));
          });
        };
        input.click();
      }}
    }}
  });
  var restoring = false;
  // 编辑器内容 → content 字段（空正文写成空字符串，必填检查才认得出来）
  function syncContent() {
    var empty = !quill.getText().trim() && !quill.root.querySelector('img, .news-reference');
    contentTextarea.value = empty ? '' : quill.root.innerHTML.trim();
  }
  function loadContent(content) {
    restoring = true;
    try {
      quill.setContents(quill.clipboard.convert(content || ''), 'silent');
      syncContent();
    } finally {
      restoring = false;
    }
  }
  loadContent(contentTextarea.value);
  syncContent();
  quill.on('text-change', function () {
    if (restoring) return;
    syncContent();
    contentTextarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
  // 恢复草稿：把草稿里的正文放回编辑器
  form.addEventListener('admin-draft:restored', function () {
    loadContent(contentTextarea.value);
  });
  form.addEventListener('submit', syncContent, true);

  var toggle = document.getElementById('referenceToggle');
  var controls = document.getElementById('referenceControls');
  var urlInput = document.getElementById('referenceUrl');
  var resolveButton = document.getElementById('referenceResolve');
  var insertButton = document.getElementById('referenceInsert');
  var preview = document.getElementById('referencePreview');
  var previewContent = document.getElementById('referencePreviewContent');
  var referenceMessage = document.getElementById('referenceMessage');
  var currentReference = null;
  var lookupVersion = 0;
  var lookupController = null;
  var editorRange = null;
  toggle.hidden = false;
  quill.root.setAttribute('aria-label', window.siteMessage('client.inline_news_form.article_content'));
  quill.on('selection-change', function (range) { if (range) editorRange = range; });
  quill.root.addEventListener('click', function (event) {
    if (event.target.closest('.news-reference a')) event.preventDefault();
  });

  // 进度（正在读取）写在链接框下面；出错改用右上角提示，链接本身有问题时把链接框标红
  function showReferenceMessage(message, failed, badLink) {
    referenceMessage.textContent = failed ? '' : message;
    referenceMessage.hidden = failed || !message;
    if (badLink) urlInput.setAttribute('aria-invalid', 'true'); else urlInput.removeAttribute('aria-invalid');
    if (failed) window.showToast(message, 'error', { key: 'news-reference' });
    else window.dismissToast('news-reference');
  }
  function clearPreview() {
    lookupVersion += 1;
    if (lookupController) lookupController.abort();
    lookupController = null;
    currentReference = null;
    preview.hidden = true;
    previewContent.replaceChildren();
    insertButton.disabled = true;
    resolveButton.disabled = false;
    showReferenceMessage('', false);
  }
  function readReference() {
    clearPreview();
    var value = urlInput.value.trim();
    if (!value) {
      showReferenceMessage(window.siteMessage('client.inline_news_form.enter_a_site_page_url'), true, true);
      urlInput.focus();
      return;
    }
    var version = lookupVersion;
    lookupController = new AbortController();
    resolveButton.disabled = true;
    showReferenceMessage(window.siteMessage('client.inline_news_form.reading_page'), false);
    fetch(form.dataset.referenceUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': form.elements.csrf_token.value,
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify({ url: value }),
      signal: lookupController.signal,
    }).then(function (response) {
      return response.json().catch(function () { throw new Error(); }).then(function (data) {
        if (!response.ok || !data.ok || !data.reference) {
          var error = new Error(data.msg || data.error || window.siteMessage('client.inline_news_form.could_not_read_the_page_please'));
          error.userMessage = true;
          throw error;
        }
        return data.reference;
      });
    }).then(function (reference) {
      if (version !== lookupVersion) return;
      currentReference = reference;
      var previewBlock = SiteReference.create(reference);
      var previewLink = previewBlock.querySelector('a');
      previewLink.setAttribute('target', '_blank');
      previewLink.setAttribute('rel', 'noopener');
      previewLink.removeAttribute('tabindex');
      previewContent.replaceChildren(previewBlock);
      preview.hidden = false;
      insertButton.disabled = false;
      showReferenceMessage('', false);
    }).catch(function (error) {
      if (version !== lookupVersion || error.name === 'AbortError') return;
      showReferenceMessage(error.userMessage ? error.message : window.siteMessage('client.inline_news_form.could_not_read_the_page_please'), true, !!error.userMessage);
    }).finally(function () {
      if (version === lookupVersion) {
        resolveButton.disabled = false;
        lookupController = null;
      }
    });
  }
  toggle.addEventListener('click', function () {
    controls.hidden = !controls.hidden;
    toggle.setAttribute('aria-expanded', String(!controls.hidden));
    if (!controls.hidden) urlInput.focus();
    else clearPreview();
  });
  urlInput.addEventListener('input', clearPreview);
  urlInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { event.preventDefault(); readReference(); }
    if (event.key === 'Escape') {
      event.preventDefault();
      clearPreview();
      controls.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      toggle.focus();
    }
  });
  resolveButton.addEventListener('click', readReference);
  insertButton.addEventListener('click', function () {
    if (!currentReference) return;
    var index = editorRange ? editorRange.index + editorRange.length : quill.getLength() - 1;
    index = Math.max(0, Math.min(index, quill.getLength() - 1));
    // 不覆盖选中的旧文字；引用插入选区之后，并留出下一行继续编辑。
    quill.history.cutoff();
    if (index > 0 && quill.getText(index - 1, 1) !== '\n') {
      quill.insertText(index, '\n', 'user');
      index += 1;
    }
    quill.insertEmbed(index, 'siteReference', currentReference, 'user');
    if (quill.getLength() <= index + 1) quill.insertText(index + 1, '\n', 'user');
    quill.setSelection(index + 1, 0, 'silent');
    quill.history.cutoff();
    syncContent();
    contentTextarea.dispatchEvent(new Event('input', { bubbles: true }));
    clearPreview();
    controls.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
  });
  // 工具按钮使用同一套可翻译名称，键盘和悬停都能辨认。
  var toolLabels = { bold: window.siteMessage('client.inline_news_form.bold'), italic: window.siteMessage('client.inline_news_form.italic'), underline: window.siteMessage('client.inline_news_form.underline'), strike: window.siteMessage('client.inline_news_form.strikethrough'), header: window.siteMessage('client.inline_news_form.title'), list: window.siteMessage('client.inline_news_form.list'), link: window.siteMessage('client.inline_news_form.link'), image: window.siteMessage('client.inline_news_form.insert_image'), clean: window.siteMessage('client.inline_news_form.clear_formatting') };
  Object.keys(toolLabels).forEach(function (name) {
    form.querySelectorAll('.ql-toolbar button.ql-' + name).forEach(function (button) {
      var label = toolLabels[name];
      if (name === 'header') label = button.value === '1' ? window.siteMessage('client.inline_news_form.heading_1') : window.siteMessage('client.inline_news_form.heading_2');
      if (name === 'list') label = button.value === 'ordered' ? window.siteMessage('client.inline_news_form.numbered_list') : window.siteMessage('client.inline_news_form.bulleted_list');
      label = label;
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
    });
  });
  var alignment = form.querySelector('.ql-align .ql-picker-label');
  if (alignment) { alignment.setAttribute('aria-label', window.siteMessage('client.inline_news_form.text_alignment')); alignment.setAttribute('title', window.siteMessage('client.inline_news_form.text_alignment')); }
})();
