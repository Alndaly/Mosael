import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => {
  //: `supports` 是接口上**必填**的声明(见 adapters/shared):假适配器也得说清自己会发什么形状。
  const adapter = {
    supports: ["video"] as const,
    ...Object.fromEntries(["openCreatorPage", "checkLogin", "uploadVideo", "fillTitle", "fillTags", "submit", "waitResult"].map(k => [k, vi.fn(async () => true)])),
  };
  const driver = { setAbortSignal: vi.fn(), captureResponses: vi.fn(() => ({ stop: async () => [] })), setMetricsOverride: vi.fn(), clearMetricsOverride: vi.fn(async () => {}), url: () => "about:blank" };
  const views = { attachWindow: vi.fn(), getDriver: () => driver, panelAttach: vi.fn(), panelDetach: vi.fn(), isPanelled: () => true, configureAccount: vi.fn(async () => {}) };
  const backend = { heartbeat: vi.fn(async () => {}), markDue: vi.fn(async () => {}), claimTask: vi.fn(), claimCheck: vi.fn(async () => ({ account: null })), patchAccount: vi.fn(async () => {}), reportTask: vi.fn(async () => {}), taskStatus: vi.fn(async () => ({ status: "running" })) };
  return { adapter, driver, views, backend };
});
vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));
//: 执行器开跑前会 stat 一下素材文件(素材丢了要在动手前点名)。这条用例用的是假计时器,
//: 真实文件系统的 Promise 什么时候 resolve 不确定 —— CI 上就因此错过了「提交」那一拍。
//: 这里直接把 stat 钉成"文件在",让用例只测调度,不测磁盘。
vi.mock("node:fs/promises", () => ({
  mkdir: vi.fn(async () => undefined),
  stat: vi.fn(async () => ({ isFile: () => true, size: 1 })),
}));
vi.mock("../pool/accountViews", () => ({ createSharedViews: () => mocks.views, destroySharedViews: vi.fn() }));
vi.mock("./adapters", () => ({ createAdapter: () => mocks.adapter }));
vi.mock("../log", () => ({ plog: vi.fn() }));
vi.mock("./publishBackend", () => mocks.backend);
import { startPublishWorker, stopPublishWorker } from "./publishWorker";

const MEDIA = "/tmp/mosael-cancel-test.mp4";

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  mocks.backend.taskStatus.mockResolvedValue({ status: "running" });
  mocks.backend.claimTask.mockResolvedValue({ task: null }).mockResolvedValueOnce({ task: {
    id: "task", account_id: "account", account_name: "Test", platform: "douyin",
    content_kind: "video", body: "", media_paths: [MEDIA], title: "test", tags: [], status: "running",
  } });
  mocks.adapter.fillTags.mockImplementation(async () => true);
});
afterEach(() => { stopPublishWorker(); vi.clearAllTimers(); vi.useRealTimers(); });

it("cancellation during preparation prevents submitting to the platform", async () => {
  mocks.adapter.fillTags.mockImplementation(async () => {
    mocks.backend.taskStatus.mockResolvedValue({ status: "cancelled" });
    return true;
  });
  startPublishWorker({ window: {} as never });
  await vi.advanceTimersByTimeAsync(15_000);
  expect(mocks.adapter.fillTags).toHaveBeenCalledOnce();
  expect(mocks.adapter.submit).not.toHaveBeenCalled();
  expect(mocks.backend.reportTask).not.toHaveBeenCalledWith("task", { status: "success" });
  expect(mocks.driver.setAbortSignal).toHaveBeenCalledWith(expect.any(AbortSignal));
});

it("active tasks still submit and report success", async () => {
  startPublishWorker({ window: {} as never });
  await vi.advanceTimersByTimeAsync(15_000);
  expect(mocks.adapter.submit).toHaveBeenCalledOnce();
  expect(mocks.backend.reportTask).toHaveBeenCalledWith("task", { status: "success", post: null });
});
