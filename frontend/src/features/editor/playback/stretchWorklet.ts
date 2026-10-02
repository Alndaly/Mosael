import { WSOLA_PROCESSOR, type WsolaMessage } from "./wsola";

/** 变速声部的输出节点:一个 AudioWorkletNode(处理器见 wsolaWorklet.ts)。测试里换成假的。 */
export interface StretchNode {
  readonly port: { postMessage(message: WsolaMessage, transfer?: Transferable[]): void };
  connect(destination: AudioNode): unknown;
  disconnect(): void;
}

export type StretchFactory = (tempo: number, channels: number) => StretchNode;

/**
 * 加载 WSOLA 处理器,返回建变速节点的工厂;环境不支持 AudioWorklet、或模块加载失败时返回 null ——
 * 混音器那时退回 playbackRate 变速(会变调,但有声音)。
 *
 * 处理器由 Vite 以 `?worker&url` 单独打包:worklet 只能按 URL 加载模块,不能吃主线程的模块图。
 */
export async function loadStretchFactory(ctx: AudioContext): Promise<StretchFactory | null> {
  if (!ctx.audioWorklet || typeof AudioWorkletNode === "undefined") return null;
  try {
    const { default: url } = await import("./wsolaWorklet?worker&url");
    await ctx.audioWorklet.addModule(url);
  } catch {
    return null;
  }
  return (tempo, channels) =>
    new AudioWorkletNode(ctx, WSOLA_PROCESSOR, {
      numberOfInputs: 0,
      numberOfOutputs: 1,
      outputChannelCount: [channels],
      processorOptions: { channels, tempo },
    });
}
