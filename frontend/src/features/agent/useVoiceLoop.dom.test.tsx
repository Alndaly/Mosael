/** @vitest-environment jsdom */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetSpeechModeForTests } from "@/features/agent/speechSettings";
import { useVoiceLoop } from "./useVoiceLoop";

const mocks = vi.hoisted(() => ({
  playBlob: vi.fn(),
  stopPlayback: vi.fn(),
  toastError: vi.fn(),
  toastMessage: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  API_BASE: "http://api.test",
  getAuthToken: () => "token",
}));
vi.mock("@/lib/audioPlayback", () => ({
  playBlob: mocks.playBlob,
  stopPlayback: mocks.stopPlayback,
}));
vi.mock("sonner", () => ({ toast: { error: mocks.toastError, message: mocks.toastMessage } }));
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const t = (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key];
  return { useI18n: () => t };
});

class FakeAudioContext {
  close = vi.fn().mockResolvedValue(undefined);
  createAnalyser() {
    return { fftSize: 0, getFloatTimeDomainData: vi.fn() };
  }
  createMediaStreamSource() {
    return { connect: vi.fn() };
  }
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("useVoiceLoop", () => {
  const stopTrack = vi.fn();
  const getUserMedia = vi.fn();

  beforeEach(() => {
    mocks.playBlob.mockReset().mockResolvedValue(undefined);
    mocks.stopPlayback.mockReset();
    mocks.toastError.mockReset();
    mocks.toastMessage.mockReset();
    stopTrack.mockReset();
    getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Blob(["speech"]), { status: 200 })));
    //: 模块级缓存会让用例互相影响:「念回复时先出声」那份设置是进程内的。
    resetSpeechModeForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("stays off and explains when microphone access fails", async () => {
    getUserMedia.mockRejectedValueOnce(new Error("denied"));
    const { result } = renderHook(() => useVoiceLoop({ workspaceId: "w1", onUtterance: vi.fn(), reply: "", busy: false }));

    await act(async () => result.current.start());
    expect(result.current.state).toBe("off");
    expect(mocks.toastError).toHaveBeenCalledWith("用不了麦克风");
  });

  it("starts listening and releases every native resource on stop", async () => {
    const { result } = renderHook(() => useVoiceLoop({ workspaceId: "w1", onUtterance: vi.fn(), reply: "", busy: false }));
    await act(async () => result.current.start());
    expect(result.current.state).toBe("listening");

    act(() => result.current.stop());
    expect(result.current.state).toBe("off");
    expect(stopTrack).toHaveBeenCalledOnce();
    expect(mocks.stopPlayback).toHaveBeenCalledOnce();
  });

  it("moves speaking back to listening only after playback settles", async () => {
    const playback = deferred();
    mocks.playBlob.mockReturnValueOnce(playback.promise);
    const props = { workspaceId: "w1", onUtterance: vi.fn(), reply: "", busy: false };
    const { result, rerender } = renderHook((next: typeof props) => useVoiceLoop(next), { initialProps: props });
    await act(async () => result.current.start());

    rerender({ ...props, reply: "完成了" });
    await waitFor(() => expect(result.current.state).toBe("speaking"));
    expect(fetch).toHaveBeenCalledWith(expect.stringMatching(/\/api\/agent\/speech$/), expect.objectContaining({ method: "POST" }));

    await act(async () => playback.resolve());
    expect(result.current.state).toBe("listening");
  });

  it("回复到了、声音还没合成出来:状态是「正在生成语音」,不是「在说」", async () => {
    //: 免提一挂上就去取「念回复时先出声 / 等整段」;那份设置先回,之后合成那一条才挂住。
    const settings = () => Promise.resolve(new Response(JSON.stringify({ speak_early: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    let release!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (
      String(input).includes("/api/agent/speech")
        ? new Promise<Response>((resolve) => { release = resolve; })
        : settings()
    )));
    const playback = deferred();
    mocks.playBlob.mockReturnValueOnce(playback.promise);

    const props = { workspaceId: "w1", onUtterance: vi.fn(), reply: "", busy: false };
    const { result, rerender } = renderHook((next: typeof props) => useVoiceLoop(next), { initialProps: props });
    await act(async () => result.current.start());

    rerender({ ...props, reply: "完成了" });
    await waitFor(() => expect(result.current.state).toBe("synthesizing"));
    expect(mocks.playBlob, "还没合成出来就先播了").not.toHaveBeenCalled();

    await act(async () => release(new Response(new Blob(["speech"]), { status: 200 })));
    await waitFor(() => expect(result.current.state).toBe("speaking"));

    await act(async () => playback.resolve());
    await waitFor(() => expect(result.current.state).toBe("listening"));
  });

  it("合成失败:说清原因、能重试;重试成功了照常念,不留一个死在那儿的状态", async () => {
    const settings = () => Promise.resolve(new Response(JSON.stringify({ speak_early: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    let synthCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (!String(input).includes("/api/agent/speech")) return settings();
      synthCalls += 1;
      return synthCalls === 1
        ? Promise.reject(new TypeError("Failed to fetch"))
        : Promise.resolve(new Response(new Blob(["speech"]), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const props = { workspaceId: "w1", onUtterance: vi.fn(), reply: "", busy: false };
    const { result, rerender } = renderHook((next: typeof props) => useVoiceLoop(next), { initialProps: props });
    await act(async () => result.current.start());

    rerender({ ...props, reply: "完成了" });
    await waitFor(() => expect(result.current.state).toBe("synthesisFailed"));
    expect(result.current.speechFailure?.retryable).toBe(true);
    expect(result.current.speechFailure?.message).toBeTruthy();
    expect(mocks.toastError, "合成失败静默了").toHaveBeenCalled();

    await act(async () => result.current.retrySpeech());
    await waitFor(() => expect(synthCalls).toBe(2));
    await waitFor(() => expect(result.current.state).toBe("listening"));
    expect(result.current.speechFailure).toBeNull();
  });
});

