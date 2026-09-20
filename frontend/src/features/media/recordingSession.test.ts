/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createRecordingSession, EmptyRecordingError } from "./recordingSession";

class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  static payloadSizes: number[] = [];
  static failStartAt = -1;

  state: RecordingState = "inactive";
  mimeType = "video/webm";
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onstop: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readonly start = vi.fn((_: number) => {
    if (FakeMediaRecorder.instances.indexOf(this) === FakeMediaRecorder.failStartAt) throw new Error("start failed");
    this.state = "recording";
  });
  readonly stop = vi.fn(() => {
    this.state = "inactive";
    const size = FakeMediaRecorder.payloadSizes[FakeMediaRecorder.instances.indexOf(this)] ?? 4096;
    this.ondataavailable?.({ data: new Blob(["x".repeat(size)], { type: this.mimeType }) } as BlobEvent);
    this.onstop?.(new Event("stop"));
  });

  constructor(readonly stream: MediaStream) {
    FakeMediaRecorder.instances.push(this);
  }
}

function fakeStream() {
  const stop = vi.fn();
  return {
    stream: { getTracks: () => [{ stop }] } as unknown as MediaStream,
    stop,
  };
}

describe("recording session", () => {
  beforeEach(() => {
    FakeMediaRecorder.instances = [];
    FakeMediaRecorder.payloadSizes = [];
    FakeMediaRecorder.failStartAt = -1;
    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts screen and camera together and returns two independent files", async () => {
    const screen = fakeStream();
    const camera = fakeStream();
    const session = createRecordingSession(
      [
        { kind: "screen", stream: screen.stream, filenamePrefix: "screen" },
        { kind: "camera", stream: camera.stream, filenamePrefix: "camera" },
      ],
      { now: () => 1234 },
    );

    session.start();

    expect(FakeMediaRecorder.instances).toHaveLength(2);
    expect(FakeMediaRecorder.instances.map((recorder) => recorder.start.mock.calls[0]?.[0])).toEqual([1000, 1000]);

    const files = await session.stop();

    expect(files.map((file) => file.name)).toEqual(["screen-1234.webm", "camera-1234.webm"]);
    expect(files.every((file) => file.size === 4096)).toBe(true);
    expect(screen.stop).toHaveBeenCalledOnce();
    expect(camera.stop).toHaveBeenCalledOnce();
  });

  it("rejects the whole session when any capture is empty", async () => {
    FakeMediaRecorder.payloadSizes = [4096, 32];
    const screen = fakeStream();
    const camera = fakeStream();
    const session = createRecordingSession([
      { kind: "screen", stream: screen.stream, filenamePrefix: "screen" },
      { kind: "camera", stream: camera.stream, filenamePrefix: "camera" },
    ]);

    session.start();

    await expect(session.stop()).rejects.toBeInstanceOf(EmptyRecordingError);
    expect(screen.stop).toHaveBeenCalledOnce();
    expect(camera.stop).toHaveBeenCalledOnce();
  });

  it("releases every source if one recorder cannot start", () => {
    FakeMediaRecorder.failStartAt = 1;
    const screen = fakeStream();
    const camera = fakeStream();
    const session = createRecordingSession([
      { kind: "screen", stream: screen.stream, filenamePrefix: "screen" },
      { kind: "camera", stream: camera.stream, filenamePrefix: "camera" },
    ]);

    expect(() => session.start()).toThrow("start failed");
    expect(screen.stop).toHaveBeenCalledOnce();
    expect(camera.stop).toHaveBeenCalledOnce();
  });

  it("cancels all active captures without producing files", () => {
    const screen = fakeStream();
    const camera = fakeStream();
    const session = createRecordingSession([
      { kind: "screen", stream: screen.stream, filenamePrefix: "screen" },
      { kind: "camera", stream: camera.stream, filenamePrefix: "camera" },
    ]);

    session.start();
    session.cancel();

    expect(FakeMediaRecorder.instances.every((recorder) => recorder.stop.mock.calls.length === 1)).toBe(true);
    expect(screen.stop).toHaveBeenCalledOnce();
    expect(camera.stop).toHaveBeenCalledOnce();
  });

  it("reports recorder errors and rejects the session as one unit", async () => {
    const screen = fakeStream();
    const camera = fakeStream();
    const onError = vi.fn();
    const session = createRecordingSession(
      [
        { kind: "screen", stream: screen.stream, filenamePrefix: "screen" },
        { kind: "camera", stream: camera.stream, filenamePrefix: "camera" },
      ],
      { onError },
    );

    session.start();
    FakeMediaRecorder.instances[1].onerror?.(new Event("error"));

    expect(onError).toHaveBeenCalledOnce();
    await expect(session.stop()).rejects.toThrow("camera recorder failed");
    expect(screen.stop).toHaveBeenCalledOnce();
    expect(camera.stop).toHaveBeenCalledOnce();
  });
});
