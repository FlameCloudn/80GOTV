import { message as siteMessage } from '../../shared/i18n.js';
import { escapeHtml } from '../../shared/dom.mjs';

// ==================== 移动端搜索 ====================
const searchToggle = document.getElementById('searchToggle');
const searchForm = document.getElementById('searchForm');
const mobileSearchBrowse = document.getElementById('mobileSearchBrowse');
let mobileSearchBrowseLoaded = false;

function mobileSearchCard(item, type) {
  var label = item.nickname || item.name || siteMessage('client.navigation.untitled');
  var meta = '';
  var image = '';
  // 优先沿用网站接口返回的队伍和赛事缩写。
  var initials = item.abbr || label.trim().slice(0, 2).toUpperCase();
  if (type === 'players') {
    if (item.group_username) label += ' @' + item.group_username;
    meta = item.team || siteMessage('client.navigation.players');
    image = item.avatar || '';
  } else if (type === 'teams') {
    meta = item.short_name || siteMessage('client.navigation.teams');
    image = item.logo || '';
  } else {
    meta = item.start_date || item.status || siteMessage('client.navigation.events');
  }
  var visual = image
    ? '<img src="' + escapeHtml(image) + '" alt="">'
    : '<span class="mobile-search-card-fallback">' + escapeHtml(initials) + '</span>';
  return '<a class="mobile-search-card" href="' + escapeHtml(item.url || '#') + '">' +
    '<span class="mobile-search-card-visual">' + visual + '</span>' +
    '<strong>' + escapeHtml(label) + '</strong>' +
    '<small>' + escapeHtml(meta) + '</small>' +
  '</a>';
}

function mobileSearchSection(title, type, items) {
  if (!items || !items.length) return '';
  return '<section class="mobile-search-section">' +
    '<header><span class="mobile-search-section-title">' + escapeHtml(title) + '</span>' +
      '<span class="mobile-search-section-controls">' +
        ("<button type=\"button\" data-search-scroll=\"-1\" aria-label=\"" + siteMessage('client.navigation.scroll_left') + "\">‹</button>") +
        ("<button type=\"button\" data-search-scroll=\"1\" aria-label=\"" + siteMessage('client.navigation.scroll_right') + "\">›</button>") +
      '</span>' +
    '</header>' +
    '<div class="mobile-search-card-track">' + items.slice(0, 10).map(function(item) {
      return mobileSearchCard(item, type);
    }).join('') + '</div>' +
  '</section>';
}

function loadMobileSearchBrowse() {
  if (!mobileSearchBrowse || mobileSearchBrowseLoaded) return;
  mobileSearchBrowseLoaded = true;
  mobileSearchBrowse.innerHTML = ("<div class=\"mobile-search-loading\">" + siteMessage('client.navigation.loading_recommendations') + "</div>");
  Promise.all([
    fetch('/api/front/players?per_page=10', {credentials:'same-origin'}).then(function(r){ return r.json(); }),
    fetch('/api/front/teams', {credentials:'same-origin'}).then(function(r){ return r.json(); }),
    fetch('/api/front/events', {credentials:'same-origin'}).then(function(r){ return r.json(); })
  ]).then(function(data) {
    var html = mobileSearchSection(siteMessage('client.navigation.players'), 'players', data[0].players) +
      mobileSearchSection(siteMessage('client.navigation.teams'), 'teams', data[1].teams) +
      mobileSearchSection(siteMessage('client.navigation.events'), 'events', data[2].events);
    mobileSearchBrowse.innerHTML = html || ("<div class=\"mobile-search-loading\">" + siteMessage('client.navigation.no_recommendations') + "</div>");
  }).catch(function() {
    mobileSearchBrowseLoaded = false;
    mobileSearchBrowse.innerHTML = ("<div class=\"mobile-search-loading\">" + siteMessage('client.navigation.recommendations_are_temporarily_unavailable') + "</div>");
  });
}

if (mobileSearchBrowse) {
  mobileSearchBrowse.addEventListener('click', function(e) {
    var button = e.target.closest('[data-search-scroll]');
    if (!button) return;
    var track = button.closest('.mobile-search-section').querySelector('.mobile-search-card-track');
    var direction = Number(button.getAttribute('data-search-scroll')) || 1;
    track.scrollBy({left: direction * Math.max(180, track.clientWidth * 0.72), behavior:'smooth'});
  });
}

function setSearchOpen(isOpen) {
  if (!searchToggle || !searchForm) return;
  const searchInput = searchForm.querySelector('input');
  searchForm.classList.toggle('open', isOpen);
  searchToggle.classList.toggle('active', isOpen);
  searchToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  searchToggle.setAttribute('aria-label', isOpen ? siteMessage('client.navigation.close_search') : siteMessage('client.navigation.open_search'));
  if (isOpen) {
    loadMobileSearchBrowse();
    if (searchInput) {
      if (window.matchMedia('(max-width:960px)').matches) {
        searchInput.setAttribute('placeholder', ' ');
      }
      searchInput.focus();
    }
  } else {
    var dropdown = document.getElementById('searchDropdown');
    if (dropdown) dropdown.classList.remove('active');
    if (mobileSearchBrowse) mobileSearchBrowse.classList.remove('query-active');
  }
}

if (searchToggle && searchForm) {
  searchToggle.addEventListener('click', () => {
    setSearchOpen(!searchForm.classList.contains('open'));
  });
  document.addEventListener('click', (e) => {
    if (!searchToggle.contains(e.target) && !searchForm.contains(e.target)) {
      setSearchOpen(false);
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && searchForm.classList.contains('open')) {
      setSearchOpen(false);
      searchToggle.focus();
    }
  });
}

// ==================== 即时搜索下拉 ====================
(function() {
  var input = document.getElementById('searchInput');
  var dropdown = document.getElementById('searchDropdown');
  if (!input || !dropdown) return;
  var externalPlayer = document.getElementById('searchExternalPlayer');
  var debounceTimer = null;
  var abortController = null;

  function hideDropdown() {
    dropdown.classList.remove('active');
    dropdown.innerHTML = '';
  }

  input.addEventListener('input', function() {
    clearTimeout(debounceTimer);
    if (abortController) abortController.abort();
    var q = input.value.trim();
    if (mobileSearchBrowse) mobileSearchBrowse.classList.toggle('query-active', Boolean(q));
    if (!q) { hideDropdown(); return; }
    debounceTimer = setTimeout(function() {
      abortController = new AbortController();
      fetch('/api/search?q=' + encodeURIComponent(q), {
        signal: abortController.signal,
        credentials: 'same-origin'
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (!data.results || data.results.length === 0) {
          dropdown.innerHTML = ("<div class=\"search-dropdown-empty\">" + siteMessage('client.navigation.no_matching_results') + "</div>");
          dropdown.classList.add('active');
          return;
        }
        var html = '';
        data.results.forEach(function(r) {
          var sub = r.type === 'player' && r.sub === '\u{1f310}' && externalPlayer
            ? externalPlayer.innerHTML : escapeHtml(r.sub);
          html += '<a class="search-dropdown-item" href="' + escapeHtml(r.url) + '">' +
            '<span class="sd-type sd-type-' + escapeHtml(r.type) + '">' + escapeHtml(r.type) + '</span>' +
            '<span class="sd-label">' + escapeHtml(r.label) + '</span>' +
            '<span class="sd-sub">' + sub + '</span>' +
          '</a>';
        });
        dropdown.innerHTML = html;
        dropdown.classList.add('active');
      })
      .catch(function(err) {
        if (err.name !== 'AbortError') console.error(err);
      });
    }, 200);
  });

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideDropdown();
  });

  // 回车提交表单（跳转到完整搜索结果页）
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && dropdown.classList.contains('active')) {
      // 回车时关闭下拉，触发表单提交
      hideDropdown();
    }
  });

  input.addEventListener('focus', function() {
    if (input.value.trim()) {
      input.dispatchEvent(new Event('input'));
    }
  });

  document.addEventListener('click', function(e) {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      hideDropdown();
    }
  });

  // 点击下拉项时导航
  dropdown.addEventListener('mousedown', function(e) {
    // 阻止 mousedown 默认行为，防止输入框失焦导致下拉消失
    e.preventDefault();
  });

  dropdown.addEventListener('click', function(e) {
    var item = e.target.closest('.search-dropdown-item');
    if (item) {
      var href = item.getAttribute('href');
      hideDropdown();
      input.value = '';
      if (href) window.location.href = href;
    }
  });
})();

// ==================== 手机抽屉菜单 ====================
// 手机上 #navPanel（导航 + 账号 + 主题 + 语言）变成右侧抽屉，顶栏下面盖一层半透明遮罩。
const hamburger = document.getElementById('hamburger');
const navLinks = document.getElementById('navLinks');
const navPanel = document.getElementById('navPanel') || navLinks;
const siteNavbar = document.querySelector('.navbar');

function setMenuOpen(isOpen){
  if (!hamburger || !navLinks) return;
  navLinks.classList.toggle('open', isOpen);
  if (siteNavbar) siteNavbar.classList.toggle('menu-open', isOpen);
  document.documentElement.classList.toggle('menu-open', isOpen);
  hamburger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  hamburger.setAttribute('aria-label', isOpen ? siteMessage('client.navigation.close_menu') : siteMessage('client.navigation.open_menu'));
}

function closeMenu(){
  setMenuOpen(false);
  setSearchOpen(false);
}

if (searchToggle) {
  // 打开搜索时先收起抽屉，两个浮层不叠在一起
  searchToggle.addEventListener('click', function(){
    if (searchForm && searchForm.classList.contains('open')) setMenuOpen(false);
  });
}

if(hamburger && navLinks){
  hamburger.addEventListener('click', ()=>{
    if (navLinks.classList.contains('open')) {
      closeMenu();
      return;
    }
    setSearchOpen(false);
    setMenuOpen(true);
  });

  // 点击菜单项后关闭菜单
  navLinks.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', function(){
      closeMenu();
    });
  });

  // 点击抽屉外面（包括遮罩）关闭菜单
  document.addEventListener('click', (e)=>{
    if (!navLinks.classList.contains('open')) return;
    var searchToggleButton = document.getElementById('searchToggle');
    var insideMenu = navPanel.contains(e.target) || hamburger.contains(e.target) ||
      (searchToggleButton && searchToggleButton.contains(e.target)) ||
      (searchForm && searchForm.contains(e.target));
    if (!insideMenu) closeMenu();
  });

  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape' && navLinks.classList.contains('open')){
      e.preventDefault();
      closeMenu();
      hamburger.focus();
    }
  });
}

// ==================== 桌面下拉菜单键盘操作 ====================
(function initDropdownKeyboard(){
  document.querySelectorAll('.nav-dropdown').forEach(function(dropdown, index){
    var toggle = dropdown.querySelector(':scope > .nav-dropdown-toggle');
    var menu = dropdown.querySelector(':scope > .nav-dropdown-menu');
    if(!toggle || !menu) return;

    if(!menu.id) menu.id = 'navDropdownMenu' + index;
    toggle.setAttribute('aria-controls', menu.id);
    toggle.setAttribute('aria-expanded', 'false');

    function isDesktop(){
      return window.matchMedia('(min-width:961px)').matches;
    }

    function setOpen(open){
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    dropdown.addEventListener('focusin', function(){
      if(isDesktop() && !dropdown.classList.contains('keyboard-closed')) setOpen(true);
    });

    dropdown.addEventListener('focusout', function(){
      setTimeout(function(){
        if(!dropdown.contains(document.activeElement)){
          dropdown.classList.remove('keyboard-closed');
          setOpen(false);
        }
      }, 0);
    });

    toggle.addEventListener('keydown', function(event){
      if(!isDesktop() || event.key !== 'ArrowDown') return;
      event.preventDefault();
      dropdown.classList.remove('keyboard-closed');
      setOpen(true);
      var firstItem = menu.querySelector('a,button');
      if(firstItem) firstItem.focus();
    });

    dropdown.addEventListener('keydown', function(event){
      if(!isDesktop() || event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      dropdown.classList.add('keyboard-closed');
      setOpen(false);
      toggle.focus();
    });
  });
})();


// ==================== 顶部导航按实际宽度自动收纳 ====================
// 登录后右侧多了通知、用户名、后台入口，英文菜单也更长，固定断点挡不住重叠。
// 这里按真实宽度逐级收纳：1 级把次要入口收进“更多”，2 级压缩用户名和搜索框，
// 3 级把赛果/赛事/论坛也收进“更多”，4 级把搜索框收成放大镜按钮。
// 窄屏（≤960px）顶栏用抽屉菜单，只量顶栏上那几个常用入口：放不下的整个藏起来，不露半截。
(function() {
  var navbar = document.querySelector('.navbar');
  var navLinks = document.getElementById('navLinks');
  var navInner = navbar && navbar.querySelector('.nav-inner');
  if (!navbar || !navLinks || !navInner) return;
  var navQuick = navbar.querySelector('.nav-quick');
  var LEVEL_CLASSES = ['nav-fit-1', 'nav-fit-2', 'nav-fit-3', 'nav-fit-4'];
  var pending = false;

  function navOverflows() {
    return navLinks.scrollWidth > navLinks.clientWidth + 1 ||
      navInner.scrollWidth > navInner.clientWidth + 1;
  }

  function applyLevel(level) {
    LEVEL_CLASSES.forEach(function(name, index) {
      navbar.classList.toggle(name, index < level);
    });
  }

  // 窄屏顶栏的常用入口：先全部显示，放不下就从最后一个开始藏（抽屉菜单里都有）
  function fitQuickLinks() {
    if (!navQuick) return;
    var links = Array.prototype.slice.call(navQuick.querySelectorAll('a'));
    links.forEach(function(link) { link.hidden = false; });
    for (var i = links.length - 1; i > 0 && navQuick.scrollWidth > navQuick.clientWidth + 1; i -= 1) {
      links[i].hidden = true;
    }
  }

  function fitNav() {
    pending = false;
    if (window.matchMedia('(max-width:960px)').matches) {
      applyLevel(0);
      fitQuickLinks();
      return;
    }
    var level = 0;
    applyLevel(level);
    while (navOverflows() && level < LEVEL_CLASSES.length) {
      level += 1;
      applyLevel(level);
    }
  }

  function scheduleFit() {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(fitNav);
  }

  fitNav();
  window.addEventListener('resize', scheduleFit);
  window.addEventListener('load', scheduleFit);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(scheduleFit);
})();
