// ==================== 页面内 Tab 切换 ====================
(function() {
  var tabNavs = Array.from(document.querySelectorAll('[data-profile-tabs], [data-switch-tabs]'));
  if (!tabNavs.length) return;

  function activate(tabNav, targetId) {
    var group = tabNav.getAttribute('data-tab-group') || '';
    var links = Array.from(tabNav.querySelectorAll('[data-tab-target]'));
    var panels = Array.from(document.querySelectorAll('[data-tab-panel]')).filter(function(panel) {
      return (panel.getAttribute('data-tab-group') || '') === group;
    });
    links.forEach(function(link) {
      var active = link.getAttribute('data-tab-target') === targetId;
      link.classList.toggle('active', active);
      link.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panels.forEach(function(panel) {
      var active = panel.getAttribute('data-tab-panel') === targetId;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });
    document.dispatchEvent(new CustomEvent('site:tab-activated', {
      detail: { tab: targetId, group: group }
    }));
  }

  tabNavs.forEach(function(tabNav) {
    var links = Array.from(tabNav.querySelectorAll('[data-tab-target]'));
    if (!links.length) return;
    links.forEach(function(link) {
      link.addEventListener('click', function(e) {
        e.preventDefault();
        var targetId = link.getAttribute('data-tab-target');
        if (targetId) activate(tabNav, targetId);
      });
    });
    var initial = links.find(function(link) {
      return link.classList.contains('active');
    });
    activate(tabNav, (initial && initial.getAttribute('data-tab-target')) || links[0].getAttribute('data-tab-target'));
  });
})();

// 横向可滑动的标签条、字母筛选条：两边还有没露出来的内容时，边缘淡出，提示可以左右滑；
// 打开页面时把当前选中的那一项滑到看得见的位置（只滑这一条，不滚动整页）。
(function bindScrollStrips() {
  var SELECTOR = '.tabs, .player-initial-filter';
  var strips = Array.prototype.slice.call(document.querySelectorAll(SELECTOR));
  if (!strips.length) return;

  // 只多出一点空白（如最后一项的内边距）不算，免得把完整的最后一项也淡掉
  function markEdges(strip) {
    var hidden = strip.scrollWidth - strip.clientWidth;
    var scrollable = hidden > 16;
    strip.classList.toggle('has-more-start', scrollable && strip.scrollLeft > 2);
    strip.classList.toggle('has-more-end', scrollable && strip.scrollLeft < hidden - 2);
  }

  function revealActive(strip) {
    var active = strip.querySelector('.active, [aria-current="page"], [aria-selected="true"]');
    if (!active || strip.scrollWidth <= strip.clientWidth + 2) return;
    var stripBox = strip.getBoundingClientRect();
    var itemBox = active.getBoundingClientRect();
    if (itemBox.left >= stripBox.left && itemBox.right <= stripBox.right) return;
    strip.scrollLeft += itemBox.left - stripBox.left - (stripBox.width - itemBox.width) / 2;
  }

  var pending = false;
  function refreshAll() {
    pending = false;
    strips.forEach(markEdges);
  }

  strips.forEach(function(strip) {
    revealActive(strip);
    markEdges(strip);
    strip.addEventListener('scroll', function() { markEdges(strip); }, { passive: true });
  });
  window.addEventListener('resize', function() {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(refreshAll);
  });
  window.addEventListener('load', refreshAll);
})();
