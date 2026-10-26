// 全站通用的提示条和确认框（前台、后台、登录 / 改密码页共用）。
// 只在还没有定义时注册，重复引入也不会覆盖。
// ==================== 提示条（右上角浮动） / 确认框（替代浏览器 alert/confirm） ====================
// showToast(文字, 类型, 选项)：类型 error / warning / success / info；样式在 static/css/toast.css。
//   错误和警告不会自动消失，要手动关（重要的不能一闪而过）；成功、说明 6 秒后收起，鼠标停在上面或键盘焦点在里面时暂停。
//   选项 key：同一个 key 只保留最新一条（如表单校验汇总）；actions：[{label, run, close}] 提示里的小按钮；duration：停留毫秒。
//   多条从上往下堆叠，最多 5 条；有模态弹窗（<dialog>）开着时放进弹窗里，不会被挡住。
// updateToast(key, 文字, actions)：原地改已有的那一条（内容没变就不动），没有这一条时什么都不做。
// 服务器提示（flash）由 templates/_flash_toasts.html 输出成同样的提示条，本文件给它们补上关闭按钮、计时和读屏播报。
// 另外两件配套的事：浏览器自带的“请填写此字段”气泡换成同一套提示；checkUploadFile 检查上传文件的大小和格式。
(function() {
  if (window.showToast && window.showConfirm) return;

  var ICONS = {
    error: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5.5M12 16.3h.01"/>',
    warning: '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4M12 17h.01"/>',
    success: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.7 2.7L16 9.6"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 7.8h.01"/>',
    close: '<path d="M7 7l10 10M17 7L7 17"/>'
  };
  var DURATION = { success: 6000, info: 6000, warning: 0, error: 0 };
  var MAX_TOASTS = 5;
  // 提示至少放在顶栏（前台、后台）下面
  var HEADERS = '.navbar, .admin-topbar';
  // 提示不能挡住的东西：按钮、链接、输入框、下拉框、标签页
  var CONTROLS = 'a[href], button, input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="tab"]';

  function tr(text) { return window.siteTranslate ? window.siteTranslate(text) : text; }
  function isEnglish() { return (document.documentElement.lang || '').indexOf('en') === 0; }

  function svg(name, cls) {
    return '<svg class="' + cls + '" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + ICONS[name] + '</svg>';
  }

  function normalizeType(type) {
    return { error: 'error', danger: 'error', warning: 'warning', warn: 'warning', success: 'success' }[type] || 'info';
  }

  // 有模态弹窗开着时，提示要放进弹窗（否则在弹窗下面、点不到）；否则用页面上已有的提示区或新建一个
  function ensureContainer() {
    var modal = null;
    try { modal = document.querySelector('dialog:modal'); } catch (e) { modal = null; }
    var container = modal ? modal.querySelector('.site-toast-container')
      : document.querySelector('.site-toast-container:not(dialog .site-toast-container)');
    if (container) return container;
    container = document.createElement('div');
    container.className = 'site-toast-container';
    (modal || document.body).appendChild(container);
    if (modal) modal.addEventListener('close', function() { moveOut(container); }, { once: true });
    return container;
  }

  // 弹窗关掉后，里面还没关的提示搬回页面上，不会跟着弹窗一起看不见
  function moveOut(container) {
    var items = Array.prototype.slice.call(container.querySelectorAll(':scope > .site-toast'));
    container.remove();
    if (!items.length) return;
    var target = ensureContainer();
    items.forEach(function(item) { target.appendChild(item); });
    placeContainer(target);
  }

  function headerBottom() {
    var bottom = 0;
    document.querySelectorAll(HEADERS).forEach(function(bar) {
      var box = bar.getBoundingClientRect();
      if (box.height && box.top < window.innerHeight * 0.4 && box.bottom > bottom) bottom = box.bottom;
    });
    return bottom;
  }

  // 提示那一列（column 的左右）从 top 往下 height 的范围里，看得见的按钮、输入框最低的底边；没有就返回 0。
  // 只算主体（中心点）落在这一列里的：很宽的输入框只被盖住右端一小段时，照样能点、能填，不为它往下让
  function lowestControl(root, column, top, height) {
    var lowest = 0;
    Array.prototype.forEach.call(root.querySelectorAll(CONTROLS), function(el) {
      if (el.closest('.site-toast-container')) return;
      var box = el.getBoundingClientRect();
      var center = (box.left + box.right) / 2;
      if (!box.width || !box.height || center < column.left || center > column.right) return;
      if (box.bottom > top && box.top < top + height && box.bottom > lowest) lowest = box.bottom;
    });
    return lowest;
  }

  // 提示区的上边：放在顶栏下面；那一列里有按钮、输入框会被挡住时，往下让到它们下面
  // （最多让过两排，如标题行的“新增”和工具条的“保存”；不低于屏幕 40% 高度）。弹窗开着时只看弹窗自己的按钮。
  // 提示多到放不下时，提示区自己上下滚动（不超出屏幕）
  function placeContainer(container) {
    var dialog = container.closest('dialog');
    var column = container.getBoundingClientRect();
    var height = container.scrollHeight + 12;
    var top = dialog ? 0 : headerBottom();
    for (var row = 0; row < 2; row += 1) {
      var below = lowestControl(dialog || document, column, top, height);
      if (!below || below > window.innerHeight * 0.4) break;
      top = below;
    }
    container.style.setProperty('--toast-top', Math.round(top) + 'px');
    fitContainer(container);
  }

  // 内容比提示区高就让它内部滚动；只在状态变了时才改，免得滚到一半的位置被重置
  function fitContainer(container) {
    var overflowing = container.scrollHeight > container.clientHeight + 1;
    if (overflowing !== container.classList.contains('is-scrollable')) container.classList.toggle('is-scrollable', overflowing);
  }

  // 改变窗口大小时重新摆（每帧最多一次）。页面滚动时不跟着动，和平常的浮动提示一样停在原处
  var placeQueued = false;
  function queuePlace() {
    if (placeQueued || !document.querySelector('.site-toast')) return;
    placeQueued = true;
    requestAnimationFrame(function() {
      placeQueued = false;
      document.querySelectorAll('.site-toast-container').forEach(placeContainer);
    });
  }
  window.addEventListener('resize', queuePlace);

  // 读屏要读的文字：提示内容加上小按钮上的字
  function spokenText(el) {
    var parts = [el.querySelector('.site-toast-msg').textContent];
    el.querySelectorAll('.site-toast-action').forEach(function(button) { parts.push(button.textContent); });
    return parts.join(' ');
  }

  // 读屏播报：新出现的错误提示本身是 role=alert，插进页面就会被读；其余提示、以及页面一打开就有的
  // 服务器错误，交给提示区里看不见的播报区读（先清空再写入才会被读出来）
  function announce(container, el, urgent) {
    var cls = urgent ? 'site-toast-sr-urgent' : 'site-toast-sr-polite';
    var region = container.querySelector(':scope > .' + cls);
    if (!region) {
      region = document.createElement('div');
      region.className = 'site-toast-sr ' + cls;
      region.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
      region.setAttribute('aria-atomic', 'true');
      container.appendChild(region);
    }
    region.textContent = '';
    setTimeout(function() { region.textContent = spokenText(el); }, 150);
  }

  function dismiss(el) {
    if (!el || !el.parentNode || el.classList.contains('toast-out')) return;
    clearTimeout(el._toastTimer);
    el.classList.add('toast-out');
    var done = function() {
      var container = el.parentNode;
      if (!container) return;
      el.remove();
      fitContainer(container);
    };
    el.addEventListener('animationend', done);
    setTimeout(done, 400);
  }

  // 计时：鼠标停在上面或键盘焦点在里面时暂停，移开后重新计时
  function startTimer(el, type, duration) {
    var wait = duration != null ? duration : DURATION[type];
    if (!wait) return;
    var arm = function() { clearTimeout(el._toastTimer); el._toastTimer = setTimeout(function() { dismiss(el); }, wait); };
    var hold = function() { clearTimeout(el._toastTimer); };
    el.addEventListener('mouseenter', hold);
    el.addEventListener('focusin', hold);
    el.addEventListener('mouseleave', arm);
    el.addEventListener('focusout', arm);
    arm();
  }

  function actionRow(actions, el) {
    var row = document.createElement('div');
    row.className = 'site-toast-actions';
    actions.forEach(function(action) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'site-toast-action';
      button.textContent = action.label;
      button.addEventListener('click', function() {
        if (action.run) action.run();
        if (action.close) dismiss(el);
      });
      row.appendChild(button);
    });
    return row;
  }

  // 给一条提示补上图标、正文区（错误是 role=alert）、小按钮和关闭按钮；新建的和服务器输出的都走这里
  function decorate(el, type, actions) {
    el.setAttribute('data-enhanced', '1');
    var body = el.querySelector('.site-toast-body');
    if (!body) {
      body = document.createElement('div');
      body.className = 'site-toast-body';
      el.insertBefore(body, el.firstChild);
      body.appendChild(el.querySelector('.site-toast-msg'));
    }
    if (type === 'error') body.setAttribute('role', 'alert');
    var icon = document.createElement('span');
    icon.className = 'site-toast-icon';
    icon.innerHTML = svg(type, 'site-toast-svg');
    el.insertBefore(icon, body);
    if (actions && actions.length) body.appendChild(actionRow(actions, el));
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'site-toast-close';
    close.setAttribute('aria-label', tr('关闭提示'));
    close.title = tr('关闭提示');
    close.innerHTML = svg('close', 'site-toast-svg');
    close.addEventListener('click', function() { dismiss(el); });
    el.appendChild(close);
  }

  // 按 key 找提示；includeLeaving=true 时连正在淡出的也算（换成新的一条时要一起马上去掉）
  function findByKey(key, includeLeaving) {
    return Array.prototype.filter.call(document.querySelectorAll('.site-toast[data-toast-key]'), function(el) {
      return el.getAttribute('data-toast-key') === key && (includeLeaving || !el.classList.contains('toast-out'));
    });
  }

  function signature(msg, actions) {
    return String(msg) + '\n' + (actions || []).map(function(action) { return action.label; }).join('\n');
  }

  window.showToast = function(msg, type, options) {
    options = options || {};
    type = normalizeType(type);
    if (options.key) window.dismissToast(options.key, true);
    var el = document.createElement('div');
    el.className = 'site-toast toast-' + type;
    if (options.key) el.setAttribute('data-toast-key', options.key);
    el._toastSig = signature(msg == null ? '' : msg, options.actions);
    var text = document.createElement('span');
    text.className = 'site-toast-msg';
    text.textContent = String(msg == null ? '' : msg);
    el.appendChild(text);
    decorate(el, type, options.actions);
    var container = ensureContainer();
    container.appendChild(el);
    var items = container.querySelectorAll(':scope > .site-toast');
    for (var i = 0; i < items.length - MAX_TOASTS; i += 1) items[i].remove();
    placeContainer(container);
    // 页面这一轮里可能还会滚到出错的字段：滚完再摆一次位置
    queuePlace();
    // 提示区在滚动时，把新来的这条滚到看得见的地方
    if (container.classList.contains('is-scrollable')) container.scrollTop = container.scrollHeight;
    startTimer(el, type, options.duration);
    if (type !== 'error') announce(container, el, false);
    return el;
  };

  window.updateToast = function(key, msg, actions) {
    var el = findByKey(key)[0];
    if (!el) return null;
    var sig = signature(msg == null ? '' : msg, actions);
    if (el._toastSig === sig) return el;
    el._toastSig = sig;
    el.querySelector('.site-toast-msg').textContent = String(msg == null ? '' : msg);
    var body = el.querySelector('.site-toast-body');
    var old = body.querySelector('.site-toast-actions');
    if (old) old.remove();
    if (actions && actions.length) body.appendChild(actionRow(actions, el));
    fitContainer(el.parentNode);
    return el;
  };

  // 关掉指定的提示：传 key 文字或提示元素；immediate=true 时不放收起动画（马上换成新的一条）
  window.dismissToast = function(target, immediate) {
    var items = typeof target === 'string' ? findByKey(target, immediate) : [target];
    items.forEach(function(el) {
      if (!el) return;
      if (!immediate) { dismiss(el); return; }
      var container = el.parentNode;
      clearTimeout(el._toastTimer);
      if (!container) return;
      el.remove();
      fitContainer(container);
    });
  };

  // 服务器输出的提示（页面打开时就有）：原地补上按钮和计时（不挪动，后台表单脚本还要读它），再交给播报区读出来
  function enhanceServerToasts() {
    document.querySelectorAll('.site-toast[data-toast-type]:not([data-enhanced])').forEach(function(el) {
      var type = normalizeType(el.getAttribute('data-toast-type'));
      decorate(el, type);
      startTimer(el, type);
      placeContainer(el.parentNode);
      announce(el.parentNode, el, type === 'error');
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', enhanceServerToasts);
  else enhanceServerToasts();

  // ==================== 浏览器自带的填写检查 → 同一套提示 ====================
  // 不弹浏览器的气泡（它的语言跟着浏览器、不跟网站）：字段标红、展开并定位到第一个，右上角写明要改什么。
  // 后台表单自己校验（form.noValidate），不会走到这里。
  var pendingInvalid = null;

  function fieldLabel(field) {
    var text = field.getAttribute('aria-label') || '';
    var label = field.labels && field.labels[0];
    if (!text && label) text = (label.querySelector('.field-label, span') || label).textContent;
    if (!text && field.type === 'radio') {
      var legend = field.closest('fieldset') && field.closest('fieldset').querySelector('legend');
      text = legend ? legend.textContent : '';
    }
    return (text || field.placeholder || field.name || '').replace(/[*＊]/g, '').replace(/[：:？?]\s*$/, '').replace(/\s+/g, ' ').trim();
  }

  function invalidMessage(field) {
    var v = field.validity;
    var en = isEnglish();
    var label = fieldLabel(field);
    if (v.customError) return field.validationMessage;
    if (v.valueMissing) {
      var choose = field.tagName === 'SELECT' || /^(radio|checkbox|file)$/.test(field.type);
      return en ? (choose ? 'Please choose ' : 'Please fill in ') + label : (choose ? '请选择' : '请填写') + label;
    }
    if (v.tooShort) return en ? label + ' needs at least ' + field.minLength + ' characters' : label + '至少 ' + field.minLength + ' 个字符';
    if (v.tooLong) return en ? label + ' allows at most ' + field.maxLength + ' characters' : label + '不能超过 ' + field.maxLength + ' 个字符';
    if (v.rangeUnderflow) return en ? label + ' must be at least ' + field.min : label + '不能小于 ' + field.min;
    if (v.rangeOverflow) return en ? label + ' must be at most ' + field.max : label + '不能大于 ' + field.max;
    return en ? label + ' is not valid' : label + '格式不正确';
  }

  // 定位到字段：展开所在折叠块；字段本身看不见（如美化过的文件框）就定位到它的标签
  function focusInvalid(field) {
    for (var d = field.closest('details'); d; d = d.parentElement && d.parentElement.closest('details')) d.open = true;
    var target = field.getClientRects().length ? field : ((field.labels && field.labels[0]) || field);
    var box = target.getBoundingClientRect();
    if (box.top < 80 || box.bottom > window.innerHeight - 20) target.scrollIntoView({ block: 'center' });
    try { target.focus({ preventScroll: true }); } catch (e) { target.focus(); }
  }

  function flushInvalid() {
    var fields = pendingInvalid;
    pendingInvalid = null;
    focusInvalid(fields[0]);
    var many = fields.length > 1;
    var text = !many ? invalidMessage(fields[0])
      : (isEnglish() ? fields.length + ' fields need fixing:' : fields.length + ' 处需要填写或修改：');
    var actions = !many ? [] : fields.slice(0, 5).map(function(field) {
      return { label: invalidMessage(field), run: function() { focusInvalid(field); } };
    });
    window.showToast(text, 'error', { key: 'form-invalid', actions: actions });
  }

  document.addEventListener('invalid', function(event) {
    var field = event.target;
    if (!field || !field.validity) return;
    event.preventDefault();
    if (!pendingInvalid) { pendingInvalid = []; setTimeout(flushInvalid, 0); }
    // 同一组单选只算一项；同一个字段被检查两次也只算一次
    var duplicate = pendingInvalid.some(function(other) {
      return other === field || (field.type === 'radio' && other.type === 'radio' && other.name === field.name && other.form === field.form);
    });
    if (duplicate) return;
    pendingInvalid.push(field);
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('data-native-invalid', '');
  }, true);

  // 改对了就去掉红框；这一页全部改好后收起提示
  function clearNativeInvalid(event) {
    var field = event.target;
    if (!field || !field.hasAttribute || !field.validity || !field.validity.valid) return;
    var group = field.type === 'radio' && field.form
      ? Array.prototype.filter.call(field.form.elements, function(el) { return el.name === field.name; }) : [field];
    group.forEach(function(el) {
      if (!el.hasAttribute('data-native-invalid')) return;
      el.removeAttribute('data-native-invalid');
      el.removeAttribute('aria-invalid');
    });
    if (!document.querySelector('[data-native-invalid]')) window.dismissToast('form-invalid');
  }
  document.addEventListener('input', clearNativeInvalid);
  document.addEventListener('change', clearNativeInvalid);

  // ==================== 上传文件的前端检查 ====================
  // <input type="file" accept="..." data-max-bytes="字节数" data-size-error="太大时的话" data-type-error="格式不对时的话">
  // 返回按当前语言翻好的错误文字；没选文件或没问题返回 ''。服务器还会再检查一遍。
  function acceptsFile(input, file) {
    var rules = (input.getAttribute('accept') || '').toLowerCase().split(',')
      .map(function(rule) { return rule.trim(); }).filter(Boolean);
    if (!rules.length) return true;
    var name = file.name.toLowerCase();
    var type = (file.type || '').toLowerCase();
    return rules.some(function(rule) {
      if (rule.charAt(0) === '.') return name.slice(-rule.length) === rule;
      if (rule.slice(-2) === '/*') return type.indexOf(rule.slice(0, -1)) === 0;
      return type === rule;
    });
  }

  window.checkUploadFile = function(input) {
    var file = input && input.files && input.files[0];
    if (!file) return '';
    var max = Number(input.getAttribute('data-max-bytes') || 0);
    if (max && file.size > max) return tr(input.getAttribute('data-size-error') || '文件太大');
    if (!acceptsFile(input, file)) return tr(input.getAttribute('data-type-error') || '文件格式不支持');
    return '';
  };

  // ==================== 确认框 ====================
  window.showModal = function(msg, title) {
    return new Promise(function(resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'site-modal-overlay';
      overlay.innerHTML = '<div class="site-modal">' +
        (title ? '<div class="site-modal-title">' + title + '</div>' : '') +
        '<div class="site-modal-body">' + msg + '</div>' +
        '<div class="site-modal-actions">' +
          '<button class="site-modal-btn site-modal-btn-primary site-modal-ok">确定</button>' +
        '</div></div>';
      overlay.addEventListener('click', function(e) {
        if (e.target === overlay) { overlay.remove(); resolve(); }
      });
      overlay.querySelector('.site-modal-ok').addEventListener('click', function() {
        overlay.remove(); resolve();
      });
      document.body.appendChild(overlay);
    });
  };

  window.showConfirm = function(msg, title) {
    return new Promise(function(resolve) {
      var overlay = document.createElement('div');
      overlay.className = 'site-modal-overlay';
      overlay.innerHTML = '<div class="site-modal">' +
        (title ? '<div class="site-modal-title">' + title + '</div>' : '') +
        '<div class="site-modal-body">' + msg + '</div>' +
        '<div class="site-modal-actions">' +
          '<button class="site-modal-btn site-modal-btn-secondary site-modal-cancel">取消</button>' +
          '<button class="site-modal-btn site-modal-btn-primary site-modal-ok">确定</button>' +
        '</div></div>';
      overlay.addEventListener('click', function(e) {
        if (e.target === overlay) { overlay.remove(); resolve(false); }
      });
      overlay.querySelector('.site-modal-cancel').addEventListener('click', function() {
        overlay.remove(); resolve(false);
      });
      overlay.querySelector('.site-modal-ok').addEventListener('click', function() {
        overlay.remove(); resolve(true);
      });
      document.body.appendChild(overlay);
    });
  };

  // 用于替换 HTML 内联 onsubmit="return confirm(...)" → onsubmit="return window._confirmThen(event, '...')"
  window._confirmThen = function(e, msg) {
    e.preventDefault();
    var target = e.currentTarget || e.target;
    var form = target && target.tagName === 'FORM' ? target : (target ? target.closest('form') : null);
    showConfirm(msg).then(function(yes) {
      if (!yes || !form) return;
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin'
      }).then(function(resp) {
        if (resp.ok) window.location.href = resp.url;
        else window.location.reload();
      }).catch(function() {
        window.location.reload();
      });
    });
    return false;
  };

  // 用于替换 HTML 内联 onclick="return confirm(...)" 在链接上
  window._confirmLink = function(e, msg) {
    e.preventDefault();
    var href = e.currentTarget.getAttribute('href');
    showConfirm(msg).then(function(yes) { if (yes) window.location.href = href; });
    return false;
  };
})();
