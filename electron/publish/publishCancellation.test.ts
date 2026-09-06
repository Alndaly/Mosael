import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => {
  const adapter = Object.fromEntries(["openCreatorPage", "checkLogin", "uploadVideo", "fillTitle", "fillTags", "submit", "waitResult"].map(k => [k, vi.fn(async () => true)]));
  const driver = { setAbortSignal: vi.fn(), setMetricsOverride: vi.fn(), clearMetricsOverride: vi.fn(async () => {}), url: () => "about:blank" };
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

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  mocks.backend.taskStatus.mockResolvedValue({ status: "running" });
  mocks.backend.claimTask.mockResolvedValue({ task: null }).mockResolvedValueOnce({ task: {
    id: "task", account_id: "account", account_name: "Test", platform: "douyin", video_path: "/tmp/test.mp4", title: "test", tags: [], status: "running",
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
  expect(mocks.backend.reportTask).toHaveBeenCalledWith("task", { status: "success" });
});
