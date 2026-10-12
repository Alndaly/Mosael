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
  // 「那 9 秒里页面在后端要什么」那一档(和上面那一个共用同一个 webRequest 回调)。
  httpConstants: extract(/\nconst HTTP_TRACE_WINDOW_MS = [^\n]*\n[\s\S]*?const HTTP_TRACE_TYPES = [^\n]*\n/, "HTTP_TRACE_* 常量"),
  httpState: extract(/\nconst httpTracePaths = new Map\(\);\n[\s\S]*?let httpTraceDropped = 0;\n/, "httpTrace 状态"),
  httpTracePath: extract(/\nfunction httpTracePath\(raw\) \{[\s\S]*?\n\}\n/, "httpTracePath"),
  httpTraceBytes: extract(/\nfunction httpTraceBytes\(details\) \{[\s\S]*?\n\}\n/, "httpTraceBytes"),
  httpTraceAdd: extract(/\nfunction httpTraceAdd\(table, key, bytes, type\) \{[\s\S]*?\n\}\n/, "httpTraceAdd"),
  httpTraceTypeRows: extract(/\nfunction httpTraceTypeRows\(table, limit\) \{[\s\S]*?\n\}\n/, "httpTraceTypeRows"),
  traceHttpRequest: extract(/\nfunction traceHttpRequest\(details\) \{[\s\S]*?\n\}\n/, "traceHttpRequest"),
  httpTraceRows: extract(/\nfunction httpTraceRows\(entries, crashAt, limit\) \{[\s\S]*?\n\}\n/, "httpTraceRows"),
  httpTraceSessionTop: extract(/\nfunction httpTraceSessionTop\(limit\) \{[\s\S]*?\n\}\n/, "httpTraceSessionTop"),
  appendHttpTraceAtCrash: extract(/\nfunction appendHttpTraceAtCrash\(details, view\) \{[\s\S]*?\n\}\n/, "appendHttpTraceAtCrash"),
  ipcTraceMode: extract(/\nfunction ipcTraceMode\(env\) \{[\s\S]*?\n\}\n/, "ipcTraceMode"),
  localClock: extract(/\nfunction localClock\(date = new Date\(\)\) \{[\s\S]*?\n\}\n/, "localClock"),
};

/**
 * webRequest 那一个回调连同它点名的每一段代码,凑成一个**能整跑**的沙箱。
 *
 * 为什么要连 `traceHttpRequest` 一起 extract、而不是只 extract `startPluginsDirectoryDiagnostics`:
 * 回调自带 `try/catch`(「一条数不出来,不影响别的请求」),沙箱里少一个函数不会报错,只会**静默**少写几行 ——
 * 那正是「测试全绿、真机才炸」的雷。所以这里把用到的都装进来,并且有一条用例专门盯着「回调点名的每个函数
 * 是不是都真的在沙箱里」(见 `missingFromSanbox`)。
 */
const WATCHER_SANDBOX = [
  F.localClock,
  F.ipcTraceMode,
  "const IPC_TRACE_MODE = ipcTraceMode(process.env);",
  F.httpConstants,
  F.httpState,
  F.httpTracePath,
  F.httpTraceBytes,
  F.httpTraceAdd,
  F.httpTraceTypeRows,
  F.traceHttpRequest,
  F.httpTraceRows,
  F.httpTraceSessionTop,
  F.appendHttpTraceAtCrash,
  F.startPluginsDirectoryDiagnostics,
].join("\n");

/** 桩的名字 + 语言关键字 + 宿主全局:它们不是「沙箱里少了一个函数」。 */
const CALL_ALLOWED = new Set([
  ...["appendDiagnosticLog", "session", "process"],
  ...["Number", "String", "Boolean", "Math", "JSON", "Object", "Array", "Map", "Set", "RegExp", "Date", "Error"],
  ...["if", "for", "while", "switch", "catch", "return", "typeof", "new", "function", "do", "else"],
]);

/**
 * 去掉注释。三步的顺序都是踩出来的,换一步就会把**代码**当注释吃掉(扫描结果就成了「什么都没调用」,
 * 这条断言于是永远绿 —— 正是它要防的那种静默):
 *   1. 先抠字符串字面量:`["*://127.0.0.1/*", "*://localhost/*"]` 里那对斜杠星号不是注释开头,
 *      而 `*://` 里那对斜杠也不是;
 *   2. 再去 `//` 行注释,**必须在块注释之前** —— 注释里写着「别的 /api/ 通配不记」那种字眼时,注释里那个
 *      斜杠星号会跟后面代码里 `[^/]*` 结尾的星号加斜杠配成一对,把中间的真代码整段删掉(实测:这一段
 *      1379 字节会只剩 708);
 *   3. 最后去块注释(这一段的文档注释在这一步)。
 */
function stripComments(source: string): string {
  return source
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''")
    .replace(/\/\/[^\n]*/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");
}

function missingFromSandbox(sandbox: string = WATCHER_SANDBOX): string[] {
  const source = stripComments(sandbox);
  const declared = new Set(
    [...source.matchAll(/(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*))/g)]
      .flatMap((match) => [match[1], match[2]])
      .filter((name): name is string => Boolean(name)),
  );
  const called = new Set([...source.matchAll(/(?:^|[^\w.$])([A-Za-z_$][\w$]*)\s*\(/g)].map((match) => match[1]));
  return [...called].filter((name) => !declared.has(name) && !CALL_ALLOWED.has(name)).sort();
}

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

/**
 * 把 webRequest 的观察者接下来,喂它几条完成的请求。
 * 时钟是假的:窗口 top5 与 `t=` 偏移要钉死,真时钟下这些断言只能靠 sleep。
 */
function runWatcher(stubs: Record<string, unknown> = {}) {
  const written: string[] = [];
  const filters: unknown[] = [];
  const clock = { now: Date.UTC(2026, 0, 2, 3, 4, 5) };
  let handler: ((details: unknown) => void) | null = null;
  class FakeDate extends Date {
    constructor(value?: number) {
      super(value ?? clock.now);
    }
    static now(): number {
      return clock.now;
    }
  }
  const context: Record<string, unknown> = {
    Date: FakeDate,
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
    process: { env: {} },
    ...stubs,
  };
  vm.runInNewContext(WATCHER_SANDBOX, context);
  return {
    written,
    filters,
    clock,
    context,
    fire: (details: unknown) => handler?.(details),
  };
}

describe("插件页在反复拉整份目录吗", () => {

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

/**
 * 「那 9 秒里,页面在后端反复要什么」—— IPC 追踪给出的结论是「桥上一片安静」(崩前最后一条 IPC 距崩溃 9.0 秒),
 * 于是问题落到不过桥的那些请求上。这一档与上面那一个**共用同一个 webRequest 回调**(Electron 每个事件只保留
 * 最后一个 listener),所以这里的桩、沙箱、`plugins-dir-fetch` 的既有断言都在上面那一个 describe 里,两处共用。
 */
describe("那 9 秒里页面在后端要什么", () => {
  /** 一条本机请求。`bytes` 不给就等同于「响应没报 Content-Length」。 */
  const req = (path: string, bytes?: number, type = "xhr") => ({
    url: `http://127.0.0.1:8800${path}`,
    statusCode: 200,
    fromCache: false,
    resourceType: type,
    webContentsId: 1,
    responseHeaders: bytes === undefined ? {} : { "Content-Length": [String(bytes)] },
  });

  /** 起观察者。 */
  const start = (stubs: Record<string, unknown> = {}) => {
    const w = runWatcher(stubs);
    (w.context.startPluginsDirectoryDiagnostics as () => void)();
    return w;
  };

  /** 崩一次,把 http-at-crash 那一行解出来。 */
  const crash = (w: ReturnType<typeof start>, details: unknown = { reason: "crashed", exitCode: 5 }) => {
    (w.context.appendHttpTraceAtCrash as (d: unknown, v: unknown) => void)(details, 1);
    const line = w.written.filter((entry) => entry.startsWith("http-at-crash ")).at(-1);
    if (!line) throw new Error("没有写出 http-at-crash 那一行");
    return JSON.parse(line.slice("http-at-crash ".length));
  };

  it("回调点名的每个函数都真的在沙箱里 —— 否则会被那个 try/catch 静默吞掉(测试全绿、真机才炸)", () => {
    expect(missingFromSandbox()).toEqual([]);
    // 反面自检:故意抽掉一段就该点名它 —— 证明这条断言不是摆设(而不是「永远绿」)。
    expect(missingFromSandbox(WATCHER_SANDBOX.replace(F.traceHttpRequest, ""))).toEqual(["traceHttpRequest"]);
    // 间接被调用的那一段一样抓得到(httpTracePath 只被 traceHttpRequest 叫)。
    expect(missingFromSandbox(WATCHER_SANDBOX.replace(F.httpTracePath, ""))).toEqual(["httpTracePath"]);
    // 模板字符串里的调用也数得到(localClock 就在 `local=${localClock()}` 里)。
    expect(missingFromSandbox(WATCHER_SANDBOX.replace(F.localClock, ""))).toEqual(["localClock"]);
  });

  it("只记账、不写日志:本机请求再多,这一档一行都不多写(plugins-dir-fetch 照旧只数那一个路径)", () => {
    const w = start();
    for (let i = 0; i < 8; i += 1) w.fire(req("/api/plugins/local-service/comfy", 300 * 1024));
    w.fire(req("/api/plugins", 1_636_452));
    w.fire(req("/src/main.tsx", 4096, "script"));
    w.fire({ url: "https://creator.douyin.com/api/plugins", statusCode: 200, fromCache: false, responseHeaders: {} });

    expect(w.written).toEqual([
      expect.stringMatching(/^plugins-dir-fetch n=1 local=\d\d:\d\d:\d\d status=200 bytes=1636452 fromCache=false$/),
    ]);
  });

  it("崩的那一刻给窗口 top5:次数 / 累计字节 / 单次最大 / resourceType / 首末两条距崩溃多久", () => {
    const w = start();
    // 9 秒窗口里的那一族 1200 毫秒轮询:7 次,每次 300 KB。
    for (let i = 0; i < 7; i += 1) {
      w.clock.now += 1200;
      w.fire(req("/api/plugins/local-service/comfy", 300 * 1024));
    }
    w.fire(req("/api/state", 500));
    w.clock.now += 300;
    w.fire(req("/api/plugins", 1_636_452));
    w.clock.now += 200;

    const payload = crash(w);
    expect(payload).toMatchObject({
      local: expect.stringMatching(/^\d\d:\d\d:\d\d$/),
      reason: "crashed",
      exitCode: 5,
      view: 1,
      windowMs: 10_000,
      inWindow: { count: 9, paths: 3 },
      partial: false,
      lastAgoMs: 200,
      last: "/api/plugins",
    });
    expect(payload.inWindow.top).toEqual([
      {
        path: "/api/plugins/local-service/comfy",
        n: 7,
        bytes: 7 * 300 * 1024,
        max: 300 * 1024,
        type: "xhr",
        firstT: -7700,
        lastT: -500,
      },
      { path: "/api/plugins", n: 1, bytes: 1636452, max: 1636452, type: "xhr", firstT: -200, lastT: -200 },
      { path: "/api/state", n: 1, bytes: 500, max: 500, type: "xhr", firstT: -500, lastT: -500 },
    ]);
    // 「每 1.2 秒一次」由这两个数直接读得出来:(lastT - firstT) / (n - 1) = 7200 / 6 = 1200 毫秒。
    expect((payload.inWindow.top[0].lastT - payload.inWindow.top[0].firstT) / (payload.inWindow.top[0].n - 1)).toBe(1200);
    // /api/ 单独一列,只有 /api/ 开头的。
    expect(payload.api.map((row: { path: string }) => row.path)).toEqual([
      "/api/plugins/local-service/comfy",
      "/api/plugins",
      "/api/state",
    ]);
    expect(payload.session).toMatchObject({ total: 9, paths: 3, dropped: 0 });
    expect(payload.session.top[0]).toMatchObject({ path: "/api/plugins/local-service/comfy", n: 7 });
    expect(payload.ring.at(-1)).toMatchObject({ path: "/api/plugins", type: "xhr", status: 200, bytes: 1636452, from: 1, t: -200 });
  });

  it("一两百条「各只出现一次」的模块路径不会把字节数藏起来:类型榜 + 字节榜 + 谁在要", () => {
    // 真实那一次的形状:窗口里 205 条 / 197 条路径,前 5 榜上只有 5 条(第 5 条还是靠字节数并列才挤进来的),
    // 而 5 MB 的 lucide-react.js 就藏在剩下的一百多条里。这一条钉住「那之后补的三样读数」。
    const w = start();
    const POLLS = 6;
    const MODULES = 190;
    const MODULE_BYTES = 100 * 1024;
    const BIG_BYTES = 5 * 1024 * 1024;
    for (let i = 0; i < POLLS; i += 1) {
      w.clock.now += 100;
      // 主进程自己的 worker 轮询:没有 webContentsId(不是哪块页面发的),响应十几字节。
      w.fire({ url: "http://127.0.0.1:8800/api/browser/worker/claim", statusCode: 200, fromCache: false, resourceType: "other", responseHeaders: { "Content-Length": ["15"] } });
    }
    for (let i = 0; i < MODULES; i += 1) w.fire(req(`/node_modules/.vite/deps/mod-${i}.js`, MODULE_BYTES, "script"));
    w.fire(req("/node_modules/.vite/deps/lucide-react.js", BIG_BYTES, "script"));
    w.clock.now += 8700; // 页面之后 8.7 秒一个字都没要
    // 而主进程自己的 worker 轮询一直在走 —— 崩前 300 毫秒还来了一条(实测就是这么被误读的)。
    w.fire({ url: "http://127.0.0.1:8800/api/browser/worker/claim", statusCode: 200, fromCache: false, resourceType: "other", responseHeaders: { "Content-Length": ["15"] } });
    w.clock.now += 300;

    const payload = crash(w);
    expect(payload.inWindow).toMatchObject({ count: POLLS + MODULES + 2, paths: MODULES + 2, main: POLLS + 1, renderer: MODULES + 1 }); // 轮询打在同一条路径上
    expect(payload.inWindow.bytes).toBe(MODULES * MODULE_BYTES + BIG_BYTES + (POLLS + 1) * 15);
    expect(payload.inWindow.types).toEqual([
      { type: "script", n: MODULES + 1, bytes: MODULES * MODULE_BYTES + BIG_BYTES },
      { type: "other", n: POLLS + 1, bytes: (POLLS + 1) * 15 },
    ]);
    // 按次数的榜在这时候几乎没用(195 条并列 n=1);字节榜直接点名那个 5 MB 的。
    expect(payload.inWindow.top).toHaveLength(5);
    expect(payload.inWindow.biggest[0]).toMatchObject({ path: "/node_modules/.vite/deps/lucide-react.js", n: 1, bytes: BIG_BYTES });
    expect(payload.inWindow.biggest[1]).toMatchObject({ path: "/node_modules/.vite/deps/mod-0.js", bytes: MODULE_BYTES });
    // /api/ 那一列在这时候只有主进程那几条小请求 —— 正是「API 不是它」的读法。
    expect(payload.api.map((row: { path: string; n: number }) => [row.path, row.n])).toEqual([["/api/browser/worker/claim", POLLS + 1]]);
    // 「崩前 300 毫秒还在要东西」是**主进程**要的:渲染进程最后一次是 8.7 秒前。两个数必须分开给。
    expect(payload.lastAgoMs).toBe(300);
    expect(payload.lastMainMs).toBe(-300);
    expect(payload.lastMainPath).toBe("/api/browser/worker/claim");
    expect(payload.lastRendererMs).toBe(-9000);
    expect(payload.lastRendererPath).toBe("/node_modules/.vite/deps/lucide-react.js");
    // 窗口真的覆盖了 10 秒(环没被塞满时不带 partial)。
    expect(payload.partial).toBe(false);
    expect(payload.inWindow.coveredMs).toBe(9500); // 第一条在 100ms、崩在 9600ms
  });

  it("窗口外的请求不计入 inWindow,但计入 session(窗口是崩前那一段,不是整轮)", () => {
    const w = start();
    w.fire(req("/api/plugins", 1000));
    w.clock.now += 4000;
    w.fire(req("/api/plugins", 1000));
    w.clock.now += 30_000; // 中间隔了 30 秒,前面两条都掉出 10 秒窗口
    w.fire(req("/api/plugins", 1000));

    const payload = crash(w);
    expect(payload.inWindow).toMatchObject({ count: 1, paths: 1 });
    expect(payload.session).toMatchObject({ total: 3, paths: 1 });
    expect(payload.ring).toHaveLength(3); // 逐条现场不受窗口限制
  });

  it("窗口里一条本机请求都没有:也写一行,inWindow.count=0 —— 那 9 秒与后端无关也是结论", () => {
    const w = start();
    w.fire(req("/api/plugins", 1000));
    w.clock.now += 60_000;

    const payload = crash(w);
    expect(payload.inWindow).toEqual({
      count: 0,
      paths: 0,
      bytes: 0,
      coveredMs: 0,
      main: 0,
      renderer: 0,
      types: [],
      top: [],
      biggest: [],
    });
    expect(payload.api).toEqual([]);
    expect(payload.lastAgoMs).toBe(60_000);
    expect(payload.last).toBe("/api/plugins"); // 最后一次是一分钟前那一条
    expect(payload.session).toMatchObject({ total: 1, paths: 1, dropped: 0 });
  });

  it("响应没报 Content-Length 的仍然计数,但不假装它有大小", () => {
    const w = start();
    w.fire(req("/api/stream"));
    w.fire(req("/api/stream"));

    const payload = crash(w);
    expect(payload.inWindow.top[0]).toMatchObject({ path: "/api/stream", n: 2, bytes: 0, max: 0 });
  });

  it("表满了、环塞满了都要说出来:dropped 与 partial(这只是下界,不许当成精确值)", () => {
    const w = start();
    for (let i = 0; i < 1020; i += 1) w.fire(req(`/api/thing/${i}`, 10, "script")); // 1000 条进表,20 条被丢
    for (let i = 0; i < 3200; i += 1) w.fire(req("/api/thing/0", 10, "script")); // 打在已经在表里的那条上,顺带塞满环
    w.clock.now += 500;

    const payload = crash(w);
    expect(payload.session).toMatchObject({ paths: 1000, dropped: 20, total: 1000 + 3200 });
    // 路径表满了,类型表**不满**:「字节去哪了」永远准。
    expect(payload.session.types).toEqual([{ type: "script", n: 4220, bytes: 42200 }]);
    expect(payload.partial).toBe(true);
    expect(payload.inWindow.count).toBe(3000); // 环的容量,不是窗口里的真实条数(所以要看 partial)
  });

  it("总闸拉掉(MOSAEL_IPC_TRACE=0):不记账、不写行,但既有那条 plugins-dir-fetch 一字不动", () => {
    const w = start({ process: { env: { MOSAEL_IPC_TRACE: "0" } } });
    w.fire(req("/api/plugins/local-service/comfy", 300 * 1024));
    w.fire(req("/api/plugins", 1000));
    (w.context.appendHttpTraceAtCrash as (d: unknown, v: unknown) => void)({ reason: "crashed" }, 1);

    expect(w.written.filter((line) => line.startsWith("http-at-crash"))).toEqual([]);
    expect(w.written).toHaveLength(1);
    expect(w.written[0]).toMatch(/^plugins-dir-fetch n=1 /);
  });

  it("接法:记一笔在 /api/plugins 那个判断之前;崩的时候写 http-at-crash;filter 与 n= 一字不动", () => {
    expect(F.startPluginsDirectoryDiagnostics).toMatch(
      /if \(!\/\^https\?:\\\/\\\/\(\?:127\\\.0\\\.0\\\.1\|localhost\)[\s\S]{0,200}?traceHttpRequest\(details\);\n\s*if \(details\.url\.replace/,
    );
    expect(F.startPluginsDirectoryDiagnostics).toMatch(/\{ urls: \["\*:\/\/127\.0\.0\.1\/\*", "\*:\/\/localhost\/\*"\] \}/);
    expect(F.startPluginsDirectoryDiagnostics).toMatch(
      /`n=\$\{count\} local=\$\{localClock\(\)\} status=\$\{details\.statusCode\} bytes=\$\{length \?\? "\?"\} fromCache=\$\{Boolean\(details\.fromCache\)\}`/,
    );
    expect(MAIN).toMatch(/appendIpcTraceAtCrash\(details\);\n\s*\/\/[^\n]*\n\s*appendHttpTraceAtCrash\(details, ipcContentsId\(webContents\)\);/);
    // webRequest 每个事件只保留最后一个 listener:只许有一个观察者。
    expect(MAIN.match(/webRequest\.onCompleted\(/g)).toHaveLength(1);
  });
});
