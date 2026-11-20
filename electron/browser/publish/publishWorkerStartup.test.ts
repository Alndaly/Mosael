import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const viewState = vi.hoisted(() => ({ current: null as unknown }));
const adapterState = vi.hoisted(() => ({ open: vi.fn(), check: vi.fn() }));

vi.mock("electron", () => ({ app: { getPath: () => "/tmp/mosael-publish-worker-test" } }));
vi.mock("../log", () => ({ plog: vi.fn() }));
vi.mock("../trace.cjs", () => ({ createTrace: () => vi.fn() }));
vi.mock("../views/viewHost", () => ({ hostedViews: () => viewState.current }));
vi.mock("./adapters", () => ({
  createAdapter: () => ({ openCreatorPage: adapterState.open, checkLogin: adapterState.check }),
}));
vi.mock("./publishBackend", () => ({
  markDue: vi.fn(async () => ({ marked: 0 })),
  claimTask: vi.fn(async () => ({ task: null })),
  claimCheck: vi.fn(async () => ({ account: null })),
  heartbeat: vi.fn(async () => ({})),
  patchAccount: vi.fn(async () => ({})),
}));

import * as backend from "./publishBackend";
import { startPublishWorker, stopPublishWorker } from "./publishWorker";

const STARTUP_DELAY_MS = 15_000;

function accountViews(existing: boolean) {
  return {
    has: vi.fn(() => existing),
    visibleAccountId: null,
    isPanelled: vi.fn(() => false),
    configureAccount: vi.fn(async () => undefined),
    getDriver: vi.fn(() => ({})),
    destroy: vi.fn(),
  };
}

async function runRecheck(views: ReturnType<typeof accountViews>) {
  viewState.current = views;
  vi.mocked(backend.claimCheck)
    .mockResolvedValueOnce({ account: {
      owner: "u1", account_id: "a1", platform: "douyin", name: "A", binding_status: "unknown",
    } })
    .mockResolvedValue({ account: null });
  startPublishWorker({});
  await vi.advanceTimersByTimeAsync(0);
}

describe("发布器启动时的全量账号巡检", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    viewState.current = null;
    adapterState.open.mockResolvedValue(undefined);
    adapterState.check.mockResolvedValue(true);
  });

  afterEach(() => {
    stopPublishWorker();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("任务循环立即启动,全量巡检等首屏稳定后再做", async () => {
    startPublishWorker({});
    await vi.advanceTimersByTimeAsync(0);
    expect(backend.claimTask).toHaveBeenCalled();
    expect(backend.markDue).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(STARTUP_DELAY_MS - 1);
    expect(backend.markDue).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(backend.markDue).toHaveBeenCalledTimes(1);
  });

  it("延迟期间停止发布器,旧定时器不再复活巡检", async () => {
    startPublishWorker({});
    stopPublishWorker();
    await vi.advanceTimersByTimeAsync(STARTUP_DELAY_MS);
    expect(backend.markDue).not.toHaveBeenCalled();
  });

  it("巡检新建的临时视图用完销毁,不让创作者页面常驻", async () => {
    const views = accountViews(false);
    await runRecheck(views);
    expect(views.destroy).toHaveBeenCalledWith("a1");
  });

  it("巡检开始前已经存在的账号视图保留", async () => {
    const views = accountViews(true);
    await runRecheck(views);
    expect(views.destroy).not.toHaveBeenCalled();
  });
});
