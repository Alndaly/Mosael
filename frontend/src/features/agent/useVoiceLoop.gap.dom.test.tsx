/** @vitest-environment jsdom */

/**
 * 转写成功 → 声音出来:中间那段**不许什么都不说**。
 *
 * 维护者报的是:「转写中 → 转写成功 → 过一会儿 → 生成音频中 —— 这是怎么回事」。
 * 「过一会儿」里其实一直有事在跑:这一轮的对话模型还在出回复(可能还有工具调用)。界面上它却
 * 写着「在听」—— 那是「轮到你说」的意思;旁边那行说明 2.4 秒后就自己收起来了,于是那一段看起来
 * 什么都没发生。根因在状态机:发消息那个 Promise 一落定(只是 POST 被收下了,不是这一轮跑完了),
 * `submit` 的 finally 就把 `thinking` 改回了 `listening`。
 *
 * 这里用**一个慢对话模型**把那条时间线走一遍:识别回来 → 消息被收下 → 模型跑好几秒(状态是
 * `busy`)→ 回复落库 → 合成。每一拍都断言两件事:
 *
 * 1. 浮标处在一个**有话说**的状态(短名和整句都不为空);
 * 2. 这一段说的就是真正在跑的事 —— 等回复时说「在想」,回复到了等合成时说「生成语音中」,
 *    绝不在「在听」(或「转写中」)上停着。
 *
 * 「先出声 / 等整段」只影响**开念之后**怎么切句,两条路都得过同一道门:回复落库、这一轮收尾。
 * 所以两条都跑一遍 —— 见「等整段」那条。
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  dictate: vi.fn(),
  synthesize: vi.fn(),
  reportSpeechFailure: vi.fn(),
  playBlob: vi.fn(),
  stopPlayback: vi.fn(),
  /** 「念回复时先出声」(early) / 「等整段」(whole)。 */
  mode: "early" as "early" | "whole",
  /** 分句器每一报一次:speaking → hearing,ended → 停止录音。 */
  events: [] as string[],
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  dictate: mocks.dictate,
}));
vi.mock("@/features/agent/agentSpeech", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/agent/agentSpeech")>();
  return { ...actual, synthesizeSpeech: mocks.synthesize, reportSpeechFailure: mocks.reportSpeechFailure };
});
vi.mock("@/features/agent/speechSettings", () => ({
  loadSpeechMode: () => Promise.resolve(mocks.mode),
  prefetchSpeechMode: () => {},
}));
vi.mock("@/lib/audioPlayback", () => ({ playBlob: mocks.playBlob, stopPlayback: mocks.stopPlayback }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), message: vi.fn() } }));
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const t = (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key];
  return { useI18n: () => t };
});
vi.mock("@/features/agent/utteranceDetector", () => ({
  UtteranceDetector: class {
    triggerLevel = 1;
    push = () => mocks.events.shift() ?? "silence";
    reset = vi.fn();
  },
}));

import { messages } from "@/app/messages";
import { useVoiceLoop } from "./useVoiceLoop";
import { voiceAssistantView } from "./voiceAssistant";

const T = messages["zh-CN"];
const t = (key: keyof typeof T) => T[key];

class FakeRecorder {
  static last: FakeRecorder | null = null;
  mimeType = "audio/webm";
  state = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(public stream: MediaStream) {
    FakeRecorder.last = this;
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

class FakeAudioContext {
  close = vi.fn().mockResolvedValue(undefined);
  createAnalyser() {
    return { fftSize: 0, getFloatTimeDomainData: vi.fn() };
  }
  createMediaStreamSource() {
    return { connect: vi.fn() };
  }
}

type Props = Parameters<typeof useVoiceLoop>[0];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

/** 浮标此刻会说的那两句话。断言的是用户真会看到/听到的文案,不是内部状态名。 */
function viewOf(loop: ReturnType<typeof useVoiceLoop>) {
  return voiceAssistantView({ on: loop.on, state: loop.state, heard: loop.heard, failure: loop.speechFailure, t });
}

/** 一「拍」:推进假时钟,取回这一拍浮标的状态和它说的话。 */
async function tick(result: { current: ReturnType<typeof useVoiceLoop> }, ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  const view = viewOf(result.current);
  return { state: result.current.state, label: view.label, caption: view.caption };
}

function expectItHasSomethingToSay(beat: { state: string; label: string; caption: string }, index: number) {
  expect(beat.label, `第 ${index} 拍浮标的短名是空的`).toBeTruthy();
  expect(beat.caption, `第 ${index} 拍浮标没有说明文字`).toBeTruthy();
}

/**
 * 从「点开浮标」走到「识别回来、消息被收下」。
 *
 * 之后这一轮还在跑 —— 那一段正是要守的。返回的 `sent` 控制「POST 被收下」这一刻,
 * 因为缺陷就出在它:它一落定状态就被改回「在听」,而这一轮其实还在跑。
 */
async function speakAndSend() {
  const dictate = deferred<{ text: string }>();
  const sent = deferred<void>();
  mocks.dictate.mockReturnValue(dictate.promise);
  mocks.events = ["speaking", "ended"];
  const onUtterance = vi.fn(() => sent.promise);
  const props: Props = { workspaceId: "w1", onUtterance, reply: "", busy: false };
  const { result, rerender } = renderHook((next: Props) => useVoiceLoop(next), { initialProps: props });

  await act(async () => {
    await result.current.start();
  });
  expect(result.current.state).toBe("listening");

  //: 开口 → 「听你说」。
  await act(async () => {
    vi.advanceTimersByTime(50);
  });
  expect(result.current.state).toBe("hearing");

  //: 说完 → 录音停下,交给识别。
  await act(async () => {
    vi.advanceTimersByTime(50);
  });
  expect(result.current.state).toBe("transcribing");
  expect(viewOf(result.current).label).toBe(T.transcribing);

  //: 识别回来 —— 立刻从「转写中」走开,进入「在想」。
  await act(async () => {
    dictate.resolve({ text: "把这段改短" });
  });
  expect(result.current.state, "转写成功后还停在转写(或「完成」)上").toBe("thinking");

  return { result, rerender, props, sent };
}

describe("转写成功之后、声音出来之前", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.dictate.mockReset();
    mocks.synthesize.mockReset();
    mocks.reportSpeechFailure.mockReset();
    mocks.playBlob.mockReset();
    mocks.stopPlayback.mockReset();
    mocks.events = [];
    mocks.mode = "early";
    mocks.synthesize.mockReturnValue(new Promise<Blob>(() => {}));
    mocks.playBlob.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
    });
    vi.stubGlobal("MediaRecorder", FakeRecorder as unknown as typeof MediaRecorder);
    vi.stubGlobal("AudioContext", FakeAudioContext);
    FakeRecorder.last = null;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("慢对话模型那几秒:每一拍都在「在想」,不在「在听」上停着;回复到了就切「生成语音中」", async () => {
    const { result, rerender, props, sent } = await speakAndSend();

    //: POST 被收下 —— 但这一轮还没跑完。不能在这一刻把状态收回「在听」。
    await act(async () => {
      sent.resolve();
    });
    expect(result.current.state, "消息刚发出去就把浮标改回「在听」了,这一轮还在跑").toBe("thinking");

    //: 轮询还没把会话标成 running 的那一下:仍然是在等回复。
    for (let index = 0; index < 10; index += 1) {
      const beat = await tick(result, 100);
      expectItHasSomethingToSay(beat, index);
      expect(beat.state, `第 ${index} 拍写着「${beat.label}」,但这一轮还在跑`).toBe("thinking");
      expect(beat.caption).toContain(T.voiceMode_thinking);
      //: 听到的那句还得在:它说明这一轮对着哪句话在跑。
      expect(beat.caption).toContain("把这段改短");
    }

    //: 轮询看到这一轮在跑:模型在出字(这里用 5 秒的 busy 模拟一个慢模型)。
    rerender({ ...props, busy: true });
    for (let index = 0; index < 20; index += 1) {
      const beat = await tick(result, 250);
      expectItHasSomethingToSay(beat, 10 + index);
      expect(beat.state, `第 ${10 + index} 拍写着「${beat.label}」,但模型还在出回复`).toBe("thinking");
      expect(beat.caption).toContain(T.voiceMode_thinking);
    }

    //: 回复落库、这一轮收尾 —— 该切到「生成语音中」了(不是回到「在听」)。
    rerender({ ...props, busy: false, reply: "改短了。" });
    await tick(result, 0);
    expect(result.current.state).toBe("synthesizing");
    const synthesizing = viewOf(result.current);
    expect(synthesizing.label).toBe(T.voiceMode_synthesizing);
    expect(synthesizing.caption).toBe(T.voiceMode_synthesizing);
  });

  it("转写成功之后那一态说的是「在想」,并且带着听到的那句 —— 不是一个像「转写完成」的停格", async () => {
    const { result, sent } = await speakAndSend();

    const view = viewOf(result.current);
    expect(view.label).toBe(T.voiceMode_thinking);
    expect(view.caption, "只写了「听到:…」—— 读起来像转写刚完成,没说它现在在干什么").toContain(
      T.voiceMode_thinking,
    );
    expect(view.caption).toContain("把这段改短");

    await act(async () => {
      sent.resolve();
    });
  });

  it("「等整段」也一样:回复没到之前一直「在想」,到了才整段合成", async () => {
    mocks.mode = "whole";
    const { result, rerender, props, sent } = await speakAndSend();
    await act(async () => {
      sent.resolve();
    });

    rerender({ ...props, busy: true });
    for (let index = 0; index < 8; index += 1) {
      const beat = await tick(result, 250);
      expectItHasSomethingToSay(beat, index);
      expect(beat.state, `第 ${index} 拍:等整段不等于「在听」`).toBe("thinking");
    }
    expect(mocks.synthesize, "回复还没到就先合成了").not.toHaveBeenCalled();

    const reply = "改短了。第二句也说完,整段一起合成。";
    rerender({ ...props, busy: false, reply });
    await tick(result, 0);
    expect(result.current.state).toBe("synthesizing");
    expect(mocks.synthesize).toHaveBeenCalledOnce();
    //: 「等整段」= 整段一次合成(那是用户选的语义),不是另一段没人说话的空白。
    expect(mocks.synthesize.mock.calls[0][0]).toBe(reply);
    expect(result.current.state).toBe("synthesizing");
  });

  it("这一轮只调了工具、没有回复可念:看门狗到点收回「在听」,不留一个永远转的浮标", async () => {
    const { result, rerender, props, sent } = await speakAndSend();
    await act(async () => {
      sent.resolve();
    });

    rerender({ ...props, busy: true });
    await tick(result, 1000);
    expect(result.current.state).toBe("thinking");

    //: 这一轮收尾了,但没有新的回复(只做了事)。等一次轮询的余量,回到听。
    rerender({ ...props, busy: false, reply: "" });
    await tick(result, 4000);
    expect(result.current.state).toBe("listening");
  });
});
