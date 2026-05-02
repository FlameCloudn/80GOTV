// ==================== 主题切换 ====================
const root = document.documentElement;
const themeToggle = document.getElementById('themeToggle');

if(themeToggle){
  themeToggle.addEventListener('click', ()=>{
    const current = root.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  });
}

// ==================== 移动端汉堡菜单 ====================
const hamburger = document.getElementById('hamburger');
const navLinks = document.getElementById('navLinks');

if(hamburger && navLinks){
  hamburger.addEventListener('click', ()=>{
    navLinks.classList.toggle('open');
  });
  
  // 点击菜单项后关闭菜单
  navLinks.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', ()=>{
      navLinks.classList.remove('open');
    });
  });
  
  // 点击外部关闭菜单
  document.addEventListener('click', (e)=>{
    if(!hamburger.contains(e.target) && !navLinks.contains(e.target)){
      navLinks.classList.remove('open');
    }
  });
}