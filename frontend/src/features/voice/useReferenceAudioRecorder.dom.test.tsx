/** @vitest-environment jsdom */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useReferenceAudioRecorder } from "./useReferenceAudioRecorder";

let payloadBytes = 2048;

class FakeMediaRecorder {
  state: RecordingState = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(_stream: MediaStream) {}

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["x".repeat(payloadBytes)], { type: this.mimeType }) } as BlobEvent);
    this.onstop?.(new Event("stop"));
  }
}

describe("useReferenceAudioRecorder", () => {
  const stopTrack = vi.fn();
  const getUserMedia = vi.fn();

  beforeEach(() => {
    payloadBytes = 2048;
    stopTrack.mockReset();
    getUserMedia.mockReset();
    getUserMedia.mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns a recorded File and releases the microphone track", async () => {
    const onRecorded = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() => useReferenceAudioRecorder({ onRecorded, onError }));

    await act(async () => result.current.start());
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(result.current.recording).toBe(true);

    act(() => result.current.stop());

    expect(onError).not.toHaveBeenCalled();
    expect(onRecorded).toHaveBeenCalledOnce();
    expect(onRecorded.mock.calls[0][0]).toBeInstanceOf(File);
    expect(onRecorded.mock.calls[0][0].type).toBe("audio/webm");
    expect(stopTrack).toHaveBeenCalledOnce();
    expect(result.current.recording).toBe(false);
  });

  it("rejects an empty capture instead of replacing the selected reference", async () => {
    payloadBytes = 32;
    const onRecorded = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() => useReferenceAudioRecorder({ onRecorded, onError }));

    await act(async () => result.current.start());
    act(() => result.current.stop());

    expect(onRecorded).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith("empty");
    expect(stopTrack).toHaveBeenCalledOnce();
  });

  it("releases the microphone without creating a file when a dialog cancels", async () => {
    const onRecorded = vi.fn();
    const onError = vi.fn();
    const { result } = renderHook(() => useReferenceAudioRecorder({ onRecorded, onError }));

    await act(async () => result.current.start());
    act(() => result.current.cancel());

    expect(onRecorded).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    expect(stopTrack).toHaveBeenCalledOnce();
    expect(result.current.recording).toBe(false);
  });

  it("distinguishes permission denial from recorder failures", async () => {
    getUserMedia.mockRejectedValueOnce({ name: "NotAllowedError" });
    const denied = vi.fn();
    const deniedHook = renderHook(() => useReferenceAudioRecorder({ onRecorded: vi.fn(), onError: denied }));
    await act(async () => deniedHook.result.current.start());
    expect(denied).toHaveBeenCalledWith("denied");
    deniedHook.unmount();

    getUserMedia.mockResolvedValueOnce({ getTracks: () => [{ stop: stopTrack }] });
    vi.stubGlobal("MediaRecorder", undefined);
    const failed = vi.fn();
    const failedHook = renderHook(() => useReferenceAudioRecorder({ onRecorded: vi.fn(), onError: failed }));
    await act(async () => failedHook.result.current.start());
    expect(failed).toHaveBeenCalledWith("failed");
    expect(stopTrack).toHaveBeenCalledOnce();
  });
});
