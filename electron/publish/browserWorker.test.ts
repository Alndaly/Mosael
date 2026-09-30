/**
 * 浏览器执行器的调度:不同会话并发、心跳自己一条循环、续不上租约的动作被中止、先搬分区再认领。
 *
 * 真跑 browserWorker 的循环,只把它够不着的外部换掉:后端(browserBackend)、视图宿主(accountViews)、
 * 动作本身(executeBrowserAction —— 用一个能控制何时结束的假动作,调度才看得见)。
 */
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const drivers = new Map<string, { setAbortSignal: ReturnType<typeof vi.fn>; signal: AbortSignal | null }>();
  const views = {
    registerSession: vi.fn((sessionId: string) => {
      const driver = drivers.get(sessionId) ?? {
        signal: null as AbortSignal | null,
        setAbortSignal: vi.fn((signal: AbortSignal | null) => {
          if (signal) driver.signal = signal;
        }),
      };
      drivers.set(sessionId, driver);
      return driver;
    }),
    panelAttach: vi.fn(() => true),
    panelDetach: vi.fn(),
    touchPanel: vi.fn(),
    destroy: vi.fn(),
  };
  const backend = {
    claim: vi.fn(),
    report: vi.fn(async () => ({})),
    heartbeat: vi.fn(async (): Promise<string[]> => []),
    partitionMoves: vi.fn(async () => [] as unknown[]),
    settlePartitionMove: vi.fn(async () => ({})),
  };
  const pending = new Map<string, () => void>();
  const execute = vi.fn(
    (_driver: unknown, _action: string, args: Record<string, unknown>) =>
      new Promise<{ lastUrl: string }>((resolve) => pending.set(String(args.tag), () => resolve({ lastUrl: "https://x.test/" }))),
  );
  return { drivers, views, backend, pending, execute };
});

vi.mock("electron", () => ({ app: { getPath: () => "/tmp/mosael-test-user-data" } }));
vi.mock("./accountViews", () => ({ sharedViews: () => mocks.views }));
vi.mock("./browserBackend", () => ({ browserBackend: mocks.backend }));
vi.mock("./browserActions", () => ({ executeBrowserAction: mocks.execute }));
vi.mock("./log", () => ({ plog: vi.fn() }));

import { startBrowserWorker, stopBrowserWorker } from "./browserWorker";

const action = (id: string, session: string, tag: string) => ({
  id, session_id: session, partition: `ephemeral-${session}`, kind: "ephemeral", action: "wait", args: { tag },
  lease_token: `t-${id}`, lease_expires_at: "",
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.pending.clear();
  mocks.drivers.clear();
  mocks.backend.claim.mockResolvedValue(null);
  mocks.backend.heartbeat.mockResolvedValue([]);
  mocks.backend.partitionMoves.mockResolvedValue([]);
});

afterEach(() => {
  stopBrowserWorker();
  vi.clearAllTimers();
  vi.useRealTimers();
});

it("一个会话上的长等待不挡别的会话:另一个会话的动作照样领、照样做完", async () => {
  mocks.backend.claim
    .mockResolvedValueOnce(action("a1", "s1", "long"))
    .mockResolvedValueOnce(action("b1", "s2", "quick"));
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(2_000);

  expect(mocks.execute).toHaveBeenCalledTimes(2); // 第一条还没做完,第二条已经开始了
  mocks.pending.get("quick")!();
  await vi.advanceTimersByTimeAsync(10);
  expect(mocks.backend.report).toHaveBeenCalledWith("b1", expect.objectContaining({ status: "done" }));
  expect(mocks.backend.report).not.toHaveBeenCalledWith("a1", expect.anything());
});

it("动作跑着的时候照样按时心跳(此前只在两个动作之间发,长等待把自己的租约熬过期)", async () => {
  mocks.backend.claim.mockResolvedValueOnce(action("a1", "s1", "long"));
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(1_000);
  const before = mocks.backend.heartbeat.mock.calls.length;
  await vi.advanceTimersByTimeAsync(70_000); // 一条跑了 70 秒的等待
  expect(mocks.execute).toHaveBeenCalledTimes(1);
  expect(mocks.backend.heartbeat.mock.calls.length - before).toBeGreaterThanOrEqual(3);
});

it("心跳说这条已经不归我了(后端不等了):中止它", async () => {
  mocks.backend.claim.mockResolvedValueOnce(action("a1", "s1", "long"));
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(1_000);
  const signal = mocks.drivers.get("s1")!.signal!;
  expect(signal.aborted).toBe(false);
  mocks.backend.heartbeat.mockResolvedValueOnce(["a1"]);
  await vi.advanceTimersByTimeAsync(20_000);
  expect(signal.aborted).toBe(true);
});

it("先搬完登录分区,再开始认领", async () => {
  const order: string[] = [];
  mocks.backend.partitionMoves.mockImplementation(async () => {
    order.push("moves");
    return [{ id: "m1", old_partition: "persist:rpa-xhs", new_partition: "persist:rpa-ws-0123456789abcdef" }];
  });
  mocks.backend.settlePartitionMove.mockImplementation(async () => {
    order.push("settle");
    return {};
  });
  mocks.backend.claim.mockImplementation(async () => {
    order.push("claim");
    return null;
  });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);
  expect(order.slice(0, 3)).toEqual(["moves", "settle", "claim"]);
  // 旧目录在测试机上不存在:记成 skipped 回报,而不是一直挂着
  expect(mocks.backend.settlePartitionMove).toHaveBeenCalledWith("m1", expect.objectContaining({ status: "skipped" }));
  expect(mocks.backend.partitionMoves).toHaveBeenCalledTimes(1);
});
