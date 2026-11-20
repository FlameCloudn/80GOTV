// ==================== 对阵图弹窗点击切换 ====================
// 窄屏上对阵图放在能左右滑动的框里，弹窗留在卡片里会被框切掉：
// 这时把弹窗临时挪到页面最外层、显示在屏幕中间，关掉时再放回原来的卡片。
function closeBracketPopups() {
  document.querySelectorAll('.bracket-card.popup-open').forEach(function(c) {
    c.classList.remove('popup-open');
  });
  document.querySelectorAll('.bracket-match-popup--floating').forEach(function(popup) {
    popup.classList.remove('bracket-match-popup--floating');
    if (popup.homeCard) popup.homeCard.appendChild(popup);
  });
}

document.addEventListener('keydown', function(e) {
  if (e.key !== 'Escape') return;
  closeBracketPopups();
});

function bracketScrolls(card) {
  var box = card.closest('.bracket-container');
  return !!box && box.scrollWidth > box.clientWidth + 1;
}

document.addEventListener('click', function(e) {
  const missingMatch = e.target.closest('[data-missing-match]');
  if (missingMatch) {
    window.showToast(missingMatch.dataset.missingMatch, 'error');
    return;
  }
  if (e.target.closest('.bracket-match-popup')) return; // 点浮层里面（看阵容、点链接）不关闭
  var card = e.target.closest('.bracket-card');
  var wasOpen = !!card && card.classList.contains('popup-open');
  closeBracketPopups();
  if (!card || wasOpen) return;
  card.classList.add('popup-open');
  var popup = card.querySelector('.bracket-match-popup');
  if (popup && bracketScrolls(card)) {
    popup.homeCard = card;
    popup.classList.add('bracket-match-popup--floating');
    document.body.appendChild(popup);
  }
});
