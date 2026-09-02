import { describe, expect, it, vi } from "vitest";

import {
  FRAME_CAPTURE_ORIGINS,
  requestFrameCapturePermission,
} from "../src/frame-capture-permission";

describe("frame capture permission", () => {
  it("requests the optional permission required by captureVisibleTab", async () => {
    const request = vi.fn(async () => true);

    await expect(requestFrameCapturePermission(request)).resolves.toBe(true);
    expect(request).toHaveBeenCalledOnce();
    expect(request).toHaveBeenCalledWith({ origins: [...FRAME_CAPTURE_ORIGINS] });
  });

  it("preserves a user denial so capture can stop before taking a screenshot", async () => {
    const request = vi.fn(async () => false);

    await expect(requestFrameCapturePermission(request)).resolves.toBe(false);
  });
});
