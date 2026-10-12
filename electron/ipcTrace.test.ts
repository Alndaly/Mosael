/**
 * 「进插件页后那 27 秒里,页面隔着 Electron 桥做了什么」—— 这套追踪自己的规矩。
 *
 * 照 mainDiagnostics.test.ts / memoryDiagnostics.test.ts 的用法:把 main.cjs 里的代码段**抠出来真跑**,只喂桩
 * —— 不启动 Electron,也不会为了测试去崩一次应用。这里钉四件事:
 *   1. 行里有什么(`local/seq/dir/channel/from/bytes/n/dt/skipped/url`),而且**参数只有大小、没有内容**
 *      (IPC 参数里带着登录 token 和整份插件目录 JSON,进日志就是把凭据抄一遍);
 *   2. 同一通道按秒聚合:`n` 是累计次数、`skipped` 是被压掉的条数 —— 「每秒几十次」读得出来,日志却不被刷爆;
 *   3. 崩的那一刻,最近 40 条真的取得回来,而且每条带「距崩溃多少毫秒」;
 *   4. 关掉(`MOSAEL_IPC_TRACE=0`)时一行都不写、连 `.then` 都不挂(零开销是那一档的承诺)。
 *
 * 外加一件查这条线最实用的东西:`preload.cjs` 的**桥方法 ↔ channel 对照表**。它不是手抄的 —— 这里跑真的
 * preload.cjs(喂一座假的 electron),把 69 个桥方法各调一次、记下它用的是哪条 channel。于是「日志里那条
 * channel 对应页面上的哪个调用」永远对得上,而且 preload 加了新方法、契约里加了新 channel,这里会先红。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it } from "vitest";

const MAIN = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8");
const PRELOAD = fs.readFileSync(path.join(__dirname, "preload.cjs"), "utf8");

// CommonJS is intentional: preload.cjs 加载的就是这两个运行时模块本身。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const CONTRACT = require("./ipc-contract.cjs") as {
  IPC: { invoke: Record<string, string>; send: Record<string, string>; event: Record<string, string> };
};
const IPC = CONTRACT.IPC;

/** 从 main.cjs 里抠出一段源码来单独跑(和 mainDiagnostics.test.ts 同一个用法)。 */
function extract(pattern: RegExp, what: string) {
  const source = MAIN.match(pattern)?.[0];
  if (!source) throw new Error(`${what} not found in main.cjs`);
  return source;
}

const TRACE = extract(/\/\/ ─+ IPC 追踪\(只读诊断\)[\s\S]*?\/\/ ─+ IPC 追踪结束 ─+\n/, "IPC trace block");
const HANDLE = extract(/\nfunction handle\(channel, listener\) \{[\s\S]*?\n\}\n/, "handle");
const LISTEN = extract(/\nfunction listen\(channel, listener\) \{[\s\S]*?\n\}\n/, "listen");

type LogLine = { kind: string; text: string };
type Call = (event: unknown, ...args: unknown[]) => unknown;

const EXPOSED = [
  "this.handle = handle;",
  "this.listen = listen;",
  "this.sendToRenderer = sendToRenderer;",
  "this.appendIpcTraceAtCrash = appendIpcTraceAtCrash;",
  "this.ipcPayloadBytes = ipcPayloadBytes;",
  "this.ipcTraceMode = ipcTraceMode;",
  "this.ipcTraceUrl = ipcTraceUrl;",
  "this.appendIpcRateSummary = appendIpcRateSummary;",
].join("\n");

/**
 * 一次「主进程侧」的会话:只桩掉 ipcMain 与日志出口,其余跑 main.cjs 里真的那段代码。
 * 时钟是假的 —— `dt=` / `skipped=` / `ms=` 要钉死,真时钟下这些断言只能靠 sleep。
 */
function harness(mode: string | undefined) {
  const clock = { now: Date.UTC(2026, 0, 2, 3, 4, 5) };
  const lines: LogLine[] = [];
  const mainLines: LogLine[] = [];
  const handlers = new Map<string, Call>();
  const listeners = new Map<string, Call>();
  const refused: string[] = [];
  const sent: { channel: string; payload: unknown[] }[] = [];

  class FakeDate extends Date {
    constructor(value?: number) {
      super(value ?? clock.now);
    }
    static now(): number {
      return clock.now;
    }
  }

  const context: Record<string, unknown> = {
    Buffer,
    Date: FakeDate,
    process: { env: mode === undefined ? {} : { MOSAEL_IPC_TRACE: mode }, pid: 4242 },
    ipcMain: {
      handle: (channel: string, listener: Call) => handlers.set(channel, listener),
      on: (channel: string, listener: Call) => listeners.set(channel, listener),
    },
    fromAppWindow: () => true,
    refusedSender: (channel: string) => refused.push(channel),
    appendDiagnosticLog: (kind: string, detail: string | (() => string)) => {
      // 和真的 appendDiagnosticLog 一样:空串不写。
      const text = typeof detail === "function" ? detail() : detail;
      if (text) lines.push({ kind, text });
    },
    appendMainLog: (kind: string, detail: string) => mainLines.push({ kind, text: String(detail) }),
    localClock: (date = new FakeDate()) => date.toTimeString().slice(0, 8),
  };
  vm.runInNewContext([TRACE, HANDLE, LISTEN, EXPOSED].join("\n"), context);
  const globals = context as unknown as {
    handle: (channel: string, listener: Call) => void;
    listen: (channel: string, listener: Call) => void;
    sendToRenderer: (contents: unknown, channel: string, ...payload: unknown[]) => unknown;
    appendIpcTraceAtCrash: (details: unknown) => void;
    ipcPayloadBytes: (payload: unknown) => { bytes: number; capped: boolean };
    ipcTraceMode: (env: Record<string, string> | undefined) => string;
    ipcTraceUrl: (raw: unknown) => string;
    appendIpcRateSummary: () => void;
  };

  const eventFor = (url: string) => ({ sender: { id: 7, getURL: () => url }, senderFrame: { url } });
  const callWith = (table: Map<string, Call>, channel: string, event: unknown, args: unknown[]) => {
    const fn = table.get(channel);
    if (!fn) throw new Error(`${channel} was never registered through handle/listen`);
    return fn(event, ...args);
  };

  return {
    clock,
    lines,
    mainLines,
    refused,
    sent,
    globals,
    of: (kind: string) => lines.filter((line) => line.kind === kind),
    first: (kind: string) => lines.find((line) => line.kind === kind),
    /** 页面经 `mosaelX.foo()` 打过来的一次调用(主框架停在 #/plugins)。 */
    invoke: (channel: string, ...args: unknown[]) => callWith(handlers, channel, eventFor("http://127.0.0.1:5173/#/plugins"), args),
    /** 页面经 `ipcRenderer.send` 打过来的一次单向消息。 */
    send: (channel: string, ...args: unknown[]) => callWith(listeners, channel, eventFor("http://127.0.0.1:5173/#/plugins"), args),
    invokeFrom: (event: unknown, channel: string, ...args: unknown[]) => callWith(handlers, channel, event, args),
    push: (contents: unknown, channel: string, ...payload: unknown[]) => {
      const clone = { id: (contents as { id: number }).id, getURL: () => "http://127.0.0.1:5173/#/plugins", send: (sent2: string, ...rest: unknown[]) => sent.push({ channel: sent2, payload: rest }) };
      return globals.sendToRenderer(contents === null ? null : clone, channel, ...payload);
    },
    crash: (details: unknown = { reason: "crashed", exitCode: 5 }) => globals.appendIpcTraceAtCrash(details),
  };
}

describe("IPC 追踪:一行里有什么", () => {
  it("一次调用一行,字段齐:local / seq / dir / channel / from / bytes / n / dt / skipped / url", () => {
    const h = harness("1");
    h.globals.handle("publish:reload", () => "done");

    expect(h.invoke("publish:reload", { token: "s3cr3t-token" })).toBe("done");

    expect(h.of("ipc")).toHaveLength(1);
    expect(h.first("ipc")?.text).toMatch(
      /^local=\d\d:\d\d:\d\d seq=1 dir=invoke channel=publish:reload from=7 bytes=17 n=1 dt=- skipped=0 url=http:\/\/127\.0\.0\.1:5173\/#\/plugins$/,
    );
  });

  it("只记大小、不记内容:字符串只贡献 UTF-8 字节数,键名和值都不进日志", () => {
    const h = harness("1");
    h.globals.handle("data:createBackup", () => undefined);
    // 键 "token" 5 字节 + 值 12 字节 = 17;容器本身不计。
    expect(h.globals.ipcPayloadBytes([{ token: "s3cr3t-token" }])).toEqual({ bytes: 17, capped: false });
    // 中文按 UTF-8 算,不按字符数。
    expect(h.globals.ipcPayloadBytes(["中文"])).toEqual({ bytes: 6, capped: false });

    h.invoke("data:createBackup", { token: "s3cr3t-token" });
    const line = h.first("ipc")?.text ?? "";
    expect(line).toContain("bytes=17");
    expect(line).not.toContain("s3cr3t");
    expect(line).not.toContain("token");
  });

  it("量不动的参数不许把 IPC 本身弄挂:巨大、循环、会抛的 getter 都有兜", () => {
    const h = harness("1");
    const huge = h.globals.ipcPayloadBytes({ big: "a".repeat(200_000) });
    expect(huge.capped).toBe(true);
    expect(huge.bytes).toBe(64 * 1024);
    const cyclic: Record<string, unknown> = { name: "loop" };
    cyclic.self = cyclic;
    expect(h.globals.ipcPayloadBytes(cyclic)).toEqual({ bytes: 12, capped: true }); // name=loop 8 + self 这个键 4,再往里就停了
    const hostile = { get boom(): string { throw new Error("getter"); } };
    expect(h.globals.ipcPayloadBytes(hostile)).toEqual({ bytes: 0, capped: true });
  });

  it("URL 去掉 query、留下路由(#/plugins 是这次要认的东西,壳令牌在 query 里)", () => {
    const h = harness("1");
    h.globals.handle("customCss:read", () => "");
    expect(h.globals.ipcTraceUrl("http://127.0.0.1:5173/?token=leak#/plugins")).toBe("http://127.0.0.1:5173/#/plugins");

    h.invokeFrom({ sender: { id: 9, getURL: () => "http://127.0.0.1:5173/#/ai" }, senderFrame: { url: "http://127.0.0.1:5173/?token=leak#/plugins" } }, "customCss:read");
    const line = h.of("ipc")[0].text;
    expect(line).toContain("from=9");
    expect(line).toContain("url=http://127.0.0.1:5173/#/plugins");
    expect(line).not.toContain("leak");

    // 框架已经没了(senderFrame 会抛):退回 sender.getURL(),不许把这次 IPC 带走。
    h.clock.now += 1000;
    h.invokeFrom(
      {
        sender: { id: 11, getURL: () => "http://127.0.0.1:5173/#/ai" },
        get senderFrame(): never {
          throw new Error("frame gone");
        },
      },
      "customCss:read",
    );
    expect(h.of("ipc")[1].text).toContain("from=11");
    expect(h.of("ipc")[1].text).toContain("url=http://127.0.0.1:5173/#/ai");
  });

  it("推给页面的事(push)也进现场:记的是 to 与载荷大小", () => {
    const h = harness("1");
    h.push({ id: 3 }, "comfyui:workbench", { state: "dirty" });
    expect(h.first("ipc")?.text).toContain("dir=push channel=comfyui:workbench to=3 bytes=10");
    expect(h.sent).toEqual([{ channel: "comfyui:workbench", payload: [{ state: "dirty" }] }]);
  });
});

describe("IPC 追踪:按通道聚合(不聚合会把日志和时序一起毁掉)", () => {
  it("同一通道最快 1 秒一行:n 是累计次数,skipped 是这一秒里被压掉的条数", () => {
    const h = harness("1");
    h.globals.handle("publish:panels", () => undefined);
    for (let i = 0; i < 5; i += 1) h.invoke("publish:panels");
    expect(h.of("ipc")).toHaveLength(1);
    expect(h.first("ipc")?.text).toContain("n=1 dt=- skipped=0");

    h.clock.now += 1000;
    h.invoke("publish:panels");
    expect(h.of("ipc")).toHaveLength(2);
    expect(h.of("ipc")[1].text).toContain("n=6 dt=1000 skipped=4");
  });

  it("别的通道有自己的门:一个通道在轮询,不会把另一个通道的行压掉", () => {
    const h = harness("1");
    h.globals.handle("publish:panels", () => undefined);
    h.globals.handle("customCss:read", () => "");
    h.invoke("publish:panels");
    h.invoke("customCss:read");
    h.invoke("customCss:read");
    expect(h.of("ipc").map((line) => line.text.includes("channel=customCss:read"))).toEqual([false, true]);
  });

  it("每 10 毫秒一次(每秒上百次)的轮询:200 次调用只有 2 行,频率从 n 上读得出来", () => {
    const h = harness("1");
    h.globals.handle("pageTools:images", () => undefined);
    for (let i = 0; i < 200; i += 1) {
      h.clock.now += 10;
      h.invoke("pageTools:images");
    }
    expect(h.of("ipc")).toHaveLength(2);
    expect(h.of("ipc")[0].text).toContain("dir=invoke channel=pageTools:images from=7");
    expect(h.of("ipc")[1].text).toContain("n=101 dt=1000 skipped=99");
  });
});

describe("IPC 追踪:崩的那一刻", () => {
  it("默认档(不设开关)只进环、不写盘,但崩溃时最近 40 条照样打得出来", () => {
    const h = harness(undefined);
    h.globals.handle("customCss:read", () => "css");
    for (let i = 0; i < 50; i += 1) {
      h.clock.now += 10;
      h.invoke("customCss:read");
    }
    // 一个字节都没写盘(只有开机那一行 mode=...)。
    expect(h.of("ipc")).toEqual([]);
    expect(h.mainLines.map((line) => line.text)).toEqual([expect.stringContaining("mode=ring")]);

    h.clock.now += 250;
    h.crash({ reason: "crashed", exitCode: 5 });

    expect(h.of("ipc-at-crash")).toHaveLength(1);
    const payload = JSON.parse(h.first("ipc-at-crash")?.text ?? "{}");
    expect(payload).toMatchObject({
      reason: "crashed",
      exitCode: 5,
      mode: "ring",
      total: 50,
      channels: 1,
      top: [{ channel: "customCss:read", n: 50 }],
      lastAgoMs: 250,
    });
    expect(payload.ring).toHaveLength(40);
    // 最老的 10 条被顶掉;每条带「距崩溃多少毫秒」(负数 = 崩之前)与它自己的读数。
    expect(payload.ring[0]).toMatchObject({ seq: 11, dir: "invoke", channel: "customCss:read", from: 7, n: 11, t: -640, ms: 0, outcome: "ok" });
    expect(payload.ring[39]).toMatchObject({ seq: 50, n: 50, t: -250 });
    expect(payload.ring[39].local).toMatch(/^\d\d:\d\d:\d\d$/);
    expect(payload.ring[39].url).toBe("http://127.0.0.1:5173/#/plugins");
    // 40 条 × 10 毫秒 = 390 毫秒:窗口跨度要说清楚,免得把「最近 40 条」读成「临死前那几秒」。
    expect(payload.windowSec).toBe(0);
  });

  it("桥上一片安静也是结论:环空着照样写一行,lastAgoMs 说明「崩之前桥早就没说话了」", () => {
    const h = harness(undefined);
    h.crash({ reason: "crashed", exitCode: 5 });
    const payload = JSON.parse(h.first("ipc-at-crash")?.text ?? "{}");
    expect(payload).toMatchObject({ total: 0, channels: 0, top: [], lastAgoMs: null, windowSec: null, ring: [] });
  });

  it("每 30 秒一行频率汇总:这一窗口的增量 + 前 5 个通道;安静时一行不写", () => {
    const h = harness("1");
    h.globals.handle("pageTools:images", () => undefined);
    h.globals.handle("customCss:read", () => "");
    h.globals.appendIpcRateSummary();
    expect(h.of("ipc-rate")).toEqual([]); // 谁都没说话(也没有通道),不留痕迹

    for (let i = 0; i < 5; i += 1) h.invoke("pageTools:images");
    h.invoke("customCss:read");
    h.globals.appendIpcRateSummary();
    expect(h.of("ipc-rate")).toHaveLength(1);
    expect(h.of("ipc-rate")[0].text).toMatch(
      /^local=\d\d:\d\d:\d\d calls=6 channels=2 top=pageTools:images=5 customCss:read=1$/,
    );

    h.globals.appendIpcRateSummary();
    expect(h.of("ipc-rate")).toHaveLength(1); // 这一窗口什么都没有

    h.clock.now += 30_000;
    h.invoke("customCss:read");
    h.globals.appendIpcRateSummary();
    expect(h.of("ipc-rate")[1].text).toContain("calls=1 channels=1 top=customCss:read=1");
  });

  it("频率汇总只在 trace 档写(默认档一个字节都不落盘)", () => {
    const h = harness(undefined);
    h.globals.handle("customCss:read", () => "");
    h.invoke("customCss:read");
    h.globals.appendIpcRateSummary();
    expect(h.of("ipc-rate")).toEqual([]);
  });

  it("频率排行只列前 5 个通道(崩的那一条里就是它)", () => {
    const h = harness(undefined);
    for (const channel of ["a:1", "b:2", "c:3", "d:4", "e:5", "f:6"]) {
      h.globals.handle(channel, () => undefined);
      for (let i = 0; i < 6 - Number(channel.slice(2)); i += 1) h.invoke(channel);
    }
    h.crash();
    const payload = JSON.parse(h.first("ipc-at-crash")?.text ?? "{}");
    expect(payload.total).toBe(15);
    expect(payload.channels).toBe(5); // f:6 一次都没调过,不进计数表
    expect(payload.top).toEqual([
      { channel: "a:1", n: 5 },
      { channel: "b:2", n: 4 },
      { channel: "c:3", n: 3 },
      { channel: "d:4", n: 2 },
      { channel: "e:5", n: 1 },
    ]);
  });
});

describe("IPC 追踪:慢的、报错的", () => {
  it("异步处理器跑完补 ms;慢的单独一行,交还给 Electron 的还是原来那个 promise", async () => {
    const h = harness("1");
    let finish!: (value: string) => void;
    const pending = new Promise<string>((resolve) => {
      finish = resolve;
    });
    h.globals.handle("data:createBackup", () => pending);

    const returned = h.invoke("data:createBackup");
    expect(returned).toBe(pending); // 没被包成另一个 promise:reject 的时机与归属都不许改
    expect(h.of("ipc")).toHaveLength(1);
    expect(h.of("ipc-slow")).toEqual([]); // 还没跑完,先不猜它慢不慢

    h.clock.now += 300;
    finish("ok");
    await pending;
    await Promise.resolve();

    expect(h.of("ipc-slow")).toHaveLength(1);
    expect(h.first("ipc-slow")?.text).toMatch(/local=\d\d:\d\d:\d\d seq=1 dir=invoke channel=data:createBackup ms=300 from=7 bytes=0 url=/);
  });

  it("同步抛:记一行 outcome=throw,然后原样抛回去", () => {
    const h = harness("1");
    h.globals.handle("pageTools:capture", () => {
      throw new Error("no page");
    });
    expect(() => h.invoke("pageTools:capture")).toThrow("no page");
    expect(h.first("ipc-error")?.text).toContain("outcome=throw");
    expect(h.first("ipc-error")?.text).toContain("error=Error: no page");
  });

  it("拒绝:记一行 outcome=error,返回的 promise 原样拒绝", async () => {
    const h = harness("1");
    h.globals.handle("data:exportDiagnostics", () => Promise.reject(new Error("boom")));
    await expect(h.invoke("data:exportDiagnostics") as Promise<unknown>).rejects.toThrow("boom");
    await Promise.resolve();
    expect(h.first("ipc-error")?.text).toContain("outcome=error");
    expect(h.first("ipc-error")?.text).toContain("error=Error: boom");
  });

  it("快速失败不会刷屏:同一通道同一结局每秒最多一行", () => {
    const h = harness("1");
    h.globals.handle("backend:retry", () => {
      throw new Error("down");
    });
    for (let i = 0; i < 5; i += 1) expect(() => h.invoke("backend:retry")).toThrow("down");
    expect(h.of("ipc-error")).toHaveLength(1);
    h.clock.now += 1000;
    expect(() => h.invoke("backend:retry")).toThrow("down");
    expect(h.of("ipc-error")).toHaveLength(2);
  });
});

describe("IPC 追踪:关掉时零输出、零挂载", () => {
  it("MOSAEL_IPC_TRACE=0:一行不写、连环也不记,连 .then 都不挂", () => {
    const h = harness("0");
    let thenCalls = 0;
    const thenable = {
      then: () => {
        thenCalls += 1;
      },
    };
    h.globals.handle("publish:reload", () => thenable);
    h.globals.listen("system:status", () => undefined);

    expect(h.invoke("publish:reload")).toBe(thenable);
    expect(thenCalls).toBe(0);
    h.send("system:status", { running: 1 });
    h.crash({ reason: "crashed" });

    expect(h.lines).toEqual([]); // 诊断行一条都没有
    expect(h.mainLines.map((line) => line.text)).toEqual([expect.stringContaining("mode=off")]); // 只剩开机那一行
  });

  it("关掉时推送照旧:sendToRenderer 只是转发", () => {
    const h = harness("0");
    h.push({ id: 3 }, "publish:view", { visible: true });
    expect(h.sent).toEqual([{ channel: "publish:view", payload: [{ visible: true }] }]);
    expect(h.lines).toEqual([]);
  });

  it("三档开关:1 = trace,不设 = ring,0 = off,别的值不许悄悄打开落盘", () => {
    const h = harness("0");
    expect(h.globals.ipcTraceMode({ MOSAEL_IPC_TRACE: "1" })).toBe("trace");
    expect(h.globals.ipcTraceMode({})).toBe("ring");
    expect(h.globals.ipcTraceMode(undefined)).toBe("ring");
    expect(h.globals.ipcTraceMode({ MOSAEL_IPC_TRACE: "0" })).toBe("off");
    expect(h.globals.ipcTraceMode({ MOSAEL_IPC_TRACE: "yes" })).toBe("ring");
  });
});

describe("IPC 追踪:接法(main.cjs 里真的接上了)", () => {
  it("renderer→main 的入口还是只有 handle / listen 两个,不直接用 ipcMain", () => {
    expect(MAIN.match(/ipcMain\.(handle|on)\(/g)).toEqual(["ipcMain.handle(", "ipcMain.on("]);
    expect(MAIN).toMatch(/ipcMain\.handle\(channel, \(event, \.\.\.args\) => \{\s*if \(!fromAppWindow\(event\)\)/);
    expect(MAIN).toMatch(/ipcMain\.on\(channel, \(event, \.\.\.args\) => \{\s*if \(!fromAppWindow\(event\)\)/);
    // 追踪挂在拒绝之后:被拒的调用不发 IP C 追踪行(ipc-refused 那一行照旧)。
    expect(MAIN).toMatch(/ipcMain\.handle\(channel, \(event, \.\.\.args\) => \{[\s\S]{0,400}?traceIpc\("invoke", channel/);
    expect(MAIN).toMatch(/ipcMain\.on\(channel, \(event, \.\.\.args\) => \{[\s\S]{0,400}?traceIpc\("send", channel/);
  });

  it("主进程推给页面的每一处都过 sendToRenderer(一处定义 + 9 个调用点,再没有裸的 webContents.send)", () => {
    expect(MAIN).toMatch(/function sendToRenderer\(contents, channel, \.\.\.payload\) \{/);
    expect(MAIN.match(/sendToRenderer\(win\.webContents/g)).toHaveLength(9);
    expect(MAIN).not.toMatch(/webContents\.send\(/);
    expect(MAIN).not.toMatch(/contents\.send\(\s*["']/); // 通道名不许写死(见 ipc-contract.test.ts)
  });

  it("崩的那一刻接在 render-process-gone 上,而且是同步写(不受同一处理函数里那几个异步读数影响)", () => {
    expect(MAIN).toMatch(/app\.on\("render-process-gone", \(_event, webContents, details\) => \{[\s\S]{0,1400}?appendIpcTraceAtCrash\(details\);/);
    expect(MAIN).toMatch(/void appendMemoryAtCrash\(details\);[\s\S]{0,200}?appendIpcTraceAtCrash\(details\);/);
  });

  it("频率汇总的定时器和其他诊断一起起(在 whenReady 里,排在插件目录那一条后面)", () => {
    expect(MAIN).toMatch(/startPluginsDirectoryDiagnostics\(\);\n\s*\/\/[^\n]*\n\s*startIpcRateWatch\(\);/);
  });

  it("环的容量在 30–50 条之间(要能回看临死前那几秒,又不能把 main.log 冲掉)", () => {
    const ring = Number(MAIN.match(/const IPC_TRACE_RING = (\d+);/)?.[1]);
    expect(ring).toBeGreaterThanOrEqual(30);
    expect(ring).toBeLessThanOrEqual(50);
  });

  it("每一条诊断行都带本地时间(mainDiagnostics.test.ts 的同一条规矩,新加的行也守)", () => {
    const calls = [...MAIN.matchAll(/appendDiagnosticLog\((?:`[^`]*`|"[^"]*")/g)];
    for (const call of calls) {
      expect(MAIN.slice(call.index ?? 0).slice(0, 600), MAIN.slice(call.index, (call.index ?? 0) + 40)).toMatch(/local[=:]\s*(\$\{)?localClock\(\)/);
    }
  });
});

describe("preload 的桥 ↔ channel 对照表", () => {
  type Seen = { bridge: string; kind: string; channel: string };

  /**
   * 跑真的 preload.cjs:喂一座假的 electron,把四座桥收下来,再把每个桥方法各调一次。
   * 参数统一给一个空函数(订阅类方法要 callback,别的把它当普通值包进对象里)。
   */
  function bridgeMap() {
    const exposed = new Map<string, Record<string, unknown>>();
    const seen: Seen[] = [];
    let current = "(preload 顶层)";
    const record = (kind: string, channel: unknown) => seen.push({ bridge: current, kind, channel: String(channel) });
    const ipcRenderer = {
      invoke: (channel: string) => {
        record("invoke", channel);
        return Promise.resolve(undefined);
      },
      send: (channel: string) => {
        record("send", channel);
        return undefined;
      },
      on: (channel: string) => {
        record("on", channel);
        return undefined;
      },
      removeListener: () => undefined,
    };
    const context = {
      require: (spec: string) => {
        if (spec === "electron") return { contextBridge: { exposeInMainWorld: (key: string, bridge: Record<string, unknown>) => exposed.set(key, bridge) }, ipcRenderer };
        return require(path.join(__dirname, spec)) as unknown;
      },
      process: { platform: "darwin" },
      document: { documentElement: { lang: "zh-CN" } },
      MutationObserver: class {
        observe() {}
        disconnect() {}
      },
      window: { dispatchEvent: () => undefined },
    };
    vm.runInNewContext(PRELOAD, vm.createContext(context));

    const methods: { name: string; fn: (arg: unknown) => unknown }[] = [];
    const walk = (value: Record<string, unknown>, prefix: string) => {
      for (const [key, member] of Object.entries(value)) {
        if (typeof member === "function") methods.push({ name: `${prefix}.${key}`, fn: member as (arg: unknown) => unknown });
        else if (member && typeof member === "object") walk(member as Record<string, unknown>, `${prefix}.${key}`);
      }
    };
    for (const [key, bridge] of exposed) walk(bridge, key);

    const failed: string[] = [];
    const map = new Map<string, string[]>();
    for (const method of methods) {
      const before = seen.length;
      current = method.name;
      try {
        method.fn(() => undefined);
      } catch (error) {
        failed.push(`${method.name}: ${error instanceof Error ? error.message : String(error)}`);
      }
      if (seen.length === before) failed.push(`${method.name}: 没走到任何 channel`);
    }
    for (const call of seen) {
      const list = map.get(call.channel) ?? [];
      list.push(`${call.bridge}(${call.kind})`);
      map.set(call.channel, list);
    }
    return { exposed, methods, map, failed, seen };
  }

  const built = bridgeMap();

  it("四座桥,69 个方法,一条 channel 只对一座桥(订阅类可能两份:preload 顶层缓存 + 桥订阅)", () => {
    expect([...built.exposed.keys()].sort()).toEqual(["mosaelBrowser", "mosaelDesktop", "mosaelPageTools", "mosaelPublish"]);
    expect(built.failed).toEqual([]);
    expect(built.methods).toHaveLength(69);
    const invokeOnce = Object.values(IPC.invoke).map((channel) => built.map.get(channel)?.length ?? 0);
    const sendChannels = Object.values(IPC.send).filter((channel) => channel !== IPC.send.locale);
    expect(invokeOnce.every((count) => count === 1)).toBe(true);
    expect(sendChannels.map((channel) => built.map.get(channel)?.length ?? 0)).toEqual(sendChannels.map(() => 1));
  });

  it("契约里每一条 renderer→main 的 channel 都从桥上走得到 —— 唯一例外是界面语言", () => {
    // 语言那条不是桥方法发的:preload 盯着 <html lang>(MutationObserver),变了才 send 一次(见 preload.cjs)。
    expect(Object.values(IPC.invoke).filter((channel) => !built.map.has(channel))).toEqual([]);
    expect(Object.values(IPC.send).filter((channel) => !built.map.has(channel))).toEqual([IPC.send.locale]);
    // 反向:桥上出现的 channel 必须都在契约里(不许有野通道)。
    const known = new Set([...Object.values(IPC.invoke), ...Object.values(IPC.send), ...Object.values(IPC.event)]);
    expect([...built.map.keys()].filter((channel) => !known.has(channel))).toEqual([]);
  });

  it("这次要盯的那几条,桥上是哪个调用", () => {
    expect(built.map.get(IPC.invoke.publishReload)).toEqual(["mosaelPublish.reload(invoke)"]);
    expect(built.map.get(IPC.invoke.comfyuiWorkbenchCall)).toEqual(["mosaelBrowser.comfyWorkbench(invoke)"]);
    expect(built.map.get(IPC.invoke.comfyuiOpenWorkbench)).toEqual(["mosaelBrowser.openComfyWorkbench(invoke)"]);
    expect(built.map.get(IPC.invoke.mainStatus)).toEqual(["mosaelDesktop.devMain.status(invoke)"]);
    expect(built.map.get(IPC.invoke.customCssRead)).toEqual(["mosaelDesktop.customCss.read(invoke)"]);
    expect(built.map.get(IPC.invoke.pageToolsImages)).toEqual(["mosaelPageTools.listImages(invoke)"]);
    // 订阅:preload 顶层先订一次(缓存最新一帧,React 挂载晚也补得上),桥方法再订一次。
    expect(built.map.get(IPC.event.publishView)).toEqual(["(preload 顶层)(on)", "mosaelPublish.onViewState(on)"]);
    expect(built.map.get(IPC.event.comfyuiWorkbench)).toEqual(["mosaelBrowser.onComfyWorkbench(on)"]);
    // 这 4 条不是桥方法:preload 顶层订阅后转成 window 事件(深链、打开文件、⌘K、任务中心)。
    for (const channel of [IPC.event.deepLink, IPC.event.openFiles, IPC.event.commandPalette, IPC.event.openTasks]) {
      expect(built.map.get(channel)).toEqual(["(preload 顶层)(on)"]);
    }
  });

  it("页面拿不到裸的 ipcRenderer:桥上只有那四个对象", () => {
    expect(PRELOAD).not.toMatch(/exposeInMainWorld\(\s*["']ipcRenderer["']/);
    expect([...built.exposed.keys()]).toHaveLength(4);
  });
});
