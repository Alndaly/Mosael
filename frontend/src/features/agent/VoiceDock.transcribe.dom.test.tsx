/** @vitest-environment jsdom */
/**
 * 「停止录音」到「识别回来」之间的那段等待 —— 必须**看得见**。
 *
 * 免提的前提是手和眼睛都在别处;而识别本身是一段没有声音的等待,首次用 sherpa-onnx 还要载模型,
 * 可能十几秒。这段里界面如果什么都不说,用户读到的就是「它没听见」,于是再说一遍 —— 然后再等一次。
 *
 * 所以这里钉三件事:
 *
 * · 从录音停下那一刻起、`dictate()` 还没回来之前,浮标旁写着「转写中…」并有一颗转圈;
 *   这段说明**不会** 2.4 秒后自己收起来(模型载多久,它就挂多久);
 * · 成功、失败、取消、卸载四条出口都会把它收掉 —— 不留一个永远转圈的浮标;
 * · 失败时说出的是「这段没转成文字」(dictateFailed),而不是「这句没送出去」——
 *   失败发生在识别,不发生在发送,文案说错地方等于把人指向错误的下一步。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  dictate: vi.fn(),
  getAgentSession: vi.fn(),
  listAgentSessions: vi.fn(),
  listAgentMessages: vi.fn(),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  sendAgentMessage: vi.fn(),
  toastError: vi.fn(),
  playBlob: vi.fn(),
  stopPlayback: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  dictate: mocks.dictate,
  getAgentSession: mocks.getAgentSession,
  listAgentSessions: mocks.listAgentSessions,
  listAgentMessages: mocks.listAgentMessages,
  createAgentSession: mocks.createAgentSession,
  updateAgentSession: mocks.updateAgentSession,
  sendAgentMessage: mocks.sendAgentMessage,
}));
//: 用真实的文案 —— 断言的是用户真会看到的那几个字,不是 key。
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const t = (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key];
  return { useI18n: () => t };
});
vi.mock("sonner", () => ({ toast: { error: mocks.toastError } }));
vi.mock("@/lib/audioPlayback", () => ({ playBlob: mocks.playBlob, stopPlayback: mocks.stopPlayback }));
vi.mock("@/features/agent/agentSpeech", () => ({
  synthesizeSpeech: vi.fn().mockResolvedValue(new Blob(["voice"])),
  reportSpeechFailure: vi.fn(),
}));
vi.mock("@/components/app/useFloatingPanel", () => ({
  useFloatingPanel: () => ({ style: {}, startDrag: () => {}, wasDragged: () => false, focusProps: {} }),
}));
//: 分句器是音频算法,这里只借它说「开始说了 / 说完了」两拍。
vi.mock("@/features/agent/utteranceDetector", () => ({
  UtteranceDetector: class {
    setStartFactor = vi.fn();
    triggerLevel = 1;
    push = mocks.push;
    reset = vi.fn();
  },
}));

import { VoiceDock } from "./VoiceDock";
import { resetActivePlaces } from "./activePlace";
import { STUDIO_PLACE } from "./places";

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

class FakeAnalyser {
  fftSize = 0;
  getFloatTimeDomainData() {}
}

class FakeAudioContext {
  close = vi.fn().mockResolvedValue(undefined);
  createAnalyser() {
    return new FakeAnalyser();
  }
  createMediaStreamSource() {
    return { connect: vi.fn() };
  }
}

const session = {
  id: "s-studio",
  workspace_id: "w1",
  title: "s-studio",
  status: "idle",
  is_mine: true,
  home_kind: "studio",
  home_id: "",
  home_name: "",
  home_state: "ok",
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VoiceDock workspaceId="w1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

/** 点开浮标 → 分句器报「开始说」→ 报「说完了」,录音随之停下、clips 交给 dictate。 */
async function speakOnce() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "免提对话" }));
  });
  await act(async () => {
    vi.advanceTimersByTime(50);
  });
  await act(async () => {
    vi.advanceTimersByTime(50);
  });
}

/** 说明气泡本身:「转写中…」是它的文字,看得见与否在它的 class 上(opacity-100)。 */
function captionOf(text: string) {
  const caption = screen.getByText(text);
  return { caption, visible: caption.className.includes("opacity-100") };
}

beforeEach(() => {
  vi.useFakeTimers();
  window.sessionStorage.clear();
  resetActivePlaces();
  for (const fn of Object.values(mocks)) fn.mockReset();
  mocks.listAgentSessions.mockResolvedValue([]);
  mocks.listAgentMessages.mockResolvedValue([]);
  mocks.getAgentSession.mockResolvedValue(session);
  mocks.createAgentSession.mockResolvedValue(session);
  mocks.updateAgentSession.mockResolvedValue(session);
  mocks.sendAgentMessage.mockResolvedValue({});
  mocks.playBlob.mockResolvedValue(undefined);
  mocks.push.mockReturnValue("silence");
  mocks.push.mockReturnValueOnce("speaking").mockReturnValueOnce("ended");
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

/** 让 dictate 停在半路 —— 断言的就正是「它还没回来」这一段。 */
function pendingDictate() {
  let resolve!: (value: { text: string }) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<{ text: string }>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  mocks.dictate.mockReturnValue(promise);
  return { resolve, reject };
}

describe("免提浮标的「转写中」", () => {
  it("录音停下、dictate 还没回来:一直写着「转写中…」并在转圈,不会 2.4 秒后自己收起来", async () => {
    mocks.dictate.mockReturnValue(new Promise(() => {}));
    const view = mount();
    await speakOnce();

    expect(FakeRecorder.last?.state).toBe("inactive");
    expect(mocks.dictate).toHaveBeenCalledOnce();
    expect(mocks.dictate.mock.calls[0][0]).toBeInstanceOf(Blob);

    const { visible } = captionOf("转写中…");
    expect(visible).toBe(true);
    expect(view.container.querySelector(".animate-mosael-spin")).not.toBeNull();

    // 首次识别要载模型:十几秒也还是同一句话,不闪、不消失。
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(captionOf("转写中…").visible).toBe(true);
    expect(view.container.querySelector(".animate-mosael-spin")).not.toBeNull();
  });

  it("识别成功:状态收掉,识别到的文字发出去", async () => {
    const dictate = pendingDictate();
    mount();
    await speakOnce();
    expect(screen.getByText("转写中…")).toBeTruthy();

    await act(async () => {
      dictate.resolve({ text: "把这段改短" });
    });

    expect(screen.queryByText("转写中…")).toBeNull();
    expect(mocks.sendAgentMessage).toHaveBeenCalledWith("s-studio", { content: "把这段改短", place: STUDIO_PLACE });
  });

  it("识别失败:状态收掉,并且说的是「没转成文字」而不是「没送出去」", async () => {
    const dictate = pendingDictate();
    mount();
    await speakOnce();
    expect(screen.getByText("转写中…")).toBeTruthy();

    await act(async () => {
      dictate.reject(new Error("sherpa 挂了"));
    });

    expect(screen.queryByText("转写中…")).toBeNull();
    expect(mocks.toastError).toHaveBeenCalledWith("这段没能转成文字,再说一次试试。");
    expect(mocks.sendAgentMessage).not.toHaveBeenCalled();
  });

  it("识别回来是空的:状态收掉,并且说「没听到内容」", async () => {
    const dictate = pendingDictate();
    mount();
    await speakOnce();
    expect(screen.getByText("转写中…")).toBeTruthy();

    await act(async () => {
      dictate.resolve({ text: "   " });
    });

    expect(screen.queryByText("转写中…")).toBeNull();
    expect(mocks.toastError).toHaveBeenCalledWith("没听到内容 —— 离麦克风近一点,或者确认选对了输入设备。");
  });

  it("等待中关掉免提(取消):状态立刻收掉;迟到的识别结果不会把它重新点亮,也不会替你发出去", async () => {
    const dictate = pendingDictate();
    mount();
    await speakOnce();
    expect(screen.getByText("转写中…")).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "转写中…" }));
    });
    expect(screen.queryByText("转写中…")).toBeNull();

    await act(async () => {
      dictate.resolve({ text: "你好" });
    });
    expect(screen.queryByText("转写中…")).toBeNull();
    expect(mocks.sendAgentMessage).not.toHaveBeenCalled();
  });

  it("等待中组件卸载:迟到的识别结果不再更新界面,也不发送", async () => {
    const dictate = pendingDictate();
    const view = mount();
    await speakOnce();
    view.unmount();

    await act(async () => {
      dictate.resolve({ text: "你好" });
    });
    expect(mocks.sendAgentMessage).not.toHaveBeenCalled();
  });
});
