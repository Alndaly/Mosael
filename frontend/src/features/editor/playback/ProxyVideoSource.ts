import { RangeReader, byteSpan, readTrackIndex, sampleIndexAt, type TrackIndex } from "./mp4Index";

/**
 * 画面代理(720p、短 GOP、无 B 帧 —— 见后端 media/proxy.py)的解码,分两层:
 *
 * - {@link ProxyMedia}:**一份素材一个**。样本表只读一次(按 Range 读开头的 moov),样本数据按 GOP 用
 *   Range 取、按字节预算缓存。同一素材的所有片段共用它 —— 此前每个片段各自下载并常驻一整份代理,
 *   长访谈切成几十段就是几十份。
 * - {@link ProxyVideoSource}:一个解码游标(一个 VideoDecoder + 解出来的帧 + 当前位置)。一个游标同一
 *   时刻只能服务一个位置,所以同一素材同时出现在两层(画中画套自己)时要两个游标;但切点两侧的前后
 *   两段可以接力用同一个(见 videoSourcePool)。
 *
 * 没有 B 帧,解码顺序 == 展示顺序(cts == dts),所以 seek 就是「复位,跳到目标之前最近的关键帧,往后解」。
 * 帧按需解、播放头走过就关,内存与片段长度无关。
 */

const MICRO = 1_000_000;
// How many samples past the requested one to keep the decoder fed during playback.
const LOOKAHEAD = 12;
// Cap on buffered (decoded, open) frames — back-pressure so we never balloon memory.
const MAX_FRAMES = 24;
// Drop frames this far behind the playhead (seconds).
const EVICT_BEHIND = 0.4;
/** 往前多取几个 GOP:播放头走到 GOP 末尾时下一个已经在手里,取数据的往返不会卡住解码。 */
const PREFETCH_GOPS = 2;
/** 一份素材缓存多少秒的样本数据 —— 按这份代理自己的码率换算成字节(见 cacheBudget)。 */
const CACHE_SECONDS = 30;
const MIN_CACHE_BYTES = 8 * 1024 * 1024;
const MAX_CACHE_BYTES = 48 * 1024 * 1024;

interface Gop {
  /** GOP 第一个样本(关键帧)与最后一个样本的下标。 */
  first: number;
  last: number;
  /** 这一段在文件里的起始偏移;bytes 覆盖 [start, start + bytes.byteLength)。 */
  start: number;
  bytes: Uint8Array | null;
  loading: boolean;
  lastUsed: number;
}

export class ProxyMedia {
  private readonly reader: RangeReader;
  private index: TrackIndex | null = null;
  private gops: Gop[] = [];
  /** 样本下标 → 所在 GOP 的下标。 */
  private gopOfSample: Uint32Array = new Uint32Array(0);
  private failedFlag = false;
  private closed = false;
  private useClock = 0;
  private cacheBytes = MIN_CACHE_BYTES;
  readonly ready: Promise<void>;

  constructor(url: string) {
    this.reader = new RangeReader(url);
    this.ready = this.load();
  }

  private async load(): Promise<void> {
    try {
      const index = await readTrackIndex(this.reader, "video");
      if (this.closed) return;
      this.index = index;
      this.buildGops(index);
    } catch {
      // 读不到、不是 faststart、没有画面轨:这份代理在这里解不了。轮询的是这个标记,所以 ready 不 reject。
      this.failedFlag = true;
    }
  }

  private buildGops(index: TrackIndex): void {
    const samples = index.samples;
    this.gopOfSample = new Uint32Array(samples.length);
    let total = 0;
    for (let i = 0; i < samples.length; i++) {
      if (samples[i].sync || this.gops.length === 0) {
        this.gops.push({ first: i, last: i, start: 0, bytes: null, loading: false, lastUsed: 0 });
      }
      const gop = this.gops[this.gops.length - 1];
      gop.last = i;
      this.gopOfSample[i] = this.gops.length - 1;
      total += samples[i].size;
    }
    // 缓存预算按这份代理自己的码率换算:码率高的多给字节,低的少给 —— 都是约 CACHE_SECONDS 秒的内容。
    const last = samples[samples.length - 1];
    const seconds = last ? last.time + last.duration : 0;
    const bytesPerSecond = seconds > 0 ? total / seconds : 0;
    this.cacheBytes = Math.max(MIN_CACHE_BYTES, Math.min(MAX_CACHE_BYTES, bytesPerSecond * CACHE_SECONDS));
  }

  get ok(): boolean {
    return !this.failedFlag;
  }
  get track(): TrackIndex | null {
    return this.index;
  }

  /** 此刻占着的字节:缓存的样本数据(服务端不认 Range 时还有整份文件)。闲置池按它记账。 */
  get retainedBytes(): number {
    // 样本表本身也占内存(一小时约十万个样本),按每个样本几十字节估进去。
    let total = this.reader.retainedBytes + (this.index?.samples.length ?? 0) * 64;
    for (const gop of this.gops) total += gop.bytes?.byteLength ?? 0;
    return total;
  }

  /** 第 i 个样本的数据;还没取到就发起读取并返回 null(调用方下一帧再来要)。 */
  sampleData(i: number): Uint8Array | null {
    const index = this.index;
    if (!index || i < 0 || i >= index.samples.length) return null;
    const gopIndex = this.gopOfSample[i];
    const gop = this.gops[gopIndex];
    gop.lastUsed = ++this.useClock;
    for (let ahead = 0; ahead <= PREFETCH_GOPS; ahead++) this.loadGop(gopIndex + ahead);
    if (!gop.bytes) return null;
    const sample = index.samples[i];
    const from = sample.offset - gop.start;
    return gop.bytes.subarray(from, from + sample.size);
  }

  private loadGop(gopIndex: number): void {
    const gop = this.gops[gopIndex];
    const index = this.index;
    if (!gop || !index || gop.bytes || gop.loading || this.closed) return;
    gop.loading = true;
    const span = byteSpan(index.samples, gop.first, gop.last);
    this.reader
      .read(span.start, span.end)
      .then((bytes) => {
        gop.loading = false;
        if (this.closed) return;
        gop.start = span.start;
        gop.bytes = bytes;
        gop.lastUsed = ++this.useClock;
        this.trim();
      })
      .catch(() => {
        gop.loading = false;
        // 一个 GOP 取不到(后端重启、文件被换掉):整份判为解不了,让上层退回去说明原因,而不是黑着。
        this.failedFlag = true;
      });
  }

  /** 超出预算时按最久没用的先丢。正在用的那几个刚被 sampleData 碰过,排在最后。 */
  private trim(): void {
    let total = 0;
    for (const gop of this.gops) total += gop.bytes?.byteLength ?? 0;
    if (total <= this.cacheBytes) return;
    const loaded = this.gops.filter((gop) => gop.bytes).sort((a, b) => a.lastUsed - b.lastUsed);
    for (const gop of loaded) {
      if (total <= this.cacheBytes) break;
      total -= gop.bytes!.byteLength;
      gop.bytes = null;
    }
  }

  /** 闲置时只留样本表:缓存的样本数据丢掉,复活时按需再取。 */
  dropCache(): void {
    for (const gop of this.gops) gop.bytes = null;
  }

  close(): void {
    this.closed = true;
    this.gops = [];
    this.index = null;
  }
}

interface Decoded {
  t: number; // presentation time, seconds
  frame: VideoFrame;
}

export class ProxyVideoSource {
  private decoder: VideoDecoder | null = null;
  private frames: Decoded[] = []; // buffered decoded frames, ascending t
  private decodeCursor = 0; // next sample index to feed the decoder
  private configured = false;
  private closed = false;
  private failed = false;
  // 一帧"上次画过的画面",专门用来填 seek 期间的空窗。向后跳(或跨回已 park 的片段)必须
  // 丢弃整个缓冲从关键帧重解,而解码是异步的 —— 那几个 rAF 里没有任何帧可返回,合成器就
  // 跳过该层、画出黑屏(正向播放不进这条路径,所以只有倒着拖/跨切分边界才闪黑)。
  // 留住最后一帧当兜底:画面停一下,远好过闪黑。
  private held: Decoded | null = null;
  /** 此刻(或上一次)服务的是哪个片段。兜底帧只对同一个片段有意义 —— 换了主人就丢掉,免得新片段
   *  seek 的空窗里闪出上一个片段的画面。 */
  private owner: string | null = null;

  constructor(readonly media: ProxyMedia) {}

  get ownerKey(): string | null {
    return this.owner;
  }

  /** 交给某个片段用。换了主人时兜底帧作废。 */
  assign(clipKey: string): void {
    if (this.owner === clipKey) return;
    this.owner = clipKey;
    this.hold(null);
  }

  /** 片段离场、游标回到素材名下待用:解出来的帧放掉(留一张兜底),解码器留着给下一段接着用。 */
  release(): void {
    if (this.closed) return;
    this.holdNewest();
    for (const f of this.frames) {
      if (f !== this.held) f.frame.close();
    }
    this.frames = [];
  }

  get ok(): boolean {
    return !this.failed && this.media.ok;
  }

  /** 解码器此刻停在哪(秒):下一个要喂的样本的时间。池子据此挑「离目标最近、不用 seek」的游标。 */
  get position(): number {
    const samples = this.media.track?.samples;
    if (!samples || samples.length === 0) return 0;
    return samples[Math.min(this.decodeCursor, samples.length - 1)].time;
  }

  private ensureDecoder(): VideoDecoder | null {
    if (this.configured) return this.decoder;
    const track = this.media.track;
    if (!track) return null;
    if (typeof VideoDecoder === "undefined") {
      this.failed = true;
      return null;
    }
    if (!this.decoder || this.decoder.state === "closed") {
      this.decoder = new VideoDecoder({
        output: (frame) => this.onFrame(frame),
        error: () => {
          // Losing the decoder mid-playback used to leave frameAt returning null forever, which
          // the compositor drew as nothing — a black frame with no explanation. Record it so the
          // caller can say so instead.
          this.failed = true;
        },
      });
    }
    try {
      this.decoder.configure({
        codec: track.codec,
        codedWidth: track.width,
        codedHeight: track.height,
        description: track.description,
        optimizeForLatency: true,
      });
    } catch {
      // An unsupported codec throws here rather than going through the error callback.
      this.failed = true;
      return null;
    }
    this.configured = true;
    return this.decoder;
  }

  private onFrame(frame: VideoFrame): void {
    if (this.closed) {
      frame.close();
      return;
    }
    const t = frame.timestamp / MICRO;
    // Insert keeping ascending order (nearly always an append, no B-frames).
    let i = this.frames.length;
    while (i > 0 && this.frames[i - 1].t > t) i--;
    this.frames.splice(i, 0, { t, frame });
    // Back-pressure: if we somehow overran, close the oldest.
    while (this.frames.length > MAX_FRAMES) this.frames.shift()?.frame.close();
  }

  private nearestKeyframe(idx: number): number {
    const samples = this.media.track!.samples;
    for (let i = idx; i >= 0; i--) if (samples[i].sync) return i;
    return 0;
  }

  /** 喂一个样本;数据还没取到就返回 false(下一帧再来)。 */
  private feed(decoder: VideoDecoder, i: number): boolean {
    const data = this.media.sampleData(i);
    if (!data) return false;
    const s = this.media.track!.samples[i];
    decoder.decode(
      new EncodedVideoChunk({
        type: s.sync ? "key" : "delta",
        timestamp: Math.round(s.time * MICRO),
        duration: Math.round(s.duration * MICRO),
        data,
      }),
    );
    return true;
  }

  /**
   * The decoded frame to display at presentation time `sec`, or null if nothing is
   * decoded yet (the caller repaints on rAF, so a late frame shows on the next tick).
   * Drives on-demand decoding: seeks to the nearest keyframe on a jump, then pumps
   * a few samples ahead of the playhead.
   */
  frameAt(sec: number): VideoFrame | null {
    const track = this.media.track;
    if (!this.ok || !track || track.samples.length === 0) return null;
    const decoder = this.ensureDecoder();
    if (!decoder) return null;
    const samples = track.samples;

    const target = sampleIndexAt(samples, sec);
    const haveTarget = this.frames.some((f) => f.t <= sec + 1e-3 && f.t >= samples[target].time - 1e-3);
    // Reset to a keyframe when we've jumped (backwards, or forward past the buffer).
    if (!haveTarget && (this.decodeCursor > target || this.decodeCursor < this.nearestKeyframe(target))) {
      // reset 而不是 flush:还在解码队列里的旧位置的帧直接作废,不会晚到一步混进新位置的缓冲。
      // reset 之后要重新 configure —— 同一个解码器,不重建。
      try {
        decoder.reset();
      } catch {
        /* closed under us; ensureDecoder will notice next time */
      }
      this.configured = false;
      this.holdNewest();
      for (const f of this.frames) {
        if (f !== this.held) f.frame.close();
      }
      this.frames = [];
      this.decodeCursor = this.nearestKeyframe(target);
      if (!this.ensureDecoder()) return this.held?.frame ?? null;
    }
    // Pump forward: keep the decoder fed a little past the target.
    const limit = Math.min(samples.length - 1, target + LOOKAHEAD);
    while (this.decodeCursor <= limit && decoder.decodeQueueSize < LOOKAHEAD) {
      if (!this.feed(decoder, this.decodeCursor)) break;
      this.decodeCursor++;
    }
    // The frame to show = the NEWEST frame at or before the playhead. frames is ascending
    // in t, so that's the last one with t ≤ sec (found in one pass). Then evict frames we've
    // moved well past — everything before the chosen frame that is > EVICT_BEHIND behind it.
    let bestIdx = -1;
    for (let i = 0; i < this.frames.length; i++) {
      if (this.frames[i].t <= sec + 1e-3) bestIdx = i;
      else break; // ascending — no later frame can qualify
    }
    if (bestIdx >= 0) {
      const bestT = this.frames[bestIdx].t;
      const keep: Decoded[] = [];
      for (let i = 0; i < this.frames.length; i++) {
        if (i < bestIdx && this.frames[i].t < bestT - EVICT_BEHIND) {
          this.frames[i].frame.close();
        } else {
          keep.push(this.frames[i]);
        }
      }
      this.frames = keep;
      this.hold(null); // 真帧到位,兜底帧可以释放了
      return this.frames.find((f) => f.t === bestT)?.frame ?? null;
    }
    // Nothing ≤ sec yet (just seeked, first frame still decoding) — show the earliest
    // available, else the frame we held across the seek, so the canvas never goes blank.
    return this.frames[0]?.frame ?? this.held?.frame ?? null;
  }

  /** 换用(或清空)兜底帧,顺手关掉上一张,避免 seek 反复触发时泄漏 VideoFrame。 */
  private hold(next: Decoded | null): void {
    if (this.held === next) return;
    this.held?.frame.close();
    this.held = next;
  }

  /** 把缓冲里最新的一帧留作兜底。缓冲为空时**保留现有兜底帧**而不是清掉 ——
   *  park 后复活正是"缓冲空但已有兜底"的情形,清掉就等于把黑屏又放回来。 */
  private holdNewest(): void {
    const newest = this.frames[this.frames.length - 1];
    if (newest) this.hold(newest);
  }

  /**
   * Release the decoder and decoded frames (keeping one held frame), but keep the position.
   *
   * An open VideoDecoder plus up to MAX_FRAMES open VideoFrames (~1.4MB each at 720p) per idle
   * cursor is invisible to any byte budget and enough to exhaust the browser's limit on
   * concurrent hardware decoders. frameAt() revives it: ensureDecoder reconfigures, and a
   * decodeCursor of 0 with no buffered frames makes the next call take the seek path.
   */
  park(): void {
    if (this.closed) return;
    // 留一帧兜底:跨回这个片段(倒着拖过任一切分边界)时,复活要先从关键帧重解,
    // 期间没有兜底就会闪黑。一个游标只多留一张帧,代价可控。
    this.holdNewest();
    for (const f of this.frames) {
      if (f !== this.held) f.frame.close();
    }
    this.frames = [];
    if (this.decoder && this.decoder.state !== "closed") {
      try {
        this.decoder.close();
      } catch {
        /* already closing */
      }
    }
    this.decoder = null;
    this.configured = false;
    this.decodeCursor = 0;
  }

  close(): void {
    if (this.closed) return;
    this.park();
    this.closed = true;
    this.hold(null);
  }
}
