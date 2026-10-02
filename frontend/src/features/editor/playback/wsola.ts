/**
 * WSOLA(Waveform Similarity Overlap-Add)变速不变调,流式。
 *
 * 预览里变速片段此前是把 AudioBufferSourceNode 的 playbackRate 调成速度 —— 2 倍速听起来是花栗鼠,
 * 而导出走 ffmpeg 的 atempo(变速不变调),预览和成片对不上。这里是 atempo 同类的算法:
 *
 * 输出按固定步长 Hs 一帧一帧叠出来(帧长 N = 2·Hs,Hann 窗,50% 重叠的窗加起来恒为 1);每一帧从输入里
 * 取一段,取的位置按 Ha = Hs × tempo 往前走 —— 输入走得比输出快(或慢),时长就变了。为了不在接缝处
 * 撕开波形(那会是一串「嗡嗡」的相位噪声),每一帧的取样位置在名义位置附近 ±Δ 里挑一个,让它的开头和
 * 「上一帧自然往后接的那一段」最像(互相关最大)—— 周期性的声音(人声的基频)于是被整周期地拼接,
 * 音高不变。
 *
 * 跑在 AudioWorklet 里(wsolaWorklet.ts);这里不碰任何 Web Audio 接口,单测直接喂正弦波验证音高。
 */

/** AudioWorklet 处理器的注册名(处理器在 wsolaWorklet.ts,主线程在 stretchWorklet.ts 建节点)。 */
export const WSOLA_PROCESSOR = "mosael-wsola";

/** 主线程 → 处理器的消息。 */
export type WsolaMessage =
  | { type: "push"; channels: Float32Array[] }
  /** 从上下文的第几帧开始出声(之前输出静音):声部的起点按上下文时间精确对齐。 */
  | { type: "start"; frame: number }
  /** 这一段的输入推完了:放完剩下的就结束。 */
  | { type: "end" }
  /** 立刻停(seek、片段被删)。 */
  | { type: "stop" };

/** 帧长约 30ms:比人声的基频周期长几倍(能找到对齐),又短到听不出「回声」。 */
const FRAME_SEC = 0.03;
/** 互相关粗搜时的采样步长与位移步长:先粗后细,省掉九成多的乘加。 */
const COARSE_SAMPLE_STEP = 4;
const COARSE_SHIFT_STEP = 2;

export class WsolaStretcher {
  readonly frame: number;
  readonly hop: number;
  readonly tolerance: number;
  private readonly window: Float32Array;
  private tempoValue = 1;

  /** 输入:每声道一条,覆盖绝对输入位置 [inputStart, inputStart + 长度)。 */
  private input: Float32Array[];
  private inputStart = 0;
  private inputLength = 0;
  /** 下一帧的名义输入位置(绝对,可带小数)。 */
  private analysis = 0;
  /** 上一帧实际取样的位置;null = 还没有上一帧(第一帧不搜)。 */
  private previous: number | null = null;
  /** 重叠区:上一帧后半段加窗后的值,等下一帧的前半段叠上来。 */
  private readonly overlap: Float32Array[];
  /** 已经叠完、可以交出去的输出。 */
  private ready: Float32Array[];
  private readyLength = 0;
  private ended = false;

  constructor(
    readonly channels: number,
    sampleRate: number,
  ) {
    this.hop = Math.max(64, Math.round((FRAME_SEC * sampleRate) / 2));
    this.frame = this.hop * 2;
    this.tolerance = Math.round(this.hop / 2);
    this.window = new Float32Array(this.frame);
    // 周期 Hann:相隔半帧的两个窗相加处处等于 1,叠出来的电平不起伏。
    for (let i = 0; i < this.frame; i++) this.window[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / this.frame);
    this.input = Array.from({ length: channels }, () => new Float32Array(this.frame * 8));
    this.overlap = Array.from({ length: channels }, () => new Float32Array(this.hop));
    this.ready = Array.from({ length: channels }, () => new Float32Array(this.hop * 4));
  }

  get tempo(): number {
    return this.tempoValue;
  }
  set tempo(value: number) {
    this.tempoValue = Math.max(0.25, Math.min(4, value));
  }

  /** 接一段输入(每声道一条,等长)。 */
  push(chunk: readonly Float32Array[]): void {
    const length = chunk[0]?.length ?? 0;
    if (length === 0) return;
    this.ensureInputCapacity(this.inputLength + length);
    for (let c = 0; c < this.channels; c++) this.input[c].set(chunk[Math.min(c, chunk.length - 1)], this.inputLength);
    this.inputLength += length;
  }

  /** 输入到头了:剩下的按补零叠完、交完就算放完。 */
  end(): void {
    this.ended = true;
  }

  /** 输入已经用完、输出也交完了。 */
  get drained(): boolean {
    return this.ended && this.readyLength === 0 && this.analysis - this.tolerance >= this.inputStart + this.inputLength;
  }

  /**
   * 往 out 的 [offset, offset + frames) 写输出,返回实际写了几帧。输入不够时少写(调用方补静音)。
   */
  pull(out: Float32Array[], frames: number, offset = 0): number {
    let written = 0;
    while (written < frames) {
      if (this.readyLength === 0 && !this.produceHop()) break;
      const take = Math.min(frames - written, this.readyLength);
      for (let c = 0; c < out.length; c++) {
        const source = this.ready[Math.min(c, this.channels - 1)];
        out[c].set(source.subarray(0, take), offset + written);
      }
      for (let c = 0; c < this.channels; c++) this.ready[c].copyWithin(0, take, this.readyLength);
      this.readyLength -= take;
      written += take;
    }
    return written;
  }

  /** 叠出一个步长的输出;输入还不够就返回 false。 */
  private produceHop(): boolean {
    const nominal = Math.round(this.analysis);
    // 这一帧最远要读到 nominal + Δ + N;上一帧的「自然后续」要读到 previous + Hs + Hs。
    const needEnd = nominal + this.tolerance + this.frame;
    const haveEnd = this.inputStart + this.inputLength;
    if (needEnd > haveEnd && !this.ended) return false;
    if (this.ended && nominal - this.tolerance >= haveEnd) return false;

    const position = this.previous === null ? nominal : this.bestAlignment(nominal);
    this.ensureReadyCapacity(this.readyLength + this.hop);
    for (let c = 0; c < this.channels; c++) {
      const overlap = this.overlap[c];
      const ready = this.ready[c];
      for (let i = 0; i < this.hop; i++) {
        ready[this.readyLength + i] = overlap[i] + this.sample(c, position + i) * this.window[i];
        overlap[i] = this.sample(c, position + this.hop + i) * this.window[this.hop + i];
      }
    }
    this.readyLength += this.hop;
    this.previous = position;
    this.analysis += this.hop * this.tempoValue;
    this.discardConsumedInput();
    return true;
  }

  /** 在 nominal ± Δ 里找和「上一帧自然往后接的那一段」最像的取样位置。先粗搜,再在最好的附近细搜。 */
  private bestAlignment(nominal: number): number {
    const template = this.previous! + this.hop;
    const length = this.hop;
    const score = (shift: number, step: number) => {
      let sum = 0;
      const at = nominal + shift;
      for (let i = 0; i < length; i += step) sum += this.mono(template + i) * this.mono(at + i);
      return sum;
    };
    let best = 0;
    let bestScore = Number.NEGATIVE_INFINITY;
    for (let shift = -this.tolerance; shift <= this.tolerance; shift += COARSE_SHIFT_STEP) {
      const value = score(shift, COARSE_SAMPLE_STEP);
      if (value > bestScore) {
        bestScore = value;
        best = shift;
      }
    }
    let refined = best;
    bestScore = Number.NEGATIVE_INFINITY;
    for (let shift = best - COARSE_SHIFT_STEP; shift <= best + COARSE_SHIFT_STEP; shift++) {
      if (shift < -this.tolerance || shift > this.tolerance) continue;
      const value = score(shift, 1);
      if (value > bestScore) {
        bestScore = value;
        refined = shift;
      }
    }
    return nominal + refined;
  }

  /** 绝对位置的输入采样;缓冲之外(开头之前、结尾之后)当作静音。 */
  private sample(channel: number, at: number): number {
    const i = at - this.inputStart;
    return i >= 0 && i < this.inputLength ? this.input[channel][i] : 0;
  }

  private mono(at: number): number {
    if (this.channels === 1) return this.sample(0, at);
    return (this.sample(0, at) + this.sample(1, at)) * 0.5;
  }

  /** 丢掉以后再也用不到的输入:下一帧最早从 min(名义 − Δ, 上一帧 + Hs) 读起。 */
  private discardConsumedInput(): void {
    const keepFrom = Math.min(Math.round(this.analysis) - this.tolerance, (this.previous ?? 0) + this.hop);
    const drop = Math.min(this.inputLength, Math.max(0, keepFrom - this.inputStart));
    if (drop <= 0) return;
    for (let c = 0; c < this.channels; c++) this.input[c].copyWithin(0, drop, this.inputLength);
    this.inputLength -= drop;
    this.inputStart += drop;
  }

  private ensureInputCapacity(length: number): void {
    if (length <= this.input[0].length) return;
    const size = Math.max(length, this.input[0].length * 2);
    this.input = this.input.map((old) => {
      const grown = new Float32Array(size);
      grown.set(old.subarray(0, this.inputLength));
      return grown;
    });
  }

  private ensureReadyCapacity(length: number): void {
    if (length <= this.ready[0].length) return;
    const size = Math.max(length, this.ready[0].length * 2);
    this.ready = this.ready.map((old) => {
      const grown = new Float32Array(size);
      grown.set(old.subarray(0, this.readyLength));
      return grown;
    });
  }
}
