type FadeOptions = {
  duration?: number;
  target?: number;
  resetAfter?: boolean;
};

const clamp = (value: number) => Math.max(0, Math.min(1, value));

export const fadeInAudio = (
  audio: HTMLAudioElement,
  { duration = 1500, target = 0.72 }: FadeOptions = {}
) => {
  let frame = 0;
  const startedAt = performance.now();
  audio.pause();
  audio.currentTime = 0;
  audio.volume = 0;
  void audio.play().catch(() => undefined);

  const tick = (now: number) => {
    const progress = clamp((now - startedAt) / duration);
    audio.volume = clamp(target * progress);
    if (progress < 1) frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
};

export const fadeOutAudio = (
  audio: HTMLAudioElement,
  { duration = 1300, resetAfter = true }: FadeOptions = {}
) => {
  let frame = 0;
  const startedAt = performance.now();
  const startVolume = audio.volume;

  const tick = (now: number) => {
    const progress = clamp((now - startedAt) / duration);
    audio.volume = clamp(startVolume * (1 - progress));
    if (progress < 1) {
      frame = requestAnimationFrame(tick);
      return;
    }
    audio.pause();
    if (resetAfter) audio.currentTime = 0;
  };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
};
