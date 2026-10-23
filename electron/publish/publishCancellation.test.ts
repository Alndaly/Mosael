import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => {
  const adapter = Object.fromEntries(["openCreatorPage", "checkLogin", "uploadVideo", "fillTitle", "fillTags", "submit", "waitResult"].map(k => [k, vi.fn(async () => true)]));
  const driver = { setAbortSignal: vi.fn(), captureResponses: vi.fn(() => ({ stop: async () => [] })), setMetricsOverride: vi.fn(), clearMetricsOverride: vi.fn(async () => {}), url: () => "about:blank" };
  const views = { attachWindow: vi.fn(), getDriver: () => driver, panelAttach: vi.fn(), panelDetach: vi.fn(), isPanelled: () => true, configureAccount: vi.fn(async () => {}) };
  const backend = { heartbeat: vi.fn(async () => {}), markDue: vi.fn(async () => {}), claimTask: vi.fn(), claimCheck: vi.fn(async () => ({ account: null })), patchAccount: vi.fn(async () => {}), reportTask: vi.fn(async () => {}), taskStatus: vi.fn(async () => ({ status: "running" })) };
  return { adapter, driver, views, backend };
});
vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));
vi.mock("./accountViews", () => ({ createSharedViews: () => mocks.views, destroySharedViews: vi.fn() }));
vi.mock("./adapters", () => ({ createAdapter: () => mocks.adapter }));
vi.mock("./log", () => ({ plog: vi.fn() }));
vi.mock("./publishBackend", () => mocks.backend);
import { startPublishWorker, stopPublishWorker } from "./publishWorker";

//: 执行器现在开跑之前会看「素材文件在不在」(不存在的路径交给页面只会换来平台一句含糊的
//: 「部分文件处理失败」),所以这一份任务得指向一个真实的临时文件。
const MEDIA = join(mkdtempSync(join(tmpdir(), "mosael-publish-")), "test.mp4");
writeFileSync(MEDIA, "x");

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  mocks.backend.taskStatus.mockResolvedValue({ status: "running" });
  mocks.backend.claimTask.mockResolvedValue({ task: null }).mockResolvedValueOnce({ task: {
    id: "task", account_id: "account", account_name: "Test", platform: "douyin", video_path: MEDIA, title: "test", tags: [], status: "running",
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
