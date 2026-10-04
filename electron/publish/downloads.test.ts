/**
 * 内嵌浏览器里的下载怎么接:不弹保存框(will-download 里同步定路径)、按「谁触发的」分两路交出去。
 *
 * 真跑 DownloadRouter / DownloadCollector,只把 Electron 的会话和下载项换成会记账的假货:下载项的
 * 保存路径、有没有被取消、下好的文件落在哪,就是要验的东西。
 */
import { EventEmitter } from "node:events";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./log", () => ({ plog: vi.fn() }));

const { DownloadRouter, discardDownload } = await import("./downloads");
type Notice = import("./downloads").DownloadNotice;

class FakeItem extends EventEmitter {
  savePath = "";
  cancelled = false;
  received = 0;
  constructor(
    private readonly filename: string,
    private readonly total: number,
    private readonly url: string,
  ) {
    super();
  }
  getFilename() {
    return this.filename;
  }
  getTotalBytes() {
    return this.total;
  }
  getReceivedBytes() {
    return this.received;
  }
  getURL() {
    return this.url;
  }
  setSavePath(target: string) {
    this.savePath = target;
  }
  cancel() {
    if (this.cancelled) return;
    this.cancelled = true;
    this.emit("done", {}, "cancelled");
  }
  progress(bytes: number) {
    this.received = bytes;
    this.emit("updated", {}, "progressing");
  }
  finish(content: string) {
    fs.writeFileSync(this.savePath, content);
    this.received = content.length;
    this.emit("done", {}, "completed");
  }
}

const page = (id: number, url = "https://example.com/files", title = "下载页") => ({
  id,
  isDestroyed: () => false,
  getURL: () => url,
  getTitle: () => title,
});

let root: string;
let notices: Notice[];
let session: EventEmitter;
let router: InstanceType<typeof DownloadRouter>;

/** 页面 1 是会话 s1 的,页面 2 是 s2 的,别的认不出。 */
const owners = new Map([
  [1, "s1"],
  [2, "s2"],
]);

function start(item: FakeItem, wc = page(1)) {
  session.emit("will-download", {}, item, wc);
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-downloads-"));
  notices = [];
  session = new EventEmitter();
  router = new DownloadRouter(
    (wc) => owners.get(wc.id) ?? null,
    (notice) => notices.push(notice),
    path.join(root, "web-downloads"),
  );
  router.watch(session as never);
});

afterEach(() => {
  vi.useRealTimers();
  fs.rmSync(root, { recursive: true, force: true });
});

describe("人点的下载", () => {
  it("同步定好临时路径(不弹保存框),下好了告诉渲染层,渲染层来取的是带着出处的那份文件", async () => {
    const item = new FakeItem("报告.pdf", 12, "https://cdn.example.com/r.pdf?sig=1");
    start(item);
    // will-download 一返回就定好了路径 —— 定了路径 Chromium 就不弹框。
    expect(item.savePath).toMatch(/web-downloads[\\/][0-9a-f-]{36}[\\/]报告\.pdf$/);
    item.finish("hello world!");
    await vi.waitFor(() => expect(notices.at(-1)?.state).toBe("ready"));
    const ready = notices.at(-1)!;
    expect(ready.name).toBe("报告.pdf");
    const file = router.take(ready.id)!;
    expect(file).toMatchObject({
      name: "报告.pdf",
      bytes: 12,
      sourceUrl: "https://cdn.example.com/r.pdf?sig=1",
      pageUrl: "https://example.com/files",
      pageTitle: "下载页",
    });
    expect(fs.readFileSync(file.path, "utf8")).toBe("hello world!");
    expect(router.take(ready.id)).toBeNull(); // 取走就没了
    discardDownload(file);
    expect(fs.existsSync(path.dirname(file.path))).toBe(false);
  });

  it("素材库不收的类型:当场取消,告诉渲染层为什么,临时目录不留", async () => {
    const item = new FakeItem("setup.exe", 10, "https://example.com/setup.exe");
    start(item);
    expect(item.cancelled).toBe(true);
    await vi.waitFor(() => expect(notices.at(-1)?.state).toBe("failed"));
    expect(notices.at(-1)!.error).toContain("setup.exe");
    expect(fs.readdirSync(path.join(root, "web-downloads"))).toEqual([]);
  });

  it("服务端没报总长的,边下边数:一过上限就停", async () => {
    const { MAX_DOWNLOAD_BYTES } = await import("./downloadRules");
    const item = new FakeItem("clip.mp4", 0, "https://example.com/clip.mp4");
    start(item);
    expect(item.cancelled).toBe(false);
    item.progress(MAX_DOWNLOAD_BYTES + 1);
    expect(item.cancelled).toBe(true);
    await vi.waitFor(() => expect(notices.at(-1)?.state).toBe("failed"));
    expect(notices.at(-1)!.error).toMatch(/2 GB/);
  });

  it("blob: 下载没有能记的来源地址;新会话直接打开文件地址时,页面记下载地址本身", async () => {
    const blob = new FakeItem("a.png", 3, "blob:https://example.com/1");
    start(blob);
    blob.finish("png");
    await vi.waitFor(() => expect(notices.some((n) => n.state === "ready")).toBe(true));
    expect(router.take(notices.find((n) => n.state === "ready")!.id)).toMatchObject({
      sourceUrl: "",
      pageUrl: "https://example.com/files",
    });

    notices = [];
    const direct = new FakeItem("clip.mp4", 3, "https://cdn.example.com/clip.mp4");
    start(direct, page(1, "about:blank", ""));
    direct.finish("mp4");
    await vi.waitFor(() => expect(notices.some((n) => n.state === "ready")).toBe(true));
    expect(router.take(notices.find((n) => n.state === "ready")!.id)).toMatchObject({
      sourceUrl: "https://cdn.example.com/clip.mp4",
      pageUrl: "https://cdn.example.com/clip.mp4",
    });
  });

  it("下好了没人来取,十分钟后删掉", async () => {
    vi.useFakeTimers();
    const item = new FakeItem("a.png", 3, "https://example.com/a.png");
    start(item);
    item.finish("png");
    await vi.waitFor(() => expect(notices.at(-1)?.state).toBe("ready"));
    const dir = path.dirname(item.savePath);
    expect(fs.existsSync(dir)).toBe(true);
    await vi.advanceTimersByTimeAsync(10 * 60_000 + 1);
    expect(fs.existsSync(dir)).toBe(false);
    expect(router.take(notices.at(-1)!.id)).toBeNull();
  });

  it("上次运行没交出去的临时文件,这次启动时清掉", () => {
    const leftover = path.join(root, "web-downloads", "old");
    fs.mkdirSync(leftover, { recursive: true });
    fs.writeFileSync(path.join(leftover, "x.mp4"), "x");
    new DownloadRouter(() => null, () => undefined, path.join(root, "web-downloads"));
    expect(fs.existsSync(leftover)).toBe(false);
  });
});

describe("自动化动作里的下载", () => {
  it("动作期间开始的下载归这一步,不告诉渲染层;收尾时等它下完", async () => {
    const collector = router.collect("s1");
    const item = new FakeItem("data.csv", 4, "https://example.com/data.csv");
    start(item);
    setTimeout(() => item.finish("a,b\n"), 50);
    const collected = await collector.settle({ graceMs: 0 });
    expect(collected).toHaveLength(1);
    expect(collected[0]).toMatchObject({ ok: true, file: { name: "data.csv", bytes: 4 } });
    expect(notices).toEqual([]);
  });

  it("点完之后隔一拍才开始的下载也归这一步(等一小会儿)", async () => {
    const collector = router.collect("s1");
    setTimeout(() => {
      const item = new FakeItem("late.pdf", 3, "https://example.com/late.pdf");
      start(item);
      item.finish("pdf");
    }, 60);
    const collected = await collector.settle({ graceMs: 300 });
    expect(collected.map((one) => one.ok && one.file.name)).toEqual(["late.pdf"]);
  });

  it("页面还在等主文档响应(链接可能正要变成下载)就接着等", async () => {
    const collector = router.collect("s1");
    let waiting = true;
    setTimeout(() => {
      const item = new FakeItem("big.mp4", 3, "https://example.com/big.mp4");
      start(item);
      waiting = false;
      item.finish("mp4");
    }, 400);
    const collected = await collector.settle({ graceMs: 0, stillLoading: () => waiting, maxLoadingMs: 3_000 });
    expect(collected).toHaveLength(1);
  });

  it("收尾之后再开始的下载不归这一步,当成人点的", async () => {
    const collector = router.collect("s1");
    await collector.settle({ graceMs: 0 });
    const item = new FakeItem("after.png", 3, "https://example.com/after.png");
    start(item);
    item.finish("png");
    await vi.waitFor(() => expect(notices.at(-1)?.state).toBe("ready"));
  });

  it("别的会话里的下载不归这一步", async () => {
    const collector = router.collect("s1");
    const other = new FakeItem("other.png", 3, "https://example.com/other.png");
    start(other, page(2));
    other.finish("png");
    expect(await collector.settle({ graceMs: 0 })).toEqual([]);
    await vi.waitFor(() => expect(notices.at(-1)?.state).toBe("ready"));
  });

  it("类型不收的照样当场取消,收尾时交出那句人话", async () => {
    const collector = router.collect("s1");
    const item = new FakeItem("setup.exe", 3, "https://example.com/setup.exe");
    start(item);
    expect(item.cancelled).toBe(true);
    const [one] = await collector.settle({ graceMs: 0 });
    expect(one.ok).toBe(false);
    expect(!one.ok && one.error).toContain("setup.exe");
  });

  it("中止了(运行停下)就把还在下的取消掉", async () => {
    const collector = router.collect("s1");
    const item = new FakeItem("slow.mp4", 0, "https://example.com/slow.mp4");
    start(item);
    const controller = new AbortController();
    const settled = collector.settle({ graceMs: 0, signal: controller.signal });
    controller.abort();
    const [one] = await settled;
    expect(item.cancelled).toBe(true);
    expect(one.ok).toBe(false);
  });
});
