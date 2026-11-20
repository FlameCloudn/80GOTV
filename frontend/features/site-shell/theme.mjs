import { message as siteMessage } from '../../shared/i18n.js';
// ==================== 主题切换 ====================
const root = document.documentElement;
const themeToggle = document.getElementById('themeToggle');

function updateThemeIcon(t){
  if (!themeToggle) return;
  themeToggle.setAttribute('aria-label', t === 'dark' ? siteMessage('client.theme.switch_to_light_mode') : siteMessage('client.theme.switch_to_dark_mode'));
}
if(themeToggle){
  updateThemeIcon(root.getAttribute('data-theme') || 'light');
  themeToggle.addEventListener('click', (e)=>{
    e.stopPropagation();
    const current = root.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeIcon(next);
  });
}
