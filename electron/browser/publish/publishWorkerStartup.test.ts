import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp/mosael-publish-worker-test" } }));
vi.mock("../log", () => ({ plog: vi.fn() }));
vi.mock("../trace.cjs", () => ({ createTrace: () => vi.fn() }));
vi.mock("../views/viewHost", () => ({ hostedViews: () => undefined }));
vi.mock("./publishBackend", () => ({
  markDue: vi.fn(async () => ({ marked: 0 })),
  claimTask: vi.fn(async () => ({ task: null })),
  claimCheck: vi.fn(async () => ({ account: null })),
  heartbeat: vi.fn(async () => ({})),
}));

import * as backend from "./publishBackend";
import { startPublishWorker, stopPublishWorker } from "./publishWorker";

const STARTUP_DELAY_MS = 15_000;

describe("发布器启动时的全量账号巡检", () => {
  beforeEach(() => {
    vi.useFakeTimers();
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
});
