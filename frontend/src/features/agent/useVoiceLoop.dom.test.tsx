/** @vitest-environment jsdom */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useVoiceLoop } from "./useVoiceLoop";

const mocks = vi.hoisted(() => ({
  playSpeech: vi.fn(),
  stopSpeaking: vi.fn(),
  toastError: vi.fn(),
  toastMessage: vi.fn(),
}));

vi.mock("@/api/client", () => ({ API_BASE: "http://api.test", getAuthToken: () => "token" }));
vi.mock("@/features/agent/speechPlayback", () => ({
  playSpeech: mocks.playSpeech,
  stopSpeaking: mocks.stopSpeaking,
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
    mocks.playSpeech.mockReset().mockResolvedValue(undefined);
    mocks.stopSpeaking.mockReset();
    mocks.toastError.mockReset();
    mocks.toastMessage.mockReset();
    stopTrack.mockReset();
    getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(["speech"])),
    }));
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
    expect(mocks.stopSpeaking).toHaveBeenCalledOnce();
  });

  it("moves speaking back to listening only after playback settles", async () => {
    const playback = deferred();
    mocks.playSpeech.mockReturnValueOnce(playback.promise);
    const props = { workspaceId: "w1", onUtterance: vi.fn(), reply: "", busy: false };
    const { result, rerender } = renderHook((next: typeof props) => useVoiceLoop(next), { initialProps: props });
    await act(async () => result.current.start());

    rerender({ ...props, reply: "完成了" });
    await waitFor(() => expect(result.current.state).toBe("speaking"));
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/agent/speech", expect.objectContaining({ method: "POST" }));

    await act(async () => playback.resolve());
    expect(result.current.state).toBe("listening");
  });
});

