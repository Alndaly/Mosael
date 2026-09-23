/**
 * 拖进度条时的跳转:**只跳到最新的那个位置**,不把沿途每个像素都跳一遍。
 *
 * 指针每移动一下就设一次 `currentTime`,一次拖动就是几十次跳转。每次跳转浏览器都要重新
 * 取数据、从上一个关键帧解码到目标帧 —— 普通视频几十毫秒,Retina 录屏(3456×2234@120fps)
 * 要 0.3–0.6 秒。于是拖动时画面冻住,松手后还要等那一串跳转挨个过完才停到松手的位置。
 *
 * 做法:上一次跳转还没落地(`seeking`)时只记下目标;落地(`seeked`)后直接跳到**最新**
 * 的目标。中间那些位置不再解码。
 */
const pending = new WeakMap<HTMLMediaElement, number>();

export function seekTo(element: HTMLMediaElement, time: number): void {
  if (!element.seeking) {
    element.currentTime = time;
    return;
  }
  const waiting = pending.has(element);
  pending.set(element, time);
  if (waiting) return;
  element.addEventListener(
    "seeked",
    () => {
      const next = pending.get(element);
      pending.delete(element);
      if (next !== undefined && next !== element.currentTime) seekTo(element, next);
    },
    { once: true },
  );
}
