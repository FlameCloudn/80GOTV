// ==================== HTML 转义（防 XSS） ====================
var _escapeMap = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
export function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, function(m) { return _escapeMap[m]; });
}
