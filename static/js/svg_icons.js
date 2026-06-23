(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var SHAPES = {
    gamepad: '<path d="M8 9h8a5 5 0 0 1 4.7 6.7l-.8 2.1a2 2 0 0 1-3.2.8L14.8 17H9.2l-1.9 1.6a2 2 0 0 1-3.2-.8l-.8-2.1A5 5 0 0 1 8 9Z"/><path d="M7 13h4M9 11v4M16.5 12.5h.01M18.5 14.5h.01"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0V4ZM9 19h6M12 13v6M8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4"/>',
    swords: '<path d="m14 5 5-3 3 3-3 5M13 6l5 5M5 22l6-6M3 19l2 2M10 5 5 5M3 2l3 5 11 11M14 21l3-3 4 4"/>',
    news: '<path d="M4 4h15a1 1 0 0 1 1 1v14a2 2 0 0 1-2 2H5a3 3 0 0 1-3-3V6h2v12a1 1 0 0 0 2 0V7h11M8 9h7M8 13h7M8 17h5"/>',
    radio: '<path d="M5.6 8.6a9 9 0 0 0 0 6.8M2.8 5.8a13 13 0 0 0 0 12.4M18.4 8.6a9 9 0 0 1 0 6.8M21.2 5.8a13 13 0 0 1 0 12.4"/><circle cx="12" cy="12" r="2"/><path d="M12 14v8"/>',
    medal: '<circle cx="12" cy="15" r="5"/><path d="m9 10-3-8h4l2 5 2-5h4l-3 8"/>',
    bookmark: '<path d="M6 3h12v18l-6-4-6 4V3Z"/>',
    save: '<path d="M4 3h14l2 2v16H4V3Z"/><path d="M8 3v6h8V3M8 21v-8h8v8"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/>',
    plus: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    pencil: '<path d="m4 16-1 5 5-1L19 9l-4-4L4 16ZM14 6l4 4M3 21h18"/>',
    clipboard: '<path d="M9 4h6M9 2h6v4H9V2ZM7 4H5v18h14V4h-2M8 11h8M8 15h8M8 19h5"/>',
    trash: '<path d="M3 6h18M8 6V3h8v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/>',
    check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    close: '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    mail: '<path d="M3 6h18v14H3V6Z"/><path d="m3 8 9 6 9-6M7 6V3h10v3"/>',
    folder: '<path d="M3 5h7l2 3h9v11H3V5Z"/><path d="M3 9h18"/>',
    download: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
    alert: '<path d="M12 3 2 21h20L12 3Z"/><path d="M12 9v5M12 18h.01"/>',
    rocket: '<path d="M14 4c3-2 6-2 7-2 0 1 0 4-2 7l-6 6-4-4 5-7Z"/><path d="m9 11-4 1-3 3 6 1 1-5ZM13 15l-1 4-3 3-1-6 5-1Z"/><circle cx="16" cy="7" r="1.5"/>',
    refresh: '<path d="M20 6v5h-5M4 18v-5h5M6.1 9a7 7 0 0 1 11.8-2.1L20 11M4 13l2.1 4.1A7 7 0 0 0 17.9 15"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H3v-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V3h4v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
    map: '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z"/><path d="M9 3v15M15 6v15"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    tv: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3V9ZM8 22h8"/>',
    monitor: '<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 22h8M12 18v4"/>',
    hourglass: '<path d="M6 2h12M6 22h12M7 2c0 5 2 7 5 10-3 3-5 5-5 10M17 2c0 5-2 7-5 10 3 3 5 5 5 10"/>',
    megaphone: '<path d="M3 11v4h4l10 4V7L7 11H3ZM7 15l2 6h3l-2-5M20 10v6"/>',
    crown: '<path d="m3 7 4 4 5-7 5 7 4-4-2 12H5L3 7ZM5 19h14"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
    moon: '<path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/>',
    message: '<path d="M21 12a8 8 0 0 1-8 8H5l-3 2 1-5a8 8 0 1 1 18-5Z"/><path d="M8 12h.01M12 12h.01M16 12h.01"/>',
    arrowLeft: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    pin: '<path d="m9 3 6 6-2 2 4 4-2 2-4-4-2 2-6-6 6-6ZM8 16l-5 5"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    eye: '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    heart: '<path d="M20.8 5.7a5.5 5.5 0 0 0-7.8 0L12 6.8l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 22l8.8-8.5a5.5 5.5 0 0 0 0-7.8Z"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4V8Z"/>',
    vote: '<path d="M5 3h14v7H5V3ZM3 10h18v11H3V10Z"/><path d="m9 6 2 2 4-4M8 16h8"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    sort: '<path d="m8 4-4 4h8L8 4ZM16 20l4-4h-8l4 4Z"/><path d="M8 8v12M16 4v12"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>'
  };

  var ICONS = {};
  function add(codePoint, shape, label) {
    ICONS[String.fromCodePoint(codePoint)] = { shape: shape, label: label };
  }

  add(0x1f3ae, 'gamepad', '游戏');
  add(0x1f4ca, 'chart', '数据');
  add(0x1f465, 'users', '队伍');
  add(0x1f3af, 'target', '目标');
  add(0x1f3c6, 'trophy', '奖杯');
  add(0x2694, 'swords', '比赛');
  add(0x1f4f0, 'news', '新闻');
  add(0x1f4e1, 'radio', '直播');
  add(0x1f3c5, 'medal', '奖牌');
  add(0x1f516, 'bookmark', '书签');
  add(0x1f4be, 'save', '保存');
  add(0x1f310, 'globe', '网站');
  add(0x2795, 'plus', '添加');
  add(0x270f, 'pencil', '编辑');
  add(0x1f4cb, 'clipboard', '清单');
  add(0x1f5d1, 'trash', '删除');
  add(0x2705, 'check', '成功');
  add(0x274c, 'close', '失败');
  add(0x1f4ec, 'mail', '反馈');
  add(0x1f4c2, 'folder', '打开文件');
  add(0x1f4e5, 'download', '导入');
  add(0x1f50d, 'search', '搜索');
  add(0x26a0, 'alert', '警告');
  add(0x1f680, 'rocket', '开始');
  add(0x1f504, 'refresh', '刷新');
  add(0x2699, 'settings', '设置');
  add(0x1f5fa, 'map', '地图');
  add(0x1f512, 'lock', '锁定');
  add(0x1f4fa, 'tv', '观看');
  add(0x1f5a5, 'monitor', '服务器');
  add(0x23f3, 'hourglass', '等待');
  add(0x1f4e2, 'megaphone', '公告');
  add(0x1f451, 'crown', '冠军');
  add(0x1f514, 'bell', '通知');
  add(0x1f319, 'moon', '深色模式');
  add(0x1f4ac, 'message', '消息');
  add(0x1f448, 'arrowLeft', '这里');
  add(0x1f4cc, 'pin', '置顶');
  add(0x1f464, 'user', '用户');
  add(0x1f550, 'clock', '时间');
  add(0x1f441, 'eye', '浏览');
  add(0x2764, 'heart', '喜欢');
  add(0x25b6, 'play', '播放');
  add(0x1f5f3, 'vote', '投票');
  add(0x1f947, 'medal', '第一名');
  add(0x1f948, 'medal', '第二名');
  add(0x1f949, 'medal', '第三名');
  add(0x2600, 'sun', '浅色模式');
  add(0x2139, 'info', '提示');
  add(0x2195, 'sort', '排序');
  add(0x2630, 'menu', '菜单');
  add(0x2715, 'close', '关闭');
  add(0x2713, 'check', '完成');
  add(0x2190, 'arrowLeft', '返回');

  var keys = Object.keys(ICONS).sort(function (a, b) { return b.length - a.length; });
  var escaped = keys.map(function (key) {
    return key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  });
  var iconPattern = new RegExp('(' + escaped.join('|') + ')\\uFE0F?', 'gu');

  function createIcon(symbol) {
    var normalized = symbol.replace(/\uFE0F/g, '');
    var data = ICONS[normalized];
    if (!data) return document.createTextNode(symbol);

    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'site-svg-icon');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', data.label);
    svg.innerHTML = '<title>' + data.label + '</title>' + SHAPES[data.shape];
    return svg;
  }

  function replaceTextNode(node) {
    if (!node.nodeValue) return;
    iconPattern.lastIndex = 0;
    if (!iconPattern.test(node.nodeValue)) return;
    iconPattern.lastIndex = 0;

    var fragment = document.createDocumentFragment();
    var text = node.nodeValue;
    var lastIndex = 0;
    text.replace(iconPattern, function (match, symbol, offset) {
      if (offset > lastIndex) fragment.appendChild(document.createTextNode(text.slice(lastIndex, offset)));
      fragment.appendChild(createIcon(symbol));
      lastIndex = offset + match.length;
      return match;
    });
    if (lastIndex < text.length) fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
    node.replaceWith(fragment);
  }

  function shouldSkip(node) {
    var parent = node.parentElement;
    if (!parent) return true;
    return /^(SCRIPT|STYLE|TEXTAREA|TITLE|SVG)$/.test(parent.tagName) ||
      parent.closest('svg, [contenteditable="true"]');
  }

  function replaceAttributes(root) {
    if (!root || !root.querySelectorAll) return;
    var elements = [];
    if (root.nodeType === Node.ELEMENT_NODE &&
        root.matches('[title], [aria-label], [placeholder]')) elements.push(root);
    root.querySelectorAll('[title], [aria-label], [placeholder]').forEach(function (element) {
      elements.push(element);
    });
    elements.forEach(function (element) {
      ['title', 'aria-label', 'placeholder'].forEach(function (name) {
        var value = element.getAttribute(name);
        if (!value) return;
        iconPattern.lastIndex = 0;
        if (!iconPattern.test(value)) return;
        iconPattern.lastIndex = 0;
        var replacement = value.replace(iconPattern, function (match, symbol) {
          var data = ICONS[symbol.replace(/\uFE0F/g, '')];
          return data ? data.label : '';
        });
        if (replacement !== value) element.setAttribute(name, replacement);
      });
    });
  }

  function replaceIn(root) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      if (!shouldSkip(root)) replaceTextNode(root);
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;

    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) {
      if (!shouldSkip(walker.currentNode)) nodes.push(walker.currentNode);
    }
    nodes.forEach(replaceTextNode);
    replaceAttributes(root);
  }

  function addStyles() {
    if (document.getElementById('siteSvgIconStyles')) return;
    var style = document.createElement('style');
    style.id = 'siteSvgIconStyles';
    style.textContent = '.site-svg-icon{display:inline-block;width:1.08em;height:1.08em;vertical-align:-.16em;flex:0 0 auto;color:currentColor;overflow:visible}.icon,.award-icon,.like-icon,.stream-play-icon{line-height:1}.icon>.site-svg-icon,.award-icon>.site-svg-icon{width:1em;height:1em}';
    document.head.appendChild(style);
  }

  function start() {
    addStyles();
    replaceIn(document.body);
    new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        if (mutation.type === 'characterData') replaceIn(mutation.target);
        if (mutation.type === 'attributes') replaceAttributes(mutation.target);
        mutation.addedNodes.forEach(replaceIn);
      });
    }).observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['title', 'aria-label', 'placeholder']
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
