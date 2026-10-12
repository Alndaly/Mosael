/**
 * 「内存随 reload 涨」这条线要有证据,就得先有一条**曲线**;曲线要有用,采样行必须真的写得出来、字段必须齐、
 * 读不到内存时不许抛。这里钉的就是这些 —— 照 mainDiagnostics.test.ts 的用法,把 main.cjs 里的代码段**抠出来真跑**:
 * 只喂桩,不启动 Electron,更不会为了测试去崩一次应用。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it } from "vitest";

const MAIN = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8");

/** 从 main.cjs 里抠出一段源码来单独跑。 */
function extract(pattern: RegExp, what: string) {
  const source = MAIN.match(pattern)?.[0];
  if (!source) throw new Error(`${what} not found in main.cjs`);
  return source;
}

const F = {
  summarizeAppMemory: extract(/\nfunction summarizeAppMemory\(metrics\) \{[\s\S]*?\n\}\n/, "summarizeAppMemory"),
  memoryByPid: extract(/\nfunction memoryByPid\(metrics\) \{[\s\S]*?\n\}\n/, "memoryByPid"),
  tabProcessList: extract(/\nfunction tabProcessList\(metrics\) \{[\s\S]*?\n\}\n/, "tabProcessList"),
  viewIdentity: extract(/\nfunction viewIdentity\(contents\) \{[\s\S]*?\n\}\n/, "viewIdentity"),
  viewPrivateMemory: extract(/\nasync function viewPrivateMemory\(contents\) \{[\s\S]*?\n\}\n/, "viewPrivateMemory"),
  viewMemoryEntry: extract(/\nfunction viewMemoryEntry\(identity, metric, priv\) \{[\s\S]*?\n\}\n/, "viewMemoryEntry"),
  liveViewMemory: extract(/\nasync function liveViewMemory\(\) \{[\s\S]*?\n\}\n/, "liveViewMemory"),
  appendMemorySample: extract(/\nasync function appendMemorySample\(extra = \{\}, kind = "memory-sample"\) \{[\s\S]*?\n\}\n/, "appendMemorySample"),
  appendMemoryAtCrash: extract(/\nasync function appendMemoryAtCrash\(details\) \{[\s\S]*?\n\}\n/, "appendMemoryAtCrash"),
  appendViewMemory: extract(/\nasync function appendViewMemory\(kind, contents, extra\) \{[\s\S]*?\n\}\n/, "appendViewMemory"),
  startMemoryDiagnostics: extract(/\nfunction startMemoryDiagnostics\(\) \{[\s\S]*?\n\}\n/, "startMemoryDiagnostics"),
  spikeStep: extract(/\nconst MEMORY_SPIKE_STEP_KB = [^\n]*\n/, "MEMORY_SPIKE_STEP_KB"),
  spikeEntries: extract(/\nfunction spikeEntries\(lastWritten, metrics, contentsList\) \{[\s\S]*?\n\}\n/, "spikeEntries"),
  startMemorySpikeWatch: extract(/\nfunction startMemorySpikeWatch\(\) \{[\s\S]*?\n\}\n/, "startMemorySpikeWatch"),
  startPluginsDirectoryDiagnostics: extract(
    /\nfunction startPluginsDirectoryDiagnostics\(\) \{[\s\S]*?\n\}\n/,
    "startPluginsDirectoryDiagnostics",
  ),
  localClock: extract(/\nfunction localClock\(date = new Date\(\)\) \{[\s\S]*?\n\}\n/, "localClock"),
};

/** 采样链上「读状态」的那几段 + 记日志那一段,凑成一条能整跑的链。 */
const SAMPLING_CHAIN = [
  F.localClock,
  F.summarizeAppMemory,
  F.memoryByPid,
  F.tabProcessList,
  F.viewIdentity,
  F.viewPrivateMemory,
  F.viewMemoryEntry,
  F.liveViewMemory,
  F.appendMemorySample,
  F.appendMemoryAtCrash,
  F.appendViewMemory,
].join("\n");

/** 一块 webContents 的桩:只实现这段代码真正用到的四个读法。 */
function fakeContents({ id = 1, type = "window", pid = 100, url = "", info }: { id?: number; type?: string; pid?: number; url?: string; info?: unknown }) {
  return {
    id,
    getType: () => type,
    getOSProcessId: () => pid,
    getURL: () => url,
    getProcessMemoryInfo: () => (info === "boom" ? Promise.reject(new Error("gone")) : Promise.resolve(info ?? { private: 10, resident: 20 })),
  };
}

/** 把采样链放进一个干净的 realm 里跑,返回写出来的行。prelude 用来在**那个 realm 里**造桩与错误。 */
function runSampling(stubs: Record<string, unknown>, prelude = "") {
  const written: string[] = [];
  const context: Record<string, unknown> = {
    appendDiagnosticLog: (kind: string, detail: string | (() => string)) => {
      const line = typeof detail === "function" ? detail() : detail;
      if (line) written.push(`${kind} ${line}`);
    },
    process: { uptime: () => 42 },
    ...stubs,
  };
  vm.runInNewContext(`${prelude}\n${SAMPLING_CHAIN}`, context);
  return { context, written };
}

/** 只跑 appendMemorySample / appendViewMemory 这两个入口,返回解析后的 JSON。 */
async function sample(stubs: Record<string, unknown>, prelude = "") {
  const { context, written } = runSampling(stubs, prelude);
  return {
    written,
    lines: () => written.map((line) => ({ kind: line.split(" ")[0], json: JSON.parse(line.slice(line.indexOf(" ") + 1)) })),
    call: (name: string, ...args: unknown[]) =>
      (context[name] as (...a: unknown[]) => Promise<void>)(...args),
  };
}

describe("每 30 秒那一条采样行", () => {
  it("按类型汇总 + 总 working set + 进程数;privateBytes 报不了就整个字段不写(不拿 0 顶替)", () => {
    const source = F.summarizeAppMemory;
    const context: Record<string, unknown> = { summarizeAppMemory: null };
    vm.runInNewContext(`${source}; this.summarizeAppMemory = summarizeAppMemory;`, context);
    const summarize = context.summarizeAppMemory as (metrics: unknown) => Record<string, unknown>;

    expect(
      summarize([
        { type: "Browser", memory: { workingSetSize: 100, privateBytes: 40 } },
        { type: "Tab", memory: { workingSetSize: 300, privateBytes: 60 } },
        { type: "Tab", memory: { workingSetSize: 1 } },
        { type: "GPU" },
      ]),
    ).toEqual({
      processes: 4,
      workingSetKb: 401,
      privateKb: 100,
      byType: { Browser: 100, Tab: 301, GPU: 0 },
    });

    // macOS 的 getAppMetrics 不给 privateBytes:那就没有这个字段,而不是 privateKb: 0。
    const noPrivate = summarize([{ type: "Tab", memory: { workingSetSize: 7 } }]);
    expect(noPrivate).toEqual({ processes: 1, workingSetKb: 7, byType: { Tab: 7 } });
    expect("privateKb" in noPrivate).toBe(false);

    // 空 / 拿不到:0 进程,不是抛。
    expect(summarize([])).toEqual({ processes: 0, workingSetKb: 0, byType: {} });
    expect(summarize(undefined)).toEqual({ processes: 0, workingSetKb: 0, byType: {} });
  });

  it("每一块 webContents 单独一行读数,url 一定带上;进程指标对不上就少字段,不是少这一块", () => {
    const source = [F.memoryByPid, F.viewMemoryEntry].join("\n");
    const context: Record<string, unknown> = { memoryByPid: null, viewMemoryEntry: null };
    vm.runInNewContext(`${source}; this.memoryByPid = memoryByPid; this.viewMemoryEntry = viewMemoryEntry;`, context);
    const entry = context.viewMemoryEntry as (i: unknown, m: unknown, p: unknown) => Record<string, unknown>;
    const identity = { id: 7, type: "window", pid: 4242, url: "http://127.0.0.1:5173/#/plugins" };

    // 三处读数齐全:私有内存优先用 getProcessMemoryInfo(只有它报 macOS)。
    expect(entry(identity, { memory: { workingSetSize: 555, privateBytes: 111 } }, { privateKb: 222, residentKb: 333 })).toEqual({
      id: 7,
      type: "window",
      pid: 4242,
      url: "http://127.0.0.1:5173/#/plugins",
      workingSetKb: 555,
      privateKb: 222,
      residentKb: 333,
    });

    // getProcessMemoryInfo 拿不到 → 退回进程级 privateBytes;进程指标也没有 → 只有 url 那一半,照样是完整的一块视图。
    expect(entry(identity, { memory: { workingSetSize: 555, privateBytes: 111 } }, null)).toMatchObject({ privateKb: 111, residentKb: null });
    expect(entry(identity, undefined, null)).toEqual({
      id: 7,
      type: "window",
      pid: 4242,
      url: "http://127.0.0.1:5173/#/plugins",
      workingSetKb: null,
      privateKb: null,
      residentKb: null,
    });
  });

  it("一条采样行里字段齐:local / uptimeSec / processes / workingSetKb / byType + 每块视图的 url 与 pid", async () => {
    const views = [
      fakeContents({ id: 1, pid: 100, url: "http://127.0.0.1:5173/#/plugins", info: { private: 700, resident: 900 } }),
      fakeContents({ id: 2, type: "webview", pid: 200, url: "http://127.0.0.1:8188/", info: { private: 30, resident: 40 } }),
    ];
    const s = await sample({
      app: {
        getAppMetrics: () => [
          { pid: 100, type: "Tab", memory: { workingSetSize: 1000 } },
          { pid: 200, type: "Tab", memory: { workingSetSize: 200 } },
          { pid: 1, type: "Browser", memory: { workingSetSize: 300 } },
        ],
      },
      webContents: { getAllWebContents: () => views },
    });

    await s.call("appendMemorySample");
    const [line] = s.lines();
    expect(line.kind).toBe("memory-sample");
    expect(line.json).toEqual({
      local: expect.stringMatching(/^\d\d:\d\d:\d\d$/),
      uptimeSec: 42,
      processes: 3,
      workingSetKb: 1500,
      byType: { Tab: 1200, Browser: 300 },
      // 渲染进程逐条列出来:视图那一栏只覆盖挂着 webContents 的,差值(实测有 300–470 MB)要看得见才追得下去。
      tabProcesses: [
        { pid: 100, workingSetKb: 1000 },
        { pid: 200, workingSetKb: 200 },
      ],
      views: [
        { id: 1, type: "window", pid: 100, url: "http://127.0.0.1:5173/#/plugins", workingSetKb: 1000, privateKb: 700, residentKb: 900 },
        { id: 2, type: "webview", pid: 200, url: "http://127.0.0.1:8188/", workingSetKb: 200, privateKb: 30, residentKb: 40 },
      ],
    });
  });

  it("崩的那一刻再抓一条:同样的读数,但 kind 不同、带上 reason/exitCode", async () => {
    // 30 秒的基线可能离崩溃很远(实测差 24 秒),崩前那几十秒谁涨的只有这一条补得上。
    const s = await sample({
      app: { getAppMetrics: () => [{ pid: 100, type: "Tab", memory: { workingSetSize: 999 } }] },
      webContents: { getAllWebContents: () => [fakeContents({ pid: 100, url: "http://127.0.0.1:5173/#/plugins" })] },
    });
    await s.call("appendMemoryAtCrash", { reason: "crashed", exitCode: 5 });
    const [line] = s.lines();
    expect(line.kind).toBe("memory-at-crash");
    expect(line.json).toMatchObject({ at: "crash", reason: "crashed", exitCode: 5, processes: 1, workingSetKb: 999 });
    expect(line.json.views[0].url).toBe("http://127.0.0.1:5173/#/plugins");
  });

  it("读不到内存时少字段、不抛:进程指标缺、私有内存读失败、某一块已销毁,别的照记", async () => {
    const destroyed = {
      id: 9,
      getType: () => "window",
      getOSProcessId: () => 300,
      getURL: () => {
        throw new Error("destroyed");
      },
      getProcessMemoryInfo: () => Promise.reject(new Error("destroyed")),
    };
    const s = await sample({
      app: { getAppMetrics: () => [{ pid: 100, type: "Tab", memory: { workingSetSize: 1000 } }] },
      webContents: {
        getAllWebContents: () => [
          fakeContents({ id: 1, pid: 100, url: "http://127.0.0.1:5173/#/plugins", info: "boom" }),
          fakeContents({ id: 2, pid: 999, url: "http://127.0.0.1:5173/#/boards" }),
          destroyed,
        ],
      },
    });

    await expect(s.call("appendMemorySample")).resolves.toBeUndefined();
    const [line] = s.lines();
    expect(line.json.processes).toBe(1);
    // pid 100 的私有内存读失败 + pid 999 没有进程指标:两块都还在,只是各少几个字段。
    expect(line.json.views).toEqual([
      { id: 1, type: "window", pid: 100, url: "http://127.0.0.1:5173/#/plugins", workingSetKb: 1000, privateKb: null, residentKb: null },
      { id: 2, type: "window", pid: 999, url: "http://127.0.0.1:5173/#/boards", workingSetKb: null, privateKb: 10, residentKb: 20 },
    ]);
  });

  it("整个读数炸了也只写一行 unavailable:不许把定时器变成第二次崩溃", async () => {
    // 桩和错误都造在 vm 自己的 realm 里:`instanceof Error` 跨 realm 为假,而现实里 getAppMetrics 抛出来的
    // 是本 realm 的 Error —— 桩得照着现实的样子抛(mainDiagnostics.test.ts 里同一条注意事项)。
    const s = await sample(
      {},
      `globalThis.app = { getAppMetrics() { throw new Error("app is gone"); } };
       globalThis.webContents = { getAllWebContents: () => [] };`,
    );
    await expect(s.call("appendMemorySample")).resolves.toBeUndefined();
    expect(s.written).toHaveLength(1);
    expect(s.written[0]).toMatch(/^memory-sample unavailable local=\d\d:\d\d:\d\d app is gone$/);
  });
});

describe("reload / 导航各一行", () => {
  it("did-start-navigation 那一行说明跳去哪、是不是同一个文档里的跳(hash 路由)", async () => {
    const s = await sample({
      app: { getAppMetrics: () => [{ pid: 100, type: "Tab", memory: { workingSetSize: 1234 } }] },
      webContents: { getAllWebContents: () => [] },
    });
    await s.call("appendViewMemory", "view-nav-start", fakeContents({ pid: 100, url: "http://127.0.0.1:5173/#/plugins" }), {
      to: "http://127.0.0.1:5173/#/ai",
      inPlace: true,
    });
    const [line] = s.lines();
    expect(line.kind).toBe("view-nav-start");
    expect(line.json).toEqual({
      local: expect.stringMatching(/^\d\d:\d\d:\d\d$/),
      id: 1,
      type: "window",
      pid: 100,
      url: "http://127.0.0.1:5173/#/plugins",
      workingSetKb: 1234,
      privateKb: 10,
      residentKb: 20,
      to: "http://127.0.0.1:5173/#/ai",
      inPlace: true,
    });
  });

  it("已销毁的那一块不写,也不抛(观测量不到不能把导航本身打断)", async () => {
    const s = await sample({ app: { getAppMetrics: () => [] }, webContents: { getAllWebContents: () => [] } });
    const gone = {
      getType: () => {
        throw new Error("destroyed");
      },
    };
    await expect(s.call("appendViewMemory", "view-load-finish", gone, {})).resolves.toBeUndefined();
    expect(s.written).toEqual([]);
  });

  it("两块事件都挂在每一块新 webContents 上,且只认主框架", () => {
    expect(MAIN).toMatch(/contents\.on\("did-start-navigation", \(details\) => \{\n\s*if \(!details\?\.isMainFrame\) return;/);
    expect(MAIN).toMatch(/contents\.on\("did-finish-load", \(\) => void appendViewMemory\("view-load-finish", contents, \{\}\)\)/);
    // hash 路由的跳(isSameDocument)不会有 did-finish-load,所以那一头必须记下来。
    expect(MAIN).toMatch(/inPlace: Boolean\(details\.isSameDocument\)/);
    // 挂在全局的 web-contents-created 上:主窗口、ComfyUI 工作台、发布账号视图一个都不落。
    expect(MAIN).toMatch(/app\.on\("web-contents-created", \(_event, contents\) => \{/);
  });
});

describe("定时器", () => {
  /** 只跑 startMemoryDiagnostics:采样本身在这里换成计数桩,测的是「多久一次、会不会拖住退出、先记不记基线」。 */
  function runStart(stubs: Record<string, unknown>, prelude = "") {
    const written: string[] = [];
    const context: Record<string, unknown> = {
      appendDiagnosticLog: (kind: string, detail: string | (() => string)) => written.push(`${kind} ${typeof detail === "function" ? detail() : detail}`),
      setInterval: null,
      boot: 0,
      ...stubs,
    };
    const counter = "async function appendMemorySample() { globalThis.boot += 1; }";
    vm.runInNewContext(`${prelude}\n${F.localClock}\n${counter}\n${F.startMemoryDiagnostics}`, context);
    return { context, written };
  }

  it("每 30 秒一次、先记一条启动基线、定时器 unref(不许拖住退出)", () => {
    const intervals: number[] = [];
    const unrefs: boolean[] = [];
    const { context } = runStart({
      setInterval: (callback: () => void, ms: number) => {
        intervals.push(ms);
        return {
          unref: () => {
            unrefs.push(true);
          },
        };
      },
    });

    (context.startMemoryDiagnostics as () => void)();
    expect(intervals).toEqual([30_000]);
    expect(unrefs).toEqual([true]);
    // 启动那条基线不是多余的:最新一簇是启动后 17 秒就崩的,「一开机就这么大」和「涨上来的」要分得开。
    expect((context as unknown as { boot: number }).boot).toBe(1);
    expect(MAIN).toMatch(/const timer = setInterval\(\(\) => void appendMemorySample\(\), sampleSeconds \* 1000\);\n\s*\/\/ 这个定时器不许拖住退出[\s\S]{0,40}?\n\s*timer\.unref\?\.\(\);/);
  });

  it("定时器都挂不上也只记一行,不抛(它跑在 whenReady 最前面,抛出去后面启动就全断了)", () => {
    // 同上:错误造在 vm 自己的 realm 里。
    const { context, written } = runStart({}, `globalThis.setInterval = () => { throw new Error("no timers"); };`);
    expect(() => (context.startMemoryDiagnostics as () => void)()).not.toThrow();
    expect(written).toEqual([expect.stringMatching(/^memory-sample unavailable local=\d\d:\d\d:\d\d no timers$/)]);
  });
});

describe("尖峰探测器(5 秒一格,只在暴涨时写)", () => {
  /** 一组会变的读数:pid = 100+i, mutate `sizes` 就是让视图涨。 */
  function world(sizes: number[]) {
    return {
      app: { getAppMetrics: () => sizes.map((kb, i) => ({ pid: 100 + i, type: "Tab", memory: { workingSetSize: kb } })) },
      webContents: {
        getAllWebContents: () => sizes.map((_, i) => fakeContents({ id: i + 1, pid: 100 + i, url: `http://127.0.0.1:5173/#/v${i}` })),
      },
    };
  }

  function runSpike(stubs: Record<string, unknown>, prelude = "") {
    const written: string[] = [];
    let tick: (() => void) | null = null;
    const intervals: number[] = [];
    const unrefs: boolean[] = [];
    const context: Record<string, unknown> = {
      appendDiagnosticLog: (kind: string, detail: string | (() => string)) => {
        const line = typeof detail === "function" ? detail() : detail;
        // 和真的 appendDiagnosticLog 一样:空串不写(安静时不许刷日志)。
        if (line) written.push(`${kind} ${line}`);
      },
      process: { uptime: () => 7 },
      setInterval: (callback: () => void, ms: number) => {
        intervals.push(ms);
        tick = callback;
        return {
          unref: () => {
            unrefs.push(true);
          },
        };
      },
      ...stubs,
    };
    vm.runInNewContext(
      `${prelude}\n${F.localClock}\n${F.memoryByPid}\n${F.viewIdentity}\n${F.spikeStep}\n${F.spikeEntries}\n${F.startMemorySpikeWatch}`,
      context,
    );
    return { written, intervals, unrefs, context, fire: () => tick?.(), spiked: () => written.map((l) => JSON.parse(l.slice(l.indexOf(" ") + 1)).spiked) };
  }

  it("5 秒一格、unref;第一次见到记基线,没涨够 32 MB 一行不写,涨够了才写", () => {
    const sizes = [1000];
    const w = runSpike(world(sizes));
    (w.context.startMemorySpikeWatch as () => void)();
    expect(w.intervals).toEqual([5_000]);
    expect(w.unrefs).toEqual([true]);

    w.fire(); // 基线:有起点才知道「涨了多少」
    expect(w.spiked()).toEqual([[{ pid: 100, url: "http://127.0.0.1:5173/#/v0", fromKb: null, toKb: 1000, deltaKb: null }]]);

    sizes[0] = 1000 + 32 * 1024 - 1; // 差 1 KB,不够
    w.fire();
    expect(w.written).toHaveLength(1); // 安静时不写

    sizes[0] = 1000 + 32 * 1024;
    w.fire();
    expect(w.spiked()[1]).toEqual([{ pid: 100, url: "http://127.0.0.1:5173/#/v0", fromKb: 1000, toKb: 33768, deltaKb: 32768 }]);

    // 写过之后基准推到当前值:再涨 1 KB 不许写(否则每一格都写,就成了刷日志)。
    sizes[0] += 1024;
    w.fire();
    expect(w.written).toHaveLength(2);
  });

  it("慢慢涨也藏不住:基准只在写出去时推进,攒够一格(32 MB)照样写一行", () => {
    const sizes = [10_000];
    const w = runSpike(world(sizes));
    (w.context.startMemorySpikeWatch as () => void)();
    w.fire(); // 基线
    // 每格 +2 MB:15 格 30 MB 还差一点,第 16 格正好 32 MB 过线(判据是 >=)。
    for (let i = 1; i <= 15; i += 1) {
      sizes[0] += 2 * 1024;
      w.fire();
    }
    expect(w.written).toHaveLength(1);
    sizes[0] += 2 * 1024;
    w.fire();
    expect(w.written).toHaveLength(2);
    expect(w.spiked()[1]).toEqual([
      { pid: 100, url: "http://127.0.0.1:5173/#/v0", fromKb: 10_000, toKb: 10_000 + 32 * 1024, deltaKb: 32 * 1024 },
    ]);
  });

  it("两块视图各记各的:涨的那块写、没涨的那块不写;已销毁的跳过", () => {
    const sizes = [1000, 5000];
    const stubs = world(sizes);
    const gone = {
      getType: () => {
        throw new Error("destroyed");
      },
    };
    const all = stubs.webContents.getAllWebContents;
    stubs.webContents.getAllWebContents = () => [...all(), gone as never];
    const w = runSpike(stubs);
    (w.context.startMemorySpikeWatch as () => void)();
    w.fire();
    expect(w.spiked()[0]).toHaveLength(2);

    sizes[1] += 40 * 1024; // 只有第二块涨
    w.fire();
    expect(w.spiked()[1]).toEqual([
      { pid: 101, url: "http://127.0.0.1:5173/#/v1", fromKb: 5000, toKb: 5000 + 40 * 1024, deltaKb: 40 * 1024 },
    ]);
  });

  it("这一档自己挂不上也只记一行,不抛", () => {
    const w = runSpike({}, `globalThis.setInterval = () => { throw new Error("no timers"); };`);
    expect(() => (w.context.startMemorySpikeWatch as () => void)()).not.toThrow();
    expect(w.written).toEqual([expect.stringMatching(/^memory-spike unavailable local=\d\d:\d\d:\d\d no timers$/)]);
  });

  it("为什么需要它:30 秒的基线给崩溃那段窗口只留 0–2 个读数", () => {
    // 采样周期与探测器周期都在源码里,别被谁悄悄改回 30 秒(那样等于没有探测器)。
    expect(MAIN).toMatch(/const MEMORY_SPIKE_STEP_KB = 32 \* 1024;/);
    expect(MAIN).toMatch(/\}, 5_000\);/);
    expect(MAIN).toMatch(/const sampleSeconds = 30;/);
  });
});

describe("插件页在反复拉整份目录吗", () => {
  /** 把 webRequest 的观察者接下来,喂它几条完成的请求。 */
  function runWatcher(stubs: Record<string, unknown> = {}) {
    const written: string[] = [];
    const filters: unknown[] = [];
    let handler: ((details: unknown) => void) | null = null;
    const context: Record<string, unknown> = {
      appendDiagnosticLog: (kind: string, detail: string | (() => string)) => written.push(`${kind} ${typeof detail === "function" ? detail() : detail}`),
      session: {
        defaultSession: {
          webRequest: {
            onCompleted: (filter: unknown, callback: (details: unknown) => void) => {
              filters.push(filter);
              handler = callback;
            },
          },
        },
      },
      ...stubs,
    };
    vm.runInNewContext(`${F.localClock}\n${F.startPluginsDirectoryDiagnostics}`, context);
    return {
      written,
      filters,
      context,
      fire: (details: unknown) => handler?.(details),
    };
  }

  it("只数那一份整目录,带 n / 字节数 / 状态码 / 本地时间", () => {
    const w = runWatcher();
    (w.context.startPluginsDirectoryDiagnostics as () => void)();

    w.fire({ url: "http://127.0.0.1:8800/api/plugins", statusCode: 200, fromCache: false, responseHeaders: { "Content-Length": ["3254512"] } });
    w.fire({ url: "http://127.0.0.1:8800/api/plugins/tools", statusCode: 200, fromCache: false, responseHeaders: {} });
    w.fire({ url: "http://127.0.0.1:8800/api/plugins?p=x", statusCode: 200, fromCache: false, responseHeaders: { "content-length": ["10"] } });
    w.fire({ url: "http://127.0.0.1:5173/src/main.tsx", statusCode: 200, fromCache: true, responseHeaders: {} });
    w.fire({ url: "https://creator.douyin.com/api/plugins", statusCode: 200, fromCache: false, responseHeaders: {} });

    expect(w.written).toEqual([
      expect.stringMatching(/^plugins-dir-fetch n=1 local=\d\d:\d\d:\d\d status=200 bytes=3254512 fromCache=false$/),
      expect.stringMatching(/^plugins-dir-fetch n=2 local=\d\d:\d\d:\d\d status=200 bytes=10 fromCache=false$/),
    ]);
  });

  it("只挂本机两个 host(发布视图要拉一堆外网资源,宽通配会让每个请求都回主进程)", () => {
    const w = runWatcher();
    (w.context.startPluginsDirectoryDiagnostics as () => void)();
    expect(w.filters).toEqual([{ urls: ["*://127.0.0.1/*", "*://localhost/*"] }]);
  });

  it("没有这条请求通道时只记一行,不抛", () => {
    const w = runWatcher({ session: {} });
    expect(() => (w.context.startPluginsDirectoryDiagnostics as () => void)()).not.toThrow();
    expect(w.written).toEqual([expect.stringMatching(/^plugins-dir-fetch unavailable local=\d\d:\d\d:\d\d /)]);
  });
});

describe("接进 main.cjs", () => {
  it("两条诊断都在 whenReady 里起,而且都不改应用行为", () => {
    expect(MAIN).toMatch(/startGpuDiagnostics\(\);\n\s*startPowerAndDisplayDiagnostics\(\);\n[\s\S]{0,200}?startMemoryDiagnostics\(\);\n\s*startMemorySpikeWatch\(\);\n\s*startPluginsDirectoryDiagnostics\(\);/);
    // 崩溃那一刻补一条逐视图读数(30 秒的基线离崩溃可以差到 24 秒)。
    expect(MAIN).toMatch(/app\.on\("render-process-gone", \(_event, webContents, details\) => \{[\s\S]{0,900}?void appendMemoryAtCrash\(details\);/);
    // 只读观察:这一档只挂 onCompleted。会改请求的那几个钩子(onBeforeRequest / onBeforeSendHeaders / cancel)
    // 一律不碰 —— main.cjs 里已有的那一处是壳令牌注入,不是这条线的(所以断言只圈在这一段里)。
    const watcher = extract(/\nfunction startPluginsDirectoryDiagnostics\(\) \{[\s\S]*?\n\}\n/, "startPluginsDirectoryDiagnostics");
    expect(watcher).toMatch(/webRequest\.onCompleted\(/);
    expect(watcher).not.toMatch(/onBeforeRequest|onBeforeSendHeaders|onHeadersReceived|cancel|callback\(/);
    // URL 那一半必须留在采样行里 —— 分不清是哪一块视图在涨,这条曲线就没用。
    expect(MAIN).toMatch(/function viewMemoryEntry\(identity, metric, priv\)/);
    expect(MAIN).toMatch(/url: contents\.getURL\(\)/);
  });

  it("原来那条崩溃行不动(它的字段形状被 mainDiagnostics.test.ts 钉着)", () => {
    expect(MAIN).toMatch(/memory: memorySnapshot\(\)/);
    expect(MAIN).toMatch(/\nfunction memorySnapshot\(\) \{/);
    expect(MAIN).not.toMatch(/function memorySnapshot\(\) \{[\s\S]{0,400}?summarizeAppMemory/);
  });
});
