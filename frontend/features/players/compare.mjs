// 下拉框换了人就直接刷新对比，不用再点按钮（没开脚本时才显示“对比”按钮）
document.querySelectorAll('.compare-pick').forEach(function(select) {
  select.addEventListener('change', function() { select.form.submit(); });
});
document.querySelectorAll('.compare-submit').forEach(function(button) { button.hidden = true; });
