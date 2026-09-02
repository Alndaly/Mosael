import { describe, expect, it, vi } from "vitest";

import { captureVideoFrame } from "../src/video-frame";

describe("video frame capture", () => {
  it("draws only the decoded video pixels at their intrinsic resolution", () => {
    const drawImage = vi.fn();
    const toDataURL = vi.fn(() => "data:image/png;base64,frame");
    const canvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => ({ drawImage })),
      toDataURL,
    };
    const video = { videoWidth: 1920, videoHeight: 1080 };

    expect(captureVideoFrame(video, () => canvas)).toBe("data:image/png;base64,frame");
    expect(canvas.width).toBe(1920);
    expect(canvas.height).toBe(1080);
    expect(drawImage).toHaveBeenCalledWith(video, 0, 0, 1920, 1080);
    expect(toDataURL).toHaveBeenCalledWith("image/png");
  });

  it("rejects videos whose decoded frame is not ready", () => {
    expect(() => captureVideoFrame({ videoWidth: 0, videoHeight: 0 }, vi.fn())).toThrow(
      "视频画面尚未就绪",
    );
  });
});
