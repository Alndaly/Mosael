/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMirroredCameraCapture } from "./cameraCapture";

function fakeFrame(width: number, height: number) {
  return { displayWidth: width, displayHeight: height, close: vi.fn() } as unknown as VideoFrame & {
    close: ReturnType<typeof vi.fn>;
  };
}

/** Stands in for Chromium's MediaStreamTrackProcessor: the test decides when the camera emits. */
function installTrackProcessor() {
  let camera!: ReadableStreamDefaultController<VideoFrame>;
  const cancelled = vi.fn();
  const tracks: MediaStreamTrack[] = [];
  class FakeTrackProcessor {
    readonly readable: ReadableStream<VideoFrame>;
    constructor({ track }: { track: MediaStreamTrack }) {
      tracks.push(track);
      this.readable = new ReadableStream<VideoFrame>({
        start: (controller) => {
          camera = controller;
        },
        cancel: cancelled,
      });
    }
  }
  vi.stubGlobal("MediaStreamTrackProcessor", FakeTrackProcessor);
  return { emit: (frame: VideoFrame) => camera.enqueue(frame), cancelled, tracks };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("createMirroredCameraCapture", () => {
  const drawImage = vi.fn();
  const setTransform = vi.fn();
  const requestFrame = vi.fn();
  const outputVideoTrack = { stop: vi.fn(), requestFrame };
  const sourceVideoTrack = { stop: vi.fn() };
  const audioTrack = { stop: vi.fn() };
  const outputStream = {
    addTrack: vi.fn(),
    getVideoTracks: () => [outputVideoTrack],
    getTracks: () => [outputVideoTrack, audioTrack],
  };
  const source = {
    getAudioTracks: () => [audioTrack],
    getTracks: () => [sourceVideoTrack, audioTrack],
    getVideoTracks: () => [sourceVideoTrack],
  } as unknown as MediaStream;
  let canvases: HTMLCanvasElement[];
  let captureStream: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    canvases = [];
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (this: HTMLCanvasElement) {
      canvases.push(this);
      return { drawImage, setTransform } as unknown as CanvasRenderingContext2D;
    } as unknown as HTMLCanvasElement["getContext"]);
    captureStream = vi.fn(() => outputStream);
    Object.defineProperty(HTMLCanvasElement.prototype, "captureStream", {
      configurable: true,
      value: captureStream,
    });
    // The capture must never depend on page rendering.
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn(() => {
        throw new Error("camera mirroring must not be driven by requestAnimationFrame");
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(HTMLCanvasElement.prototype, "captureStream");
  });

  it("records every live camera frame mirrored, straight from the camera track", async () => {
    const camera = installTrackProcessor();

    const capture = createMirroredCameraCapture(source);

    expect(capture.stream).toBe(outputStream);
    expect(camera.tracks).toEqual([sourceVideoTrack]);
    expect(captureStream).toHaveBeenCalledWith(0);
    expect(outputStream.addTrack).toHaveBeenCalledWith(audioTrack);

    // Frames keep arriving long after start; each becomes exactly one recorded, mirrored frame.
    const frames = [fakeFrame(1280, 720), fakeFrame(1280, 720), fakeFrame(1920, 1080)];
    for (const frame of frames) camera.emit(frame);
    await flush();

    expect(drawImage.mock.calls).toEqual([
      [frames[0], 0, 0, 1280, 720],
      [frames[1], 0, 0, 1280, 720],
      [frames[2], 0, 0, 1920, 1080],
    ]);
    expect(setTransform).toHaveBeenLastCalledWith(-1, 0, 0, 1, 1920, 0);
    expect(requestFrame).toHaveBeenCalledTimes(3);
    expect(frames.every((frame) => frame.close.mock.calls.length === 1)).toBe(true);
    expect([canvases[0].width, canvases[0].height]).toEqual([1920, 1080]);
  });

  it("stops pulling frames and releases every track", async () => {
    const camera = installTrackProcessor();
    const capture = createMirroredCameraCapture(source);

    capture.release();
    await flush();

    expect(camera.cancelled).toHaveBeenCalledOnce();
    expect(sourceVideoTrack.stop).toHaveBeenCalledOnce();
    expect(outputVideoTrack.stop).toHaveBeenCalledOnce();
    expect(audioTrack.stop).toHaveBeenCalledOnce();
  });

  it("refuses to start without a way to read camera frames", () => {
    expect(() => createMirroredCameraCapture(source)).toThrow(/not supported/);
  });
});
