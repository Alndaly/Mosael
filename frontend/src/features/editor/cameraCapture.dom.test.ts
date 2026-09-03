/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMirroredCameraCapture } from "./cameraCapture";

describe("createMirroredCameraCapture", () => {
  const drawImage = vi.fn();
  const translate = vi.fn();
  const scale = vi.fn();
  const outputVideoTrack = { stop: vi.fn() };
  const sourceVideoTrack = {
    getSettings: () => ({ width: 1920, height: 1080, frameRate: 30 }),
    stop: vi.fn(),
  };
  const audioTrack = { stop: vi.fn() };
  const outputStream = {
    addTrack: vi.fn(),
    getTracks: () => [outputVideoTrack, audioTrack],
  };

  beforeEach(() => {
    drawImage.mockReset();
    translate.mockReset();
    scale.mockReset();
    outputVideoTrack.stop.mockReset();
    sourceVideoTrack.stop.mockReset();
    audioTrack.stop.mockReset();
    outputStream.addTrack.mockReset();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      clearRect: vi.fn(),
      drawImage,
      restore: vi.fn(),
      save: vi.fn(),
      scale,
      translate,
    } as unknown as CanvasRenderingContext2D);
    Object.defineProperty(HTMLCanvasElement.prototype, "captureStream", {
      configurable: true,
      value: vi.fn(() => outputStream),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("records horizontally mirrored camera frames while preserving audio", () => {
    let renderFrame: FrameRequestCallback | undefined;
    const cancelAnimationFrame = vi.fn();
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => {
        renderFrame = callback;
        return 42;
      }),
    );
    vi.stubGlobal("cancelAnimationFrame", cancelAnimationFrame);
    const source = {
      getAudioTracks: () => [audioTrack],
      getTracks: () => [sourceVideoTrack, audioTrack],
      getVideoTracks: () => [sourceVideoTrack],
    } as unknown as MediaStream;
    const video = document.createElement("video");

    const capture = createMirroredCameraCapture(source, video);
    renderFrame?.(0);

    expect(capture.stream).toBe(outputStream);
    expect(translate).toHaveBeenCalledWith(1920, 0);
    expect(scale).toHaveBeenCalledWith(-1, 1);
    expect(drawImage).toHaveBeenCalledWith(video, 0, 0, 1920, 1080);
    expect(outputStream.addTrack).toHaveBeenCalledWith(audioTrack);

    capture.release();

    expect(cancelAnimationFrame).toHaveBeenCalledWith(42);
    expect(sourceVideoTrack.stop).toHaveBeenCalledOnce();
    expect(outputVideoTrack.stop).toHaveBeenCalledOnce();
    expect(audioTrack.stop).toHaveBeenCalledOnce();
  });
});
