const stream = document.querySelector('[data-stream-url]');

stream?.querySelector('button').addEventListener('click', () => {
  const player = document.createElement('iframe');
  player.src = stream.dataset.streamUrl;
  player.allow = 'autoplay; picture-in-picture';
  player.allowFullscreen = true;
  stream.replaceChildren(player);
}, { once: true });
