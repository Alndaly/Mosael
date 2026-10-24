/**
 * 录音时的**实时输入音量**(0..1),给说话输入那颗按钮上的电平条用。
 *
 * 为什么需要它:录音一旦开始,界面上只剩「■ 3s」和一颗停止 —— 用户**看不到自己有没有出声**。
 * 麦克风选错、静音、离太远、系统把输入调成 0,这几种在界面上长得一模一样,而它们的解法各不相同
 * (换设备 / 解除静音 / 靠近 / 调系统音量)。没有电平,用户只能"录完发现识别不出来"再猜。
 *
 * 三件事是刻意的:
 * · **只要值,不要波形**:界面上是一条 3 格的小电平,不是示波器;
 * · **按 dB 映射,不按线性振幅**:人耳是对数的,线性映射会让正常说话一直贴着满格;
 * · **衰减比上升慢**:说话的间隙电平不该立刻掉到 0(那看起来像"断了"),所以有 hold + 缓降。
 *
 * 没有 `AudioContext`(jsdom、或者浏览器策略不允许)时**返回 0 而不是抛错** —— 电平条是锦上添花,
 * 不该因为它让录音这条路挂掉。
 */

import * as React from "react";

/** 采样窗口:512 个时域样本 ≈ 10ms @48k,足够算 RMS,又不至于让每帧都做一次大拷贝。 */
const FFT_SIZE = 512;
/** 界面上电平时每秒刷新的次数:再快人眼也看不出,只是白烧 CPU。 */
const FRAMES_PER_SECOND = 15;
/** 低于这个 dB 就当"没有声音";再往下是底噪。 */
const FLOOR_DB = -60;
/** 缓降:每帧最多掉这么多,间隙里电平不会瞬间归零。 */
const DECAY_PER_FRAME = 0.08;

type AudioContextCtor = typeof AudioContext;

function audioContextCtor(): AudioContextCtor | null {
  if (typeof window === "undefined") return null;
  const global = window as unknown as { AudioContext?: AudioContextCtor; webkitAudioContext?: AudioContextCtor };
  return global.AudioContext ?? global.webkitAudioContext ?? null;
}

/**
 * 把 RMS 换成 0..1:先转 dB,再按 FLOOR_DB..0 线性铺开。
 * 说话的正常音量大概落在 0.45~0.8,喊话才会常常贴满。
 */
export function levelFromSamples(samples: Float32Array): number {
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const value = samples[index];
    sum += value * value;
  }
  const rms = Math.sqrt(sum / Math.max(1, samples.length));
  if (rms <= 0) return 0;
  const db = 20 * Math.log10(rms);
  const normalized = (db - FLOOR_DB) / -FLOOR_DB;
  return Math.min(1, Math.max(0, normalized));
}

/**
 * @param stream 正在录的那条流;`null` 表示没在录(电平会归 0 并停止采样)。
 * @returns 0..1 的电平,约每秒更新 `FRAMES_PER_SECOND` 次。
 */
export function useMicLevel(stream: MediaStream | null): number {
  const [level, setLevel] = React.useState(0);

  React.useEffect(() => {
    if (!stream) {
      setLevel(0);
      return;
    }
    const Ctor = audioContextCtor();
    if (!Ctor) {
      setLevel(0);
      return;
    }

    let context: AudioContext | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let analyser: AnalyserNode | null = null;
    let frame = 0;
    let cancelled = false;
    let lastPaint = 0;

    try {
      context = new Ctor();
      source = context.createMediaStreamSource(stream);
      analyser = context.createAnalyser();
      analyser.fftSize = FFT_SIZE;
      analyser.smoothingTimeConstant = 0;
      source.connect(analyser);
    } catch {
      //: 拿不到分析节点不该影响录音本身 —— 电平条只是少了,录音照走。
      context?.close().catch(() => undefined);
      setLevel(0);
      return;
    }

    //: 浏览器策略要求音频上下文在用户手势之后才 running;录音本来就是在点击之后发生的,
    //: 这里只是把它显式唤醒(resume 在已 running 时是 no-op)。
    void context.resume().catch(() => undefined);

    const samples = new Float32Array(analyser.fftSize);
    let shown = 0;
    const tick = (now: number) => {
      if (cancelled) return;
      frame = window.requestAnimationFrame(tick);
      if (now - lastPaint < 1000 / FRAMES_PER_SECOND) return;
      lastPaint = now;
      analyser?.getFloatTimeDomainData(samples);
      const next = levelFromSamples(samples);
      //: 上升立刻跟上(开口就有反馈),下降缓一点(换气不等于断了)。
      shown = next >= shown ? next : Math.max(next, shown - DECAY_PER_FRAME);
      setLevel(shown);
    };
    frame = window.requestAnimationFrame(tick);

    return () => {
      cancelled = true;
      if (frame) window.cancelAnimationFrame(frame);
      try {
        source?.disconnect();
        analyser?.disconnect();
      } catch {
        //: 节点已经跟着上下文关掉了 —— 断开失败无所谓。
      }
      void context?.close().catch(() => undefined);
      setLevel(0);
    };
  }, [stream]);

  return level;
}
