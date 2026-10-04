/**
 * 「截图」节点在执行器这一侧:截哪种、元素没出现时等多久、截不到怎么说、截好的图带着什么交给后端。
 *
 * 截图本身(captureContents)换成能控制结果的假货 —— 真截图在隔离实跑里验(三种模式真的截出图来);
 * 这里验的是围着它的那几件事。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  capture: vi.fn(),
  upload: vi.fn(),
}));

vi.mock("./pageCapture", async () => {
  class ElementCaptureError extends Error {
    constructor(readonly reason: "missing" | "empty") {
      super(reason);
    }
  }
  return { captureContents: mocks.capture, ElementCaptureError };
});
vi.mock("./pageTarget", () => {
  class PageToolError extends Error {
    constructor(readonly code: string) {
      super(code);
    }
  }
  return { PageToolError };
});
vi.mock("./browserBackend", () => ({ browserBackend: { uploadArtifact: mocks.upload } }));
vi.mock("./browserActions", () => ({ ELEMENT_WAIT_MS: 5_000 }));

const { captureForAction } = await import("./actionCapture");
const { ElementCaptureError } = await import("./pageCapture");
const { PageToolError } = await import("./pageTarget");

const page = { isDestroyed: () => false, getURL: () => "https://example.com/post/1" };
const SHOT = {
  bytes: new Uint8Array([0x89, 0x50, 0x4e, 0x47]),
  width: 2560,
  height: 1600,
  truncated: false,
  page: { url: "https://example.com/post/1", title: "一篇帖子" },
  capturedAt: "2026-10-04T05:30:00.000Z",
};

const run = (args: Record<string, unknown>) =>
  captureForAction({ actionId: "a1", webContents: page as never, args });

beforeEach(() => {
  mocks.capture.mockReset();
  mocks.upload.mockReset();
  mocks.upload.mockResolvedValue({ asset_id: "asset-1", name: "一篇帖子", kind: "image" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("「截图」节点", () => {
  it("截好的图带着出处交给后端(执行器通道),结果里有素材 id 和尺寸", async () => {
    mocks.capture.mockResolvedValueOnce(SHOT);
    const outcome = await run({ mode: "full", name: "封面参考" });
    expect(mocks.capture).toHaveBeenCalledWith(page, "full", { selector: "" });
    expect(mocks.upload).toHaveBeenCalledWith(
      "a1",
      "screenshot",
      { body: expect.any(Blob), filename: "screenshot.png" },
      {
        capture: "screenshot_full",
        filename: "screenshot.png",
        name: "封面参考",
        page_url: "https://example.com/post/1",
        page_title: "一篇帖子",
        captured_at: "2026-10-04T05:30:00.000Z",
      },
    );
    expect(outcome).toEqual({
      value: { asset_id: "asset-1", name: "一篇帖子", width: 2560, height: 1600, truncated: false },
      lastUrl: "https://example.com/post/1",
    });
  });

  it("不认识的模式按可见区域截", async () => {
    mocks.capture.mockResolvedValueOnce(SHOT);
    await run({ mode: "everything" });
    expect(mocks.capture).toHaveBeenCalledWith(page, "visible", { selector: "" });
  });

  it("截元素:元素还没出现就等一会儿,出现了就截", async () => {
    mocks.capture
      .mockRejectedValueOnce(new ElementCaptureError("missing"))
      .mockRejectedValueOnce(new ElementCaptureError("missing"))
      .mockResolvedValueOnce(SHOT);
    const outcome = await run({ mode: "element", selector: ".cover", wait_ms: 2_000 });
    expect(mocks.capture).toHaveBeenCalledTimes(3);
    expect(mocks.capture).toHaveBeenLastCalledWith(page, "element", { selector: ".cover" });
    expect(mocks.upload.mock.calls[0][3].capture).toBe("screenshot_element");
    expect((outcome.value as { asset_id: string }).asset_id).toBe("asset-1");
  });

  it("截元素:等满还没有,说清等了多久、在找什么、停在哪一页;不交任何东西", async () => {
    mocks.capture.mockRejectedValue(new ElementCaptureError("missing"));
    await expect(run({ mode: "element", selector: ".cover", wait_ms: 300 })).rejects.toThrow(
      /0\.3s.*\.cover.*example\.com\/post\/1/,
    );
    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("截元素没填选择器、元素没有大小、整页截不了:都说人话", async () => {
    await expect(run({ mode: "element" })).rejects.toThrow(/选择器/);
    mocks.capture.mockRejectedValueOnce(new ElementCaptureError("empty"));
    await expect(run({ mode: "element", selector: "#hidden" })).rejects.toThrow(/没有大小.*#hidden/);
    mocks.capture.mockRejectedValueOnce(new PageToolError("full_page_unavailable"));
    await expect(run({ mode: "full" })).rejects.toThrow(/整页长图/);
    mocks.capture.mockRejectedValueOnce(new PageToolError("capture_failed"));
    await expect(run({ mode: "visible" })).rejects.toThrow(/没截到画面/);
  });

  it("后端拒收:原样抛出那句话", async () => {
    mocks.capture.mockResolvedValueOnce(SHOT);
    mocks.upload.mockRejectedValueOnce(new Error("这条动作已经结束了"));
    await expect(run({ mode: "visible" })).rejects.toThrow("这条动作已经结束了");
  });
});
