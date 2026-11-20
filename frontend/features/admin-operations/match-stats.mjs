function switchTab(idx) {
  document.querySelectorAll('.tab-btn').forEach(function (btn, i) {
    btn.classList.toggle('active', i === idx);
  });
  document.querySelectorAll('.tab-content').forEach(function (panel, i) {
    panel.classList.toggle('active', i === idx);
  });
}

document.querySelectorAll('[data-match-stat-tab]').forEach((button) => {
  button.addEventListener('click', () => switchTab(Number(button.dataset.matchStatTab)));
});
