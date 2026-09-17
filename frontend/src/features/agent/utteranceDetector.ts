/**
 * 把一串音量样本切成「一句话」。
 *
 * **纯逻辑,不碰麦克风** —— 分句判据是这套东西里最容易调错、也最难靠肉眼发现的部分:
 * 阈值高一点就吃掉句首,低一点就被空调声触发;静音等待短一点会把一句话切成三段,长一点
 * 又让人觉得"它没反应"。这些都不会报错,只会让对话变得难用。所以它单独成一个可测的东西,
 * 用合成的能量序列去验,而不是靠对着麦克风试。
 *
 * 判据有四条,每条都在挡一种真实的失败:
 *
 * · **起说阈值高于止说阈值**(滞回)。只有一个阈值的话,音量在它上下抖动时会疯狂切换 ——
 *   一句话被切成一串碎片。
 * · **静音等待**(hangover)。句子中间本来就有停顿(逗号、换气),不等一下就会在每个逗号处
 *   断句。
 * · **最短时长**。咳嗽、键盘、鼠标点击都会顶破阈值;比这个短的一律不算一句话,否则用户
 *   每敲一下键盘就发一次空识别。
 * · **最长时长**。有人会一直说下去,而后端的听写上限是 120 秒 —— 到点先交上去,别让整段被拒。
 *
 * 噪声地板是**跟着环境走的**:阈值写死的话,安静房间里灵敏得离谱,咖啡馆里则完全不触发。
 */

export interface UtteranceOptions {
  /** 高于「地板 × 这个倍数」算开口。 */
  startFactor: number;
  /** 低于「地板 × 这个倍数」算停下。必须小于 startFactor,那就是滞回。 */
  endFactor: number;
  /** 停下之后再等多久才算说完(毫秒)。句中停顿要能扛住。 */
  hangoverMs: number;
  /** 短于这个的不算一句话(毫秒)。 */
  minSpeechMs: number;
  /** 说到这么长就先交上去(毫秒)。 */
  maxUtteranceMs: number;
}

export const DEFAULT_UTTERANCE_OPTIONS: UtteranceOptions = {
  startFactor: 3.5,
  endFactor: 2,
  hangoverMs: 900,
  minSpeechMs: 350,
  //: 后端听写上限是 120 秒(DICTATION_MAX_SECONDS),留一点余量先交。
  maxUtteranceMs: 110_000,
};

export type UtteranceEvent =
  /** 没在说话。 */
  | "idle"
  /** 正在说 —— 打断要用这个信号:它在念的时候你开口了。 */
  | "speaking"
  /** 说完了一句,该交上去识别。 */
  | "ended"
  /** 顶破了阈值但太短 —— 咳嗽、键盘。**不是一句话**,也不该当成沉默。 */
  | "discarded";

export class UtteranceDetector {
  private floor = 0;
  private speaking = false;
  private startedAt = 0;
  private quietSince: number | null = null;
  private seen = 0;

  constructor(private readonly options: UtteranceOptions = DEFAULT_UTTERANCE_OPTIONS) {}

  /** 此刻要多响才算"开口了"。
   *
   * 给可视化用,而不是给判决用 —— 判决在 push 里。浮标把音量画成"相对这条线的高度",
   * 于是那根跳动的条不是装饰:它越过刻度的那一刻,正是检测器认定你在说话的那一刻。
   * 画一个固定量程的话,安静房间里永远是一小截、吵的房间里永远顶格,而两种情况下
   * 用户都会得出同一个结论 —— "它没在听我"。
   */
  get triggerLevel(): number {
    return Math.max(this.floor, 0.005) * this.options.startFactor;
  }

  /** 说到现在多久了(毫秒)。UI 用它显示"正在听"。 */
  get speakingForMs(): number {
    return this.speaking ? this.lastAt - this.startedAt : 0;
  }

  private lastAt = 0;

  /**
   * 喂一个音量样本(RMS,0..1)和它的时刻。返回这一刻的判断。
   *
   * 地板只在**没在说话时**更新 —— 说话中一起更新的话,长句子会把地板一路抬高,
   * 说到后面自己把自己判成静音。
   */
  push(rms: number, atMs: number): UtteranceEvent {
    this.lastAt = atMs;
    this.seen += 1;
    if (!this.speaking) {
      // 慢跟随:一次响动不该把地板顶上去,而环境变了要跟得上。
      this.floor = this.seen === 1 ? rms : this.floor * 0.95 + rms * 0.05;
    }
    // 绝对下限:全静音的房间里地板会趋近 0,那时任何一点底噪都是"地板的几倍"。
    const floor = Math.max(this.floor, 0.005);

    if (!this.speaking) {
      if (rms > floor * this.options.startFactor) {
        this.speaking = true;
        this.startedAt = atMs;
        this.quietSince = null;
        return "speaking";
      }
      return "idle";
    }

    if (rms > floor * this.options.endFactor) {
      this.quietSince = null;
    } else if (this.quietSince === null) {
      this.quietSince = atMs;
    }

    // **算到静下来那一刻,不是算到现在。** 算到现在的话,静音等待那 900ms 也被记成了说话时间
    // —— 一次 100ms 的咳嗽加上等待就成了"说了 1 秒",minSpeechMs 那道闸形同虚设,于是每敲
    // 一下键盘都会发一次空识别上去。
    const spokenMs = (this.quietSince ?? atMs) - this.startedAt;
    const quietLongEnough = this.quietSince !== null && atMs - this.quietSince >= this.options.hangoverMs;
    if (quietLongEnough || spokenMs >= this.options.maxUtteranceMs) {
      this.speaking = false;
      this.quietSince = null;
      // 太短的按"没发生过"处理,但**要和沉默区分开** —— 调用方据此丢掉这段录音而不是交上去。
      return spokenMs >= this.options.minSpeechMs ? "ended" : "discarded";
    }
    return "speaking";
  }

  /** 换一轮重来(切会话、关掉语音模式)。地板留着 —— 环境没变。 */
  reset(): void {
    this.speaking = false;
    this.quietSince = null;
    this.startedAt = 0;
  }
}
