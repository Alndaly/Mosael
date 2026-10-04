/**
 * 浏览器执行器的调度:不同会话并发、心跳自己一条循环、续不上租约的动作被中止、先搬分区再认领。
 *
 * 真跑 browserWorker 的循环,只把它够不着的外部换掉:后端(browserBackend)、视图宿主(accountViews)、
 * 动作本身(executeBrowserAction —— 用一个能控制何时结束的假动作,调度才看得见)。
 */
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

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
    //: 每一步开一个下载收集器(见 actionDownloads);默认这一步没有下载
    downloads: { collect: vi.fn() },
    awaitingResponse: vi.fn(() => false),
    contentsOf: vi.fn((sessionId: string) => ({ id: `page-${sessionId}` })),
  };
  const backend = {
    claim: vi.fn(),
    report: vi.fn(async () => ({})),
    heartbeat: vi.fn(async (): Promise<string[]> => []),
    abandoned: vi.fn(async (): Promise<string[]> => []),
    partitionMoves: vi.fn(async () => [] as unknown[]),
    settlePartitionMove: vi.fn(async () => ({})),
    uploadArtifact: vi.fn(),
  };
  const pending = new Map<string, () => void>();
  //: 和真的 PageDriver 一样:中止开关一拨,手上的动作就抛出来
  const execute = vi.fn(
    (driver: { signal: AbortSignal | null }, _action: string, args: Record<string, unknown>) =>
      new Promise<{ lastUrl: string }>((resolve, reject) => {
        pending.set(String(args.tag), () => resolve({ lastUrl: "https://x.test/" }));
        driver.signal?.addEventListener("abort", () => reject(new Error("aborted")));
      }),
  );
  const paths = { userData: "" };
  const capture = vi.fn();
  return { drivers, views, backend, pending, execute, paths, capture };
});

vi.mock("electron", () => ({ app: { getPath: () => mocks.paths.userData } }));
vi.mock("./accountViews", () => ({ sharedViews: () => mocks.views }));
vi.mock("./browserBackend", () => ({ browserBackend: mocks.backend }));
vi.mock("./browserActions", () => ({ executeBrowserAction: mocks.execute }));
vi.mock("./actionCapture", () => ({ captureForAction: mocks.capture }));
vi.mock("./log", () => ({ plog: vi.fn() }));

import { startBrowserWorker, stopBrowserWorker } from "./browserWorker";
import { DownloadCollector, type CollectedDownload } from "./downloads";

const action = (id: string, session: string, tag: string) => ({
  id, session_id: session, partition: `ephemeral-${session}`, kind: "ephemeral", action: "wait", args: { tag },
  lease_token: `t-${id}`, lease_expires_at: "",
});

beforeEach(() => {
  mocks.paths.userData = mkdtempSync(join(tmpdir(), "mosael-worker-"));
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.pending.clear();
  mocks.drivers.clear();
  mocks.backend.claim.mockResolvedValue(null);
  mocks.backend.heartbeat.mockResolvedValue([]);
  mocks.backend.abandoned.mockResolvedValue([]);
  mocks.backend.partitionMoves.mockResolvedValue([]);
  mocks.views.downloads.collect.mockImplementation(() => new DownloadCollector(() => undefined));
});

afterEach(() => {
  stopBrowserWorker();
  vi.clearAllTimers();
  vi.useRealTimers();
  rmSync(mocks.paths.userData, { recursive: true, force: true });
});

/** 这台电脑上有那份旧登录。 */
const seedOldLogin = (dir: string) => mkdirSync(join(mocks.paths.userData, "Partitions", dir), { recursive: true });

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

it("后端放弃了这条(运行停下、超时):认领循环下一拍就中止它,不等 20 秒一次的心跳", async () => {
  mocks.backend.claim.mockResolvedValueOnce(action("a1", "s1", "long"));
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(1_000);
  const signal = mocks.drivers.get("s1")!.signal!;
  mocks.backend.abandoned.mockResolvedValueOnce(["a1"]);
  await vi.advanceTimersByTimeAsync(1_500);
  expect(signal.aborted).toBe(true);
  expect(mocks.backend.heartbeat.mock.calls.length).toBeLessThanOrEqual(1); // 不是心跳发现的
});

it("被放弃的那条一停,同一会话上排在它后面的失败现场截图马上开始", async () => {
  mocks.backend.claim
    .mockResolvedValueOnce(action("a1", "s1", "long"))
    .mockResolvedValueOnce({ ...action("a2", "s1", "shot"), action: "screenshot" });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(1_000);
  expect(mocks.execute).toHaveBeenCalledTimes(1); // 截图排在 a1 后面
  mocks.backend.abandoned.mockResolvedValueOnce(["a1"]);
  await vi.advanceTimersByTimeAsync(1_500);
  expect(mocks.execute).toHaveBeenCalledTimes(2);
  expect(mocks.execute.mock.calls[1][1]).toBe("screenshot");
});

it("先搬完登录分区,再开始认领", async () => {
  seedOldLogin("rpa-xhs");
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
  expect(mocks.backend.settlePartitionMove).toHaveBeenCalledWith("m1", { status: "done", reason: "" });
  expect(mocks.backend.partitionMoves).toHaveBeenCalledTimes(1);
});

it("旧目录不在这台电脑上:不回话(别的电脑还要搬),照常开始认领", async () => {
  mocks.backend.partitionMoves.mockResolvedValue([
    { id: "m1", old_partition: "persist:rpa-nothere", new_partition: "persist:rpa-ws-0123456789abcdef" },
  ]);
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);
  expect(mocks.backend.settlePartitionMove).not.toHaveBeenCalled();
  expect(mocks.backend.claim).toHaveBeenCalled();
});

it("搬家因为分区正被用着推迟了:搬成之前不在新分区上开视图,动作报失败说清原因", async () => {
  //: 同一进程里执行器重启过:上一轮用过旧分区,这一轮后端刚写下搬家单
  seedOldLogin("rpa-xhs");
  mocks.backend.claim.mockResolvedValueOnce({ ...action("a0", "s0", "warm"), partition: "persist:rpa-xhs" });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(1_500);
  mocks.pending.get("warm")!();
  await vi.advanceTimersByTimeAsync(10);
  stopBrowserWorker();

  mocks.backend.partitionMoves.mockResolvedValue([
    { id: "m1", old_partition: "persist:rpa-xhs", new_partition: "persist:rpa-ws-0123456789abcdef" },
  ]);
  mocks.backend.claim.mockResolvedValueOnce({ ...action("a1", "s1", "x"), partition: "persist:rpa-ws-0123456789abcdef" });
  mocks.views.registerSession.mockClear();
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);

  expect(mocks.backend.settlePartitionMove).not.toHaveBeenCalled();
  expect(mocks.views.registerSession).not.toHaveBeenCalled();
  expect(mocks.backend.report).toHaveBeenCalledWith("a1", expect.objectContaining({ status: "failed" }));
});

/** 这一步做的时候,浏览器开始了这些下载(每一份都已经有了结局)。 */
function stepDownloads(...outcomes: CollectedDownload[]) {
  mocks.views.downloads.collect.mockImplementationOnce(() => {
    const collector = new DownloadCollector(() => undefined);
    for (const outcome of outcomes) collector.add(Promise.resolve(outcome), () => undefined);
    return collector;
  });
}

function downloaded(name: string, content = "pdf") {
  const dir = mkdtempSync(join(mocks.paths.userData, "dl-"));
  const path = join(dir, name);
  writeFileSync(path, content);
  return {
    ok: true as const,
    file: {
      id: "d1", path, name, bytes: content.length, sourceUrl: `https://example.com/${name}`,
      pageUrl: "https://example.com/files", pageTitle: "下载页", startedAt: "2026-10-04T05:30:00.000Z",
    },
  };
}

it("点开了一个下载:不弹保存框,文件交给后端进素材库,素材 id 放进这一步的结果,临时文件删掉", async () => {
  const file = downloaded("report.pdf");
  stepDownloads(file);
  mocks.execute.mockImplementationOnce(async () => ({ lastUrl: "https://example.com/files" }));
  mocks.backend.uploadArtifact.mockResolvedValueOnce({ asset_id: "asset-1", name: "report.pdf", kind: "document" });
  mocks.backend.claim.mockResolvedValueOnce({ ...action("a1", "s1", "x"), action: "click" });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);

  expect(mocks.backend.uploadArtifact).toHaveBeenCalledWith(
    "a1",
    "download",
    { body: expect.any(Blob), filename: "report.pdf" },
    {
      filename: "report.pdf",
      source_url: "https://example.com/report.pdf",
      page_url: "https://example.com/files",
      page_title: "下载页",
      captured_at: "2026-10-04T05:30:00.000Z",
    },
  );
  expect(mocks.backend.report).toHaveBeenCalledWith("a1", {
    status: "done",
    result: { downloads: [{ asset_id: "asset-1", name: "report.pdf", bytes: 3 }] },
    last_url: "https://example.com/files",
  });
  expect(existsSync(file.file.path)).toBe(false);
});

it("点开的下载素材库不收(类型不对 / 超过上限):这一步失败,说清为什么", async () => {
  stepDownloads({ ok: false, name: "setup.exe", error: "素材库不收这种文件:「setup.exe」" });
  mocks.execute.mockImplementationOnce(async () => ({ lastUrl: "https://example.com/files" }));
  mocks.backend.claim.mockResolvedValueOnce({ ...action("a1", "s1", "x"), action: "click" });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);

  expect(mocks.backend.uploadArtifact).not.toHaveBeenCalled();
  expect(mocks.backend.report).toHaveBeenCalledWith("a1", {
    status: "failed",
    error: expect.stringContaining("setup.exe"),
  });
});

it("后端拒收(入库那道闸):这一步失败,带着后端那句话", async () => {
  const file = downloaded("clip.mp4");
  stepDownloads(file);
  mocks.execute.mockImplementationOnce(async () => ({ lastUrl: "https://example.com/files" }));
  const { UploadRefused } = await import("./downloadUpload");
  mocks.backend.uploadArtifact.mockRejectedValueOnce(new UploadRefused(413, "下载的文件太大了:最多 2.0 GB。"));
  mocks.backend.claim.mockResolvedValueOnce({ ...action("a1", "s1", "x"), action: "click" });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);

  expect(mocks.backend.report).toHaveBeenCalledWith("a1", {
    status: "failed",
    error: expect.stringMatching(/clip\.mp4.*最多 2\.0 GB/),
  });
  expect(existsSync(file.file.path)).toBe(false);
});

it("动作自己失败了:这一步开始的下载一并丢掉,不进素材库", async () => {
  const file = downloaded("report.pdf");
  stepDownloads(file);
  mocks.execute.mockImplementationOnce(async () => {
    throw new Error("元素未找到");
  });
  mocks.backend.claim.mockResolvedValueOnce({ ...action("a1", "s1", "x"), action: "click" });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);

  expect(mocks.backend.uploadArtifact).not.toHaveBeenCalled();
  expect(mocks.backend.report).toHaveBeenCalledWith("a1", { status: "failed", error: "元素未找到" });
  expect(existsSync(file.file.path)).toBe(false);
});

it("「截图」动作截这一页(交给截图那一份实现),结果里带着素材 id", async () => {
  mocks.capture.mockResolvedValueOnce({ value: { asset_id: "shot-1", width: 10, height: 10 }, lastUrl: "https://x.test/" });
  mocks.backend.claim.mockResolvedValueOnce({ ...action("a1", "s1", "x"), action: "capture", args: { mode: "element", selector: "h1" } });
  startBrowserWorker();
  await vi.advanceTimersByTimeAsync(3_000);

  expect(mocks.execute).not.toHaveBeenCalled();
  expect(mocks.capture).toHaveBeenCalledWith({ actionId: "a1", webContents: { id: "page-s1" }, args: { mode: "element", selector: "h1" } });
  expect(mocks.backend.report).toHaveBeenCalledWith("a1", {
    status: "done",
    result: { value: { asset_id: "shot-1", width: 10, height: 10 } },
    last_url: "https://x.test/",
  });
});
