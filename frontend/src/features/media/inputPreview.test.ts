import { describe, expect, it, vi } from "vitest";

import { createInputPreview } from "./inputPreview";

function fakeStream() {
  const video = { stop: vi.fn() };
  const audio = { stop: vi.fn() };
  const stream = { getTracks: () => [video, audio] } as unknown as MediaStream;
  return { stream, stopped: () => video.stop.mock.calls.length > 0 && audio.stop.mock.calls.length > 0, video };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const devices = { cameraId: "camera-1", micId: "mic-1" };

describe("input preview", () => {
  it("opens the chosen camera and microphone and publishes the live stream", async () => {
    const camera = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValue(camera.stream);
    const preview = createInputPreview({ getUserMedia });
    const listener = vi.fn();
    preview.subscribe(listener);

    preview.open(devices);
    preview.open(devices);
    await flush();

    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(getUserMedia).toHaveBeenCalledWith({
      video: { deviceId: { exact: "camera-1" } },
      audio: { deviceId: { exact: "mic-1" } },
    });
    expect(preview.getState()).toEqual({ stream: camera.stream, error: null });
    expect(listener).toHaveBeenCalled();
  });

  it("uses the system default devices when none is chosen", async () => {
    const getUserMedia = vi.fn().mockResolvedValue(fakeStream().stream);
    const preview = createInputPreview({ getUserMedia });

    preview.open({ cameraId: "", micId: "" });

    expect(getUserMedia).toHaveBeenCalledWith({ video: true, audio: true });
  });

  it("opens the microphone alone for a preview without a camera", async () => {
    const microphone = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValue(microphone.stream);
    const preview = createInputPreview({ getUserMedia });

    preview.open({ cameraId: null, micId: "mic-1" });
    await flush();

    expect(getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: "mic-1" } } });
    expect(preview.getState().stream).toBe(microphone.stream);
    await expect(preview.take({ cameraId: null, micId: "mic-1" })).resolves.toBe(microphone.stream);
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(microphone.stopped()).toBe(false);
  });

  it("treats a microphone-only preview and a default-camera preview as different inputs", async () => {
    const microphone = fakeStream();
    const camera = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValueOnce(microphone.stream).mockResolvedValueOnce(camera.stream);
    const preview = createInputPreview({ getUserMedia });

    preview.open({ cameraId: null, micId: "" });
    await flush();
    preview.open({ cameraId: "", micId: "" });
    await flush();

    expect(microphone.stopped()).toBe(true);
    expect(getUserMedia).toHaveBeenLastCalledWith({ video: true, audio: true });
    expect(preview.getState().stream).toBe(camera.stream);
  });

  it("replaces the stream when the device selection changes", async () => {
    const first = fakeStream();
    const second = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValueOnce(first.stream).mockResolvedValueOnce(second.stream);
    const preview = createInputPreview({ getUserMedia });

    preview.open(devices);
    await flush();
    preview.open({ ...devices, cameraId: "camera-2" });
    await flush();

    expect(first.stopped()).toBe(true);
    expect(second.stopped()).toBe(false);
    expect(preview.getState().stream).toBe(second.stream);
  });

  it("stops an acquisition that resolves after it was superseded or closed", async () => {
    const late = deferred<MediaStream>();
    const lateCamera = fakeStream();
    const current = fakeStream();
    const getUserMedia = vi.fn().mockReturnValueOnce(late.promise).mockResolvedValueOnce(current.stream);
    const preview = createInputPreview({ getUserMedia });

    preview.open(devices);
    preview.open({ ...devices, micId: "mic-2" });
    late.resolve(lateCamera.stream);
    await flush();

    expect(lateCamera.stopped()).toBe(true);
    expect(preview.getState().stream).toBe(current.stream);

    preview.close();
    expect(current.stopped()).toBe(true);
    expect(preview.getState().stream).toBeNull();
  });

  it("hands the open stream over without stopping it or opening the camera again", async () => {
    const camera = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValue(camera.stream);
    const preview = createInputPreview({ getUserMedia });
    preview.open(devices);
    await flush();

    await expect(preview.take(devices)).resolves.toBe(camera.stream);
    preview.close();

    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(camera.stopped()).toBe(false);
    expect(preview.getState().stream).toBeNull();
  });

  it("hands over an acquisition that is still pending", async () => {
    const pending = deferred<MediaStream>();
    const camera = fakeStream();
    const getUserMedia = vi.fn().mockReturnValue(pending.promise);
    const preview = createInputPreview({ getUserMedia });
    preview.open(devices);

    const taken = preview.take(devices);
    preview.close();
    pending.resolve(camera.stream);

    await expect(taken).resolves.toBe(camera.stream);
    await flush();
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(camera.stopped()).toBe(false);
    expect(preview.getState().stream).toBeNull();
  });

  it("acquires a camera for the recording when no preview is open for those devices", async () => {
    const stale = fakeStream();
    const fresh = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValueOnce(stale.stream).mockResolvedValueOnce(fresh.stream);
    const preview = createInputPreview({ getUserMedia });
    preview.open(devices);
    await flush();

    await expect(preview.take({ ...devices, cameraId: "camera-2" })).resolves.toBe(fresh.stream);

    expect(stale.stopped()).toBe(true);
    expect(getUserMedia).toHaveBeenLastCalledWith({
      video: { deviceId: { exact: "camera-2" } },
      audio: { deviceId: { exact: "mic-1" } },
    });
  });

  it("reports a failed acquisition and retries on the next open", async () => {
    const denied = new DOMException("denied", "NotAllowedError");
    const camera = fakeStream();
    const getUserMedia = vi.fn().mockRejectedValueOnce(denied).mockResolvedValueOnce(camera.stream);
    const preview = createInputPreview({ getUserMedia });

    preview.open(devices);
    await flush();
    expect(preview.getState()).toEqual({ stream: null, error: denied });

    preview.open(devices);
    await flush();
    expect(preview.getState()).toEqual({ stream: camera.stream, error: null });
  });
});
