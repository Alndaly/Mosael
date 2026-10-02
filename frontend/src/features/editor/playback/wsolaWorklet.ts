/**
 * AudioWorklet 处理器:一个变速片段的声部。主线程按顺序把这一段的 PCM 块推进来(port 消息),
 * 处理器用 WSOLA 按 tempo 变速不变调地往外放(与导出的 atempo 同类算法,见 wsola.ts)。
 *
 * 由 Vite 以 `?worker&url` 单独打包成一个文件,`audioWorklet.addModule` 加载(见 stretchWorklet.ts)。
 * 跑在 AudioWorkletGlobalScope 里:没有 window,只有 sampleRate / currentFrame / registerProcessor。
 */
import { WSOLA_PROCESSOR, WsolaStretcher, type WsolaMessage } from "./wsola";

declare const sampleRate: number;
declare const currentFrame: number;
declare function registerProcessor(name: string, processor: unknown): void;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
  constructor(options?: unknown);
}

class WsolaProcessor extends AudioWorkletProcessor {
  private readonly stretcher: WsolaStretcher;
  private startFrame = Number.POSITIVE_INFINITY;
  private stopped = false;

  constructor(options: { processorOptions: { channels: number; tempo: number } }) {
    super(options);
    const { channels, tempo } = options.processorOptions;
    this.stretcher = new WsolaStretcher(channels, sampleRate);
    this.stretcher.tempo = tempo;
    this.port.onmessage = (event: MessageEvent<WsolaMessage>) => {
      const message = event.data;
      if (message.type === "push") this.stretcher.push(message.channels);
      else if (message.type === "start") this.startFrame = message.frame;
      else if (message.type === "end") this.stretcher.end();
      else this.stopped = true;
    };
  }

  process(_inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    if (this.stopped) return false;
    const out = outputs[0];
    const frames = out[0]?.length ?? 0;
    if (currentFrame + frames <= this.startFrame) return true; // 还没到起点:静音
    const offset = Math.max(0, this.startFrame - currentFrame);
    this.stretcher.pull(out, frames - offset, offset); // 输入暂缺时少写的部分保持静音
    return !this.stretcher.drained;
  }
}

registerProcessor(WSOLA_PROCESSOR, WsolaProcessor);
