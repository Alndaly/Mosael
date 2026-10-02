import { RangeReader, byteSpan, readTrackIndex, sampleIndexAt, type TrackIndex } from "./mp4Index";

/**
 * 一份素材的音频代理(AAC 48k 立体声,faststart —— 见后端 media/proxy.py)按块解码。
 *
 * 此前预览混音器下的是**整份原文件**,`decodeAudioData` 一口气全解:一小时的 WAV 要下几百 MB、解出
 * 一点几 GB 的 PCM 常驻;解码一失败,40ms 后又整份重下一遍(无声的 AI 视频就是这样被无限重下的)。
 *
 * 现在:样本表按 Range 读一次;时间轴切成 {@link AUDIO_CHUNK_SEC} 秒一块,要播哪块才取那几个 AAC 帧的
 * 字节、用 WebCodecs 的 AudioDecoder 解成 PCM;用不到的块由混音器随时放掉。读不出样本表、解码器不认
 * 这个格式、某块解坏了 —— 都把整份记成 `ok = false`,混音器据此不再碰它,而不是每拍重试。
 */

/** 一块多长(秒)。48k 立体声一块 1.5MB:够大,调度的接缝少;够小,只解眼前要的。 */
export const AUDIO_CHUNK_SEC = 4;
/**
 * 每块往前多解几个 AAC 帧再丢掉:AAC 是重叠变换,一帧要靠前一帧才能还原 —— 从块头直接解,第一帧是
 * 坏的,块与块的接缝上就是一声「咔」。多解两帧(约 43ms)把它垫过去。
 */
const PREROLL_FRAMES = 2;

export interface PcmChunk {
  index: number;
  /** 这一块在素材里的起点(秒)= index × AUDIO_CHUNK_SEC。 */
  start: number;
  sampleRate: number;
  /** 平面 PCM,每声道一条;长度 = frames。素材末尾那一块比整块短。 */
  channels: Float32Array[];
  frames: number;
}

/** 解码器的最小接口 —— 测试里换成假的,真实环境是 WebCodecs 的 AudioDecoder。 */
export interface ChunkDecoder {
  decode(chunk: EncodedAudioChunk): void;
  flush(): Promise<void>;
  close(): void;
}
export type DecoderFactory = (
  config: AudioDecoderConfig,
  onOutput: (data: AudioData) => void,
  onError: (error: unknown) => void,
) => ChunkDecoder | null;

const webCodecsDecoder: DecoderFactory = (config, onOutput, onError) => {
  if (typeof AudioDecoder === "undefined") return null;
  const decoder = new AudioDecoder({ output: onOutput, error: onError });
  decoder.configure(config);
  return decoder;
};

export class AudioProxySource {
  private readonly reader: RangeReader;
  private index: TrackIndex | null = null;
  private failedFlag = false;
  private closed = false;
  private readonly chunks = new Map<number, PcmChunk>();
  private readonly pending = new Set<number>();
  /** 一次只解一块:解码吃 CPU,排队比并发更快拿到眼前那一块。 */
  private queue: Promise<void> = Promise.resolve();
  readonly ready: Promise<void>;

  constructor(
    url: string,
    private readonly decoderFactory: DecoderFactory = webCodecsDecoder,
  ) {
    this.reader = new RangeReader(url);
    this.ready = this.load();
  }

  private async load(): Promise<void> {
    try {
      this.index = await readTrackIndex(this.reader, "audio");
    } catch {
      this.failedFlag = true;
    }
  }

  /** false = 这份代理在这里放不了(读不出、解不了)。记住它,别再每拍重试。 */
  get ok(): boolean {
    return !this.failedFlag;
  }

  /** 素材长度(秒);样本表还没读到时为 0。 */
  get duration(): number {
    const last = this.index?.samples[this.index.samples.length - 1];
    return last ? last.time + last.duration : 0;
  }

  /** 解好的一块;没有就返回 null(调用方 request 之后下一拍再来要)。 */
  chunk(k: number): PcmChunk | null {
    const hit = this.chunks.get(k);
    if (!hit) return null;
    // 重新插入 = 最近用过的排在最后,淘汰时从头开始丢。
    this.chunks.delete(k);
    this.chunks.set(k, hit);
    return hit;
  }

  /** 要第 k 块:没解过、没在解,就排进解码队列。 */
  request(k: number): void {
    if (k < 0 || this.closed || this.failedFlag || this.chunks.has(k) || this.pending.has(k)) return;
    this.pending.add(k);
    this.queue = this.queue
      .then(() => this.ready)
      .then(() => (this.closed || this.failedFlag ? undefined : this.decodeChunk(k)))
      .catch(() => {
        this.failedFlag = true;
      })
      .finally(() => this.pending.delete(k));
  }

  /** 解好的块占的字节。 */
  get retainedBytes(): number {
    let total = this.reader.retainedBytes;
    for (const chunk of this.chunks.values()) total += chunk.frames * chunk.channels.length * 4;
    return total;
  }

  /** 只留 keep 里的块,外加最近用过的 spare 块(倒回去一点不用重解);其余放掉。 */
  retain(keep: ReadonlySet<number>, spare: number): void {
    let allowance = spare;
    for (const k of [...this.chunks.keys()].reverse()) {
      if (keep.has(k)) continue;
      if (allowance > 0) {
        allowance -= 1;
        continue;
      }
      this.chunks.delete(k);
    }
  }

  close(): void {
    this.closed = true;
    this.chunks.clear();
    this.index = null;
  }

  private async decodeChunk(k: number): Promise<void> {
    const index = this.index;
    if (!index || index.samples.length === 0) return;
    const samples = index.samples;
    const start = k * AUDIO_CHUNK_SEC;
    const end = start + AUDIO_CHUNK_SEC;
    const sampleRate = index.sampleRate;
    const total = Math.max(0, Math.round((Math.min(end, this.duration) - start) * sampleRate));
    const channelCount = Math.max(1, index.channels);
    const channels = Array.from({ length: channelCount }, () => new Float32Array(total));
    if (total > 0) {
      const first = Math.max(0, sampleIndexAt(samples, start) - PREROLL_FRAMES);
      const last = sampleIndexAt(samples, end);
      const span = byteSpan(samples, first, last);
      const bytes = await this.reader.read(span.start, span.end);
      let failure: unknown = null;
      const outputs: AudioData[] = [];
      const decoder = this.decoderFactory(
        { codec: index.codec, sampleRate, numberOfChannels: channelCount, description: index.description },
        (data) => outputs.push(data),
        (error) => {
          failure = error;
        },
      );
      if (!decoder) throw new Error("AudioDecoder unavailable");
      try {
        for (let i = first; i <= last; i++) {
          const sample = samples[i];
          const from = sample.offset - span.start;
          decoder.decode(
            new EncodedAudioChunk({
              type: "key",
              timestamp: Math.round(sample.time * 1_000_000),
              duration: Math.round(sample.duration * 1_000_000),
              data: bytes.subarray(from, from + sample.size),
            }),
          );
        }
        await decoder.flush();
      } finally {
        decoder.close();
      }
      if (failure) throw failure instanceof Error ? failure : new Error(String(failure));
      // 按时间戳把每段输出摆到块里的位置:预解的那几帧落在块头之前,自然被切掉。
      for (const data of outputs) {
        const at = Math.round((data.timestamp / 1_000_000 - start) * sampleRate);
        const frames = data.numberOfFrames;
        const from = Math.max(0, -at);
        const to = Math.min(frames, total - at);
        if (to > from) {
          const plane = new Float32Array(frames);
          for (let c = 0; c < channelCount; c++) {
            data.copyTo(plane, { planeIndex: Math.min(c, data.numberOfChannels - 1), format: "f32-planar" });
            channels[c].set(plane.subarray(from, to), at + from);
          }
        }
        data.close();
      }
    }
    if (this.closed) return;
    this.chunks.set(k, { index: k, start, sampleRate, channels, frames: total });
  }
}
