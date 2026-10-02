import { assetAudioProxyUrl } from "@/api/client";
import { audioGainAt, type AudioSourceSpec } from "./audioMix";
import { AUDIO_CHUNK_SEC, AudioProxySource, type PcmChunk } from "./audioProxySource";
import type { StretchFactory, StretchNode } from "./stretchWorklet";

/**
 * 预览混音的「声部」:每个在播(或马上要播)的有声片段一个,从它素材的音频代理里按块取 PCM,
 * 用 AudioBufferSourceNode 首尾相接地排进 AudioContext 的时间轴。
 *
 * 此前一个片段一个节点、节点里是**整份**解好的素材;现在是按块(AUDIO_CHUNK_SEC)排:只解眼前和前面
 * 几秒,播过的块随时放掉。块与块按同一条「上下文时间 ↔ 媒体时间」直线换算起止,接缝是采样级对齐的。
 *
 * 片段开头不再等到播放头跨进去的那一拍(最多晚 40ms)才起:落在前瞻窗口里的片段提前按精确时间排上。
 *
 * **变速片段(速率 × 速度 ≠ 1)变速不变调**:声部换成一个 AudioWorklet 节点(WSOLA,见 wsola.ts),块按
 * 顺序推给它,而不是把 playbackRate 调成速度 —— 那样 2 倍速是花栗鼠,而导出的 atempo 不变调,预览和
 * 成片对不上。环境加载不了 worklet 时才退回 playbackRate。
 */

/** 节点最多提前排多远(上下文时间,秒)。 */
const SCHEDULE_AHEAD_SEC = 0.5;
/** 往前解多远(播放时间,秒):够盖住解码与取数的往返。 */
const DECODE_AHEAD_SEC = 8;
/** 每份素材在眼前窗口之外再留几块(倒回去一点、暂停后接着播,不用重解)。 */
const SPARE_CHUNKS = 2;
/** 音频代理的采样率(后端固定转成 48k)。上下文不是这个采样率时变速声部不能直接推 PCM,退回 playbackRate。 */
const PROXY_SAMPLE_RATE = 48_000;

export interface MixState {
  playhead: number;
  rate: number;
  volume: number;
  muted: boolean;
}

/** AudioContext 里声部用得到的那几样 —— 测试里换成假的。 */
export type VoiceContext = Pick<BaseAudioContext, "createBuffer" | "createBufferSource" | "createGain" | "sampleRate">;

export type SourceFactory = (assetId: string) => AudioProxySource;

const defaultSourceFactory: SourceFactory = (assetId) => new AudioProxySource(assetAudioProxyUrl(assetId));

interface Voice {
  spec: AudioSourceSpec;
  signature: string;
  source: AudioProxySource;
  gain: GainNode;
  nodes: Set<AudioBufferSourceNode>;
  /** 上下文时间 tAnchor 时播到媒体时间 mAnchor,此后每上下文秒走 tempo 媒体秒。 */
  tAnchor: number;
  mAnchor: number;
  tempo: number;
  /** 这个声部要放的媒体区间 [mStart, mEnd)。 */
  mStart: number;
  mEnd: number;
  /** 下一块要排的块号。 */
  nextChunk: number;
  /** 变速不变调的声部:worklet 节点、已经推到的媒体时间、有没有说过「推完了」。 */
  stretch: { node: StretchNode | null; fedUntil: number; ended: boolean } | null;
}

const clipEnd = (s: AudioSourceSpec) => s.timelineStart + Math.max(0, (s.srcOut - s.srcIn) / (s.speed || 1));

export class AudioVoices {
  private readonly sources = new Map<string, AudioProxySource>();
  private readonly voices = new Map<string, Voice>();
  private readonly buffers = new WeakMap<PcmChunk, AudioBuffer>();
  private stretchFactory: StretchFactory | null = null;

  constructor(
    private readonly ctx: VoiceContext,
    private readonly destination: AudioNode,
    private readonly makeSource: SourceFactory = defaultSourceFactory,
  ) {}

  /**
   * 这一份代理的解码源:按代理指纹缓存。**失败的也留在表里** —— 它的 ok 为 false,下一拍不会再
   * 建一个去重下重解(审查发现无声视频曾被每 40ms 整份重下一遍)。指纹变了(代理重转过)才换新的。
   */
  private sourceFor(spec: AudioSourceSpec): AudioProxySource | null {
    if (!spec.audioProxy) return null;
    let source = this.sources.get(spec.audioProxy);
    if (!source) {
      source = this.makeSource(spec.assetId);
      this.sources.set(spec.audioProxy, source);
    }
    return source.ok ? source : null;
  }

  /** worklet 加载好了:之后新起的变速声部走变速不变调。 */
  enableStretch(factory: StretchFactory): void {
    this.stretchFactory = factory;
  }

  /** 时间线上已经没人用的代理:解码源连同解好的块一起放掉。 */
  private dropUnused(specs: readonly AudioSourceSpec[]): void {
    const used = new Set(specs.map((s) => s.audioProxy).filter(Boolean));
    for (const [key, source] of this.sources) {
      if (used.has(key)) continue;
      source.close();
      this.sources.delete(key);
    }
  }

  /** 播放中的一拍:上下文时间 now 对应播放头 state.playhead。 */
  play(specs: readonly AudioSourceSpec[], now: number, state: MixState): void {
    this.dropUnused(specs);
    const { playhead, rate } = state;
    const horizon = playhead + SCHEDULE_AHEAD_SEC * rate;
    const wanted = new Set<string>();
    for (const spec of specs) {
      if (clipEnd(spec) <= playhead || spec.timelineStart >= horizon) continue;
      const source = this.sourceFor(spec);
      if (!source) continue;
      wanted.add(spec.key);
      const signature = `${spec.audioProxy}|${spec.srcIn}|${spec.srcOut}|${spec.timelineStart}|${spec.speed}|${rate}`;
      let voice = this.voices.get(spec.key);
      if (voice && voice.signature !== signature) {
        this.stopVoice(voice);
        voice = undefined;
      }
      if (!voice) {
        voice = this.startVoice(spec, source, signature, now, state);
        this.voices.set(spec.key, voice);
      }
      voice.spec = spec;
      voice.gain.gain.value = audioGainAt(spec, specs as AudioSourceSpec[], Math.max(playhead, spec.timelineStart), state.volume, state.muted);
      this.schedule(voice, now);
    }
    for (const [key, voice] of this.voices) {
      if (wanted.has(key)) continue;
      this.stopVoice(voice);
      this.voices.delete(key);
    }
    this.retainChunks(specs, playhead);
  }

  /** 暂停时:声部全停;播放头下的那几块先解好,按下播放就有声音。 */
  idle(specs: readonly AudioSourceSpec[], playhead: number): void {
    this.dropUnused(specs);
    this.stopAll();
    for (const spec of specs) {
      if (playhead < spec.timelineStart || playhead >= clipEnd(spec)) continue;
      this.sourceFor(spec)?.request(Math.floor(this.mediaAtPlayhead(spec, playhead) / AUDIO_CHUNK_SEC));
    }
    this.retainChunks(specs, playhead);
  }

  stopAll(): void {
    for (const voice of this.voices.values()) this.stopVoice(voice);
    this.voices.clear();
  }

  close(): void {
    this.stopAll();
    for (const source of this.sources.values()) source.close();
    this.sources.clear();
  }

  private mediaAtPlayhead(spec: AudioSourceSpec, playhead: number): number {
    return spec.srcIn + (playhead - spec.timelineStart) * (spec.speed || 1);
  }

  private startVoice(spec: AudioSourceSpec, source: AudioProxySource, signature: string, now: number, state: MixState): Voice {
    const speed = spec.speed || 1;
    // 片段还没开始(在前瞻窗口里):从它的入点起,按精确的上下文时间排;已经在播:从播放头处起。
    const timelineFrom = Math.max(state.playhead, spec.timelineStart);
    const mStart = spec.srcIn + (timelineFrom - spec.timelineStart) * speed;
    const gain = this.ctx.createGain();
    gain.connect(this.destination);
    const tempo = state.rate * speed;
    const stretched = Math.abs(tempo - 1) > 1e-6 && this.stretchFactory !== null && this.ctx.sampleRate === PROXY_SAMPLE_RATE;
    return {
      spec,
      signature,
      source,
      gain,
      nodes: new Set(),
      tAnchor: now + (timelineFrom - state.playhead) / state.rate,
      mAnchor: mStart,
      tempo,
      mStart,
      mEnd: spec.srcOut,
      nextChunk: Math.floor(mStart / AUDIO_CHUNK_SEC),
      stretch: stretched ? { node: null, fedUntil: mStart, ended: false } : null,
    };
  }

  private ctxAt(voice: Voice, media: number): number {
    return voice.tAnchor + (media - voice.mAnchor) / voice.tempo;
  }

  private mediaAt(voice: Voice, time: number): number {
    return voice.mAnchor + (time - voice.tAnchor) * voice.tempo;
  }

  /** 把块首尾相接地排进上下文时间轴,直到 now + SCHEDULE_AHEAD_SEC;顺手请求往前 DECODE_AHEAD_SEC 的块。 */
  private schedule(voice: Voice, now: number): void {
    const source = voice.source;
    const mNow = Math.max(voice.mStart, this.mediaAt(voice, now));
    const mEnd = Math.min(voice.mEnd, source.duration || voice.mEnd);
    const lastWanted = Math.floor(Math.min(mEnd, mNow + DECODE_AHEAD_SEC * voice.tempo) / AUDIO_CHUNK_SEC);
    for (let k = Math.floor(mNow / AUDIO_CHUNK_SEC); k <= lastWanted; k++) source.request(k);
    if (voice.stretch) {
      this.feedStretch(voice, voice.stretch, now, mEnd);
      return;
    }

    while (true) {
      const k = voice.nextChunk;
      const chunkStart = k * AUDIO_CHUNK_SEC;
      if (chunkStart >= mEnd) break;
      const segEnd = Math.min(chunkStart + AUDIO_CHUNK_SEC, mEnd);
      let segStart = Math.max(chunkStart, voice.mStart);
      if (this.ctxAt(voice, segStart) > now + SCHEDULE_AHEAD_SEC) break;
      const chunk = source.chunk(k);
      if (!chunk) {
        // 还没解出来。整块都已经错过了就跳过它(宁可缺一小段,不能让后面的声音跟画面错开);
        // 否则下一拍再来。
        if (this.ctxAt(voice, segEnd) <= now) {
          voice.nextChunk += 1;
          continue;
        }
        source.request(k);
        break;
      }
      voice.nextChunk += 1;
      // 晚到的块从「此刻」该播的位置接上,而不是从块头补放 —— 那样后面整段都会晚。
      let when = this.ctxAt(voice, segStart);
      if (when < now) {
        segStart = this.mediaAt(voice, now);
        when = now;
      }
      const offset = segStart - chunk.start;
      const duration = Math.min(segEnd, chunk.start + chunk.frames / chunk.sampleRate) - segStart;
      if (duration <= 0 || chunk.frames === 0) continue;
      const node = this.ctx.createBufferSource();
      node.buffer = this.bufferOf(chunk);
      node.playbackRate.value = voice.tempo;
      node.connect(voice.gain);
      node.onended = () => voice.nodes.delete(node);
      node.start(when, offset, duration);
      voice.nodes.add(node);
    }
  }

  /**
   * 变速声部:把块按顺序推给 worklet,推到「上下文时间 now + SCHEDULE_AHEAD_SEC」为止。
   *
   * 节点等第一块解出来才建,起点从「此刻该播的位置」算(和 AudioBufferSource 路径晚到时一样),按上下文
   * 帧号精确开声。之后某块到点还没解出来(罕见:往前 8 秒就在解),推一段等长的静音占住时间 ——
   * worklet 按输入推进,缺了输入整段声音就会比画面晚。
   */
  private feedStretch(voice: Voice, stretch: NonNullable<Voice["stretch"]>, now: number, mEnd: number): void {
    if (!stretch.node) {
      const k = Math.floor(Math.max(stretch.fedUntil, this.mediaAt(voice, now)) / AUDIO_CHUNK_SEC);
      if (!voice.source.chunk(k)) return;
      const from = Math.max(stretch.fedUntil, this.mediaAt(voice, now));
      stretch.fedUntil = from;
      const node = this.stretchFactory!(voice.tempo, 2);
      node.connect(voice.gain);
      node.port.postMessage({ type: "start", frame: Math.round(Math.max(now, this.ctxAt(voice, from)) * this.ctx.sampleRate) });
      stretch.node = node;
    }
    const node = stretch.node;
    while (!stretch.ended) {
      if (stretch.fedUntil >= mEnd - 1e-9) {
        node.port.postMessage({ type: "end" });
        stretch.ended = true;
        break;
      }
      if (this.ctxAt(voice, stretch.fedUntil) > now + SCHEDULE_AHEAD_SEC) break;
      const k = Math.floor(stretch.fedUntil / AUDIO_CHUNK_SEC);
      const segEnd = Math.min((k + 1) * AUDIO_CHUNK_SEC, mEnd);
      const chunk = voice.source.chunk(k);
      let channels: Float32Array[];
      if (chunk) {
        const from = Math.max(0, Math.round((stretch.fedUntil - chunk.start) * chunk.sampleRate));
        const to = Math.min(chunk.frames, Math.round((segEnd - chunk.start) * chunk.sampleRate));
        channels = [0, 1].map((c) => chunk.channels[Math.min(c, chunk.channels.length - 1)].slice(from, Math.max(from, to)));
      } else if (this.ctxAt(voice, stretch.fedUntil) <= now) {
        const frames = Math.round((segEnd - stretch.fedUntil) * PROXY_SAMPLE_RATE);
        channels = [new Float32Array(frames), new Float32Array(frames)];
      } else {
        voice.source.request(k);
        break;
      }
      node.port.postMessage({ type: "push", channels }, channels.map((c) => c.buffer));
      stretch.fedUntil = segEnd;
    }
  }

  private bufferOf(chunk: PcmChunk): AudioBuffer {
    let buffer = this.buffers.get(chunk);
    if (!buffer) {
      buffer = this.ctx.createBuffer(chunk.channels.length, chunk.frames, chunk.sampleRate);
      chunk.channels.forEach((data, channel) => buffer!.copyToChannel(data as Float32Array<ArrayBuffer>, channel));
      this.buffers.set(chunk, buffer);
    }
    return buffer;
  }

  private stopVoice(voice: Voice): void {
    for (const node of voice.nodes) {
      try {
        node.stop();
      } catch {
        /* already stopped */
      }
    }
    voice.nodes.clear();
    if (voice.stretch?.node) {
      voice.stretch.node.port.postMessage({ type: "stop" });
      voice.stretch.node.disconnect();
    }
    voice.gain.disconnect();
  }

  /** 每份代理只留眼前要用的块(在播声部的解码窗口、暂停时播放头下那一块),外加几块备用。 */
  private retainChunks(specs: readonly AudioSourceSpec[], playhead: number): void {
    const keep = new Map<AudioProxySource, Set<number>>();
    const mark = (source: AudioProxySource, from: number, to: number) => {
      const set = keep.get(source) ?? new Set<number>();
      for (let k = Math.floor(from / AUDIO_CHUNK_SEC); k <= Math.floor(to / AUDIO_CHUNK_SEC); k++) set.add(k);
      keep.set(source, set);
    };
    for (const spec of specs) {
      if (playhead < spec.timelineStart || playhead >= clipEnd(spec)) continue;
      const source = spec.audioProxy ? this.sources.get(spec.audioProxy) : undefined;
      if (!source) continue;
      const media = this.mediaAtPlayhead(spec, playhead);
      mark(source, media, media + DECODE_AHEAD_SEC * (spec.speed || 1));
    }
    // 在播的声部(含前瞻窗口里刚排上、播放头还没跨进去的)按它自己的媒体时间留。
    for (const voice of this.voices.values()) {
      const from = Math.max(voice.mStart, this.mediaAtPlayhead(voice.spec, playhead));
      mark(voice.source, from, Math.min(voice.mEnd, from + DECODE_AHEAD_SEC * voice.tempo));
    }
    for (const source of this.sources.values()) source.retain(keep.get(source) ?? new Set(), SPARE_CHUNKS);
  }

  /** 测试与诊断用。 */
  get stats(): { sources: number; voices: number; scheduledNodes: number } {
    let scheduledNodes = 0;
    for (const voice of this.voices.values()) scheduledNodes += voice.nodes.size;
    return { sources: this.sources.size, voices: this.voices.size, scheduledNodes };
  }
}
