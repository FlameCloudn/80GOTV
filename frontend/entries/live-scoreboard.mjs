import { mountScoreboard } from '../features/live-scoreboard/scoreboard.mjs';

const root = document.getElementById('data-live');
const board = mountScoreboard(root);
let timer;
let request;
let active = true;

function schedule(delay) {
  clearTimeout(timer);
  if (active) timer = setTimeout(poll, delay);
}

async function poll() {
  if (!active || request) return;
  const controller = new AbortController();
  request = controller;
  try {
    const response = await fetch(root.dataset.liveUrl, { cache: 'no-store', signal: controller.signal });
    const data = await response.json();
    if (controller.signal.aborted) return;
    if (data.ok) {
      board.render(data);
    } else if (data.reason === 'map_run_void') {
      board.clearLiveForVoid();
    } else {
      board.markLiveUnavailable('直播数据中断，保留最后一次成功数据');
    }
  } catch (error) {
    if (!controller.signal.aborted) {
      console.error('Live fetch error:', error);
      board.markLiveUnavailable('直播请求失败，保留最后一次成功数据');
    }
  } finally {
    request = null;
    schedule(document.hidden ? 3000 : 1000);
  }
}

document.addEventListener('visibilitychange', () => schedule(document.hidden ? 3000 : 50));
window.addEventListener('pagehide', () => {
  active = false;
  clearTimeout(timer);
  request?.abort();
});
window.addEventListener('pageshow', () => {
  if (active) return;
  active = true;
  schedule(50);
});

poll();
