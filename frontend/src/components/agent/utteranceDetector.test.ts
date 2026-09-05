/**
 * 分句判据。**用合成的能量序列验,不对着麦克风试** —— 这些错误都不报错,只会让对话难用:
 * 阈值高一点吃掉句首,低一点被空调声触发;等待短一点把一句话切成三段,长一点让人觉得没反应。
 */

import { describe, expect, it } from "vitest";

import { DEFAULT_UTTERANCE_OPTIONS, UtteranceDetector } from "@/components/agent/utteranceDetector";

/** 喂一段等间隔的样本,返回每一步的判断。 */
function feed(detector: UtteranceDetector, samples: number[], stepMs = 100): string[] {
  return samples.map((rms, index) => detector.push(rms, index * stepMs));
}

const QUIET = 0.01;
const LOUD = 0.2;

/** 先给一段底噪,让地板收敛到环境水平 —— 真实场景里麦克风一开就是这样。 */
function settled(options = DEFAULT_UTTERANCE_OPTIONS): UtteranceDetector {
  const detector = new UtteranceDetector(options);
  feed(detector, Array(20).fill(QUIET));
  return detector;
}

describe("分句", () => {
  it("底噪不会被当成有人在说话", () => {
    const events = feed(settled(), Array(30).fill(QUIET), 100);
    expect(new Set(events)).toEqual(new Set(["idle"]));
  });

  it("持续的声音算开口,静下来够久算说完", () => {
    const detector = settled();
    const events = feed(detector, [...Array(8).fill(LOUD), ...Array(12).fill(QUIET)], 100);
    expect(events).toContain("speaking");
    expect(events.filter((one) => one === "ended")).toHaveLength(1);
  });

  it("句子中间的停顿不断句 —— 逗号和换气不是说完了", () => {
    const detector = settled();
    // 说 800ms → 停 400ms(短于 hangover 900ms)→ 再说 800ms → 停够久
    const events = feed(
      detector,
      [...Array(8).fill(LOUD), ...Array(4).fill(QUIET), ...Array(8).fill(LOUD), ...Array(12).fill(QUIET)],
      100,
    );
    // **只切出一句**。切成两句的话,模型会收到半截话,而用户没有察觉自己被打断了。
    expect(events.filter((one) => one === "ended")).toHaveLength(1);
  });

  it("咳嗽和键盘声顶破阈值也不算一句话", () => {
    const detector = settled();
    // 100ms 的一下(短于 minSpeechMs 350ms)
    const events = feed(detector, [LOUD, ...Array(12).fill(QUIET)], 100);
    expect(events).toContain("discarded");
    expect(events).not.toContain("ended");
  });

  it("说太久先交上去,别让整段被后端拒掉", () => {
    const detector = new UtteranceDetector({ ...DEFAULT_UTTERANCE_OPTIONS, maxUtteranceMs: 500 });
    feed(detector, Array(20).fill(QUIET));
    const events = feed(detector, Array(10).fill(LOUD), 100);
    expect(events).toContain("ended");
  });

  it("滞回:音量在阈值附近抖动不会把一句话切碎", () => {
    const detector = settled();
    // 在 startFactor(3.5×)和 endFactor(2×)之间来回 —— 只有一个阈值的话这里会疯狂开合。
    const between = QUIET * 2.6;
    const events = feed(detector, [...Array(6).fill(LOUD), ...Array(10).fill(between), ...Array(12).fill(QUIET)], 100);
    expect(events.filter((one) => one === "ended")).toHaveLength(1);
  });

  it("吵的环境里地板跟着抬高,不会一直误触发", () => {
    const noisy = new UtteranceDetector();
    // 咖啡馆:底噪本身就有 0.05
    feed(noisy, Array(40).fill(0.05));
    const events = feed(noisy, Array(20).fill(0.05), 100);
    expect(new Set(events)).toEqual(new Set(["idle"]));
  });

  it("说话中不抬高地板 —— 否则长句子会把自己判成静音", () => {
    const detector = settled();
    // 连说 6 秒。地板若跟着涨,说到后面 LOUD 就不再"高于地板×2"了,会提前断句。
    const events = feed(detector, [...Array(60).fill(LOUD), ...Array(12).fill(QUIET)], 100);
    expect(events.filter((one) => one === "ended")).toHaveLength(1);
  });
});
