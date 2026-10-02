import { useEditorStore } from "@/features/editor/editorStore";

/**
 * 播放中「此刻」的播放头,按音频时钟插值。
 *
 * 主时钟是 WebAudioMixer 的 AudioContext,而它每 40ms 才往 store 写一次播放头 —— 画面若直接读 store,
 * 就被钉成 25fps 的阶梯(60Hz 屏上每帧停 2~3 个刷新,平移镜头一顿一顿)。这里让混音器登记一个时钟函数,
 * 画面(合成器的 rAF、时间线上的播放头竖线)每帧问它要连续的时间;store 仍按混音器的节拍同步,只喂给
 * 「当前是哪一句 / 哪几段在场」这类低频派生值。
 *
 * 没在播放、或没有混音器(环境不支持 WebAudio)时,就是 store 里的那个值。
 */
type Clock = () => number;

let clock: Clock | null = null;

/** 混音器挂载时登记、卸载时传 null。同一时刻只有一个混音器(监视器里那一个)。 */
export function setPlaybackClock(next: Clock | null): void {
  clock = next;
}

export function livePlayhead(): number {
  const { playing, playhead } = useEditorStore.getState();
  if (!playing || !clock) return playhead;
  const value = clock();
  return Number.isFinite(value) ? value : playhead;
}
