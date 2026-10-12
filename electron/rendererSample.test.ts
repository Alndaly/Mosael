/**
 * 「那 9 秒里渲染进程**内部**在涨什么」这条线要有证据,就得每 500 ms 往页面里注入一段采样脚本,把页面自己说的读数
 * (堆 / DOM 节点数 / 帧 / readyState / visibilityState)写成一行,并在崩的那一刻补一条 `renderer-at-crash`。
 *
 * 这里钉住的是这条线**自己**会怎么坏:字段不齐、注入被叠(500 ms 一次的注入叠成一堆 rAF 链,于是「帧数异常」这件事
 * 被观测自己造出来)、executeJavaScript reject 时把 promise 抛出去、定时器拖住退出、开关关掉还留痕迹 ——
 * 以及最容易出事的那一条:**沙箱里点名的函数少了一个,会被那些 try/catch 静默吞掉**(测试全绿、真机才炸)。
 *
 * 用法照 memoryDiagnostics.test.ts / ipcTrace.test.ts:把 main.cjs 里的代码段**抠出来真跑**,只喂桩,不启动 Electron,
 * 更不会为了测试去崩一次应用。下面三个小工具(extract / stripComments / missingFromSandbox)与 memoryDiagnostics.test.ts
 * 里那三个同源 —— 那份没有导出它们,而 import 一个 .test.ts 会把它的用例一起拉起来,所以这里照抄一份。
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
  localClock: extract(/\nfunction localClock\(date = new Date\(\)\) \{[\s\S]*?\n\}\n/, "localClock"),
  sampleConstants: extract(
    /\nconst RENDERER_SAMPLE_MS = [^\n]*\n[\s\S]*?const RENDERER_SAMPLE_WINDOW_MS = [^\n]*\n/,
    "RENDERER_SAMPLE_* 常量",
  ),
  sampleMode: extract(/\nfunction rendererSampleMode\(env\) \{[\s\S]*?\n\}\n/, "rendererSampleMode"),
  sampleScript: extract(/\nconst RENDERER_SAMPLE_SCRIPT = `[\s\S]*?`;\n/, "RENDERER_SAMPLE_SCRIPT"),
  sampleState: extract(
    /\nconst rendererSamples = new Map\(\);\n[\s\S]*?const rendererSamplePending = new Set\(\);\n/,
    "rendererSamples / rendererSamplePending",
  ),
  finiteOrNull: extract(/\nfunction finiteOrNull\(value\) \{[\s\S]*?\n\}\n/, "finiteOrNull"),
  bytesToMb: extract(/\nfunction bytesToMb\(value\) \{[\s\S]*?\n\}\n/, "bytesToMb"),
  sampleLine: extract(/\nfunction rendererSampleLine\(identity, sample\) \{[\s\S]*?\n\}\n/, "rendererSampleLine"),
  sampleTrend: extract(/\nfunction rendererSampleTrend\(entries, crashAt\) \{[\s\S]*?\n\}\n/, "rendererSampleTrend"),
  sampleTargets: extract(/\nfunction rendererSampleTargets\(\) \{[\s\S]*?\n\}\n/, "rendererSampleTargets"),
  sampleOnce: extract(/\nasync function sampleRendererOnce\(contents\) \{[\s\S]*?\n\}\n/, "sampleRendererOnce"),
  startWatch: extract(/\nfunction startRendererSampleWatch\(\) \{[\s\S]*?\n\}\n/, "startRendererSampleWatch"),
  atCrash: extract(/\nfunction appendRendererSampleAtCrash\(details, contents\) \{[\s\S]*?\n\}\n/, "appendRendererSampleAtCrash"),
  // 采样链自己用到的两段既有的纯函数(和 ipc-at-crash 同一套 url/id 归一化)。
  ipcTraceUrl: extract(/\nfunction ipcTraceUrl\(raw\) \{[\s\S]*?\n\}\n/, "ipcTraceUrl"),
  ipcContentsId: extract(/\nfunction ipcContentsId\(contents\) \{[\s\S]*?\n\}\n/, "ipcContentsId"),
  ipcContentsUrl: extract(/\nfunction ipcContentsUrl\(contents\) \{[\s\S]*?\n\}\n/, "ipcContentsUrl"),
};

/** 注入页面里的那段脚本本身(模板字符串的内容)。 */
const PROBE = F.sampleScript.slice(F.sampleScript.indexOf("`") + 1, F.sampleScript.lastIndexOf("`"));

/**
 * 采样链整个能跑的沙箱:注入(executeJavaScript)→ 折行(rendererSampleLine)→ 记环 → 崩的那一刻(appendRendererSampleAtCrash)。
 *
 * 为什么「用到的」都要装进来:这些函数自带 try/catch(「页面正在崩 / 已销毁:这一次就算了」),沙箱里少一个函数不会
 * 报错,只会**静默**少写几行 —— 那正是「测试全绿、真机才炸」。所以下面有一条用例专门盯着这件事(missingFromSandbox)。
 */
const SAMPLING_SANDBOX = [
  F.localClock,
  F.sampleConstants,
  F.sampleMode,
  "const RENDERER_SAMPLE_MODE = rendererSampleMode(process.env);",
  F.sampleScript,
  F.sampleState,
  F.finiteOrNull,
  F.bytesToMb,
  F.sampleLine,
  F.sampleTrend,
  F.sampleTargets,
  F.ipcTraceUrl,
  F.ipcContentsId,
  F.ipcContentsUrl,
  F.sampleOnce,
  F.startWatch,
  F.atCrash,
  // 环里有什么、谁还挂着:用例要直接看这两个(它们本身是 const,不会变成 context 的属性)。
  "globalThis.__state = { rendererSamples, rendererSamplePending };",
].join("\n");

/** 桩的名字 + 语言关键字 + 宿主全局:它们不是「沙箱里少了一个函数」。 */
const CALL_ALLOWED = new Set([
  ...["appendDiagnosticLog", "process", "BrowserWindow", "isAppUrl", "setInterval"],
  ...["Number", "String", "Boolean", "Math", "JSON", "Object", "Array", "Map", "Set", "Symbol", "RegExp", "Date", "Error"],
  ...["if", "for", "while", "switch", "catch", "return", "typeof", "new", "function", "do", "else"],
]);

/**
 * 去掉注释。三步顺序照 memoryDiagnostics.test.ts 踩出来的那样,换一步就会把**代码**当注释吃掉
 * (扫描结果成了「什么都没调用」,这条断言于是永远绿 —— 正是它要防的那种静默)。
 */
function stripComments(source: string): string {
  return source
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''")
    .replace(/\/\/[^\n]*/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");
}

function missingFromSandbox(sandbox: string = SAMPLING_SANDBOX): string[] {
  const source = stripComments(sandbox);
  const declared = new Set(
    [...source.matchAll(/(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*))/g)]
      .flatMap((match) => [match[1], match[2]])
      .filter((name): name is string => Boolean(name)),
  );
  const called = new Set([...source.matchAll(/(?:^|[^\w.$])([A-Za-z_$][\w$]*)\s*\(/g)].map((match) => match[1]));
  return [...called].filter((name) => !declared.has(name) && !CALL_ALLOWED.has(name)).sort();
}

const APP_URL = "http://127.0.0.1:5173/#/plugins";

/** 一份「页面自己说的」读数(字段与注入脚本的返回值一致)。 */
function probeReply(over: Record<string, unknown> = {}) {
  return {
    at: 0,
    heapUsedBytes: 169 * 1024 * 1024,
    heapLimitBytes: 4096 * 1024 * 1024,
    nodes: 10_000,
    frames: 30,
    framesSinceInstall: 30,
    lastFrameAgoMs: 12,
    readyState: "complete",
    visibilityState: "visible",
    ...over,
  };
}

type SamplingStubs = {
  env?: Record<string, string>;
  uptime?: number;
  /** BrowserWindow 的桩:`{ isDestroyed?, webContents: { getURL() } }`。 */
  windows?: unknown[];
  appUrl?: (url: string) => boolean;
  /** 在沙箱**之前**跑:用来在那个 realm 里造桩或造错(跨 realm 的 `instanceof Error` 为假,错误必须造在里面)。 */
  prelude?: string;
  /** 固定时钟:`at` / `local` 因此可以钉死。 */
  clock?: { now: number };
};

/**
 * 把采样链放进一个干净的 realm 里跑。时钟是假的(`at`、`local` 要钉死,真时钟下这些断言只能靠 sleep)。
 */
function runSamplingChain(stubs: SamplingStubs = {}) {
  const written: string[] = [];
  const intervals: number[] = [];
  const unrefs: boolean[] = [];
  const clock = stubs.clock ?? { now: Date.UTC(2026, 0, 2, 3, 4, 5) };
  let tick: (() => void) | null = null;
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
    appendDiagnosticLog: (kind: string, detail: string | (() => string)) => {
      const line = typeof detail === "function" ? detail() : detail;
      // 和真的 appendDiagnosticLog 一样:空内容不写。
      if (line) written.push(`${kind} ${line}`);
    },
    process: { env: stubs.env ?? {}, uptime: () => stubs.uptime ?? 42, pid: 4242 },
    setInterval: (callback: () => void, ms: number) => {
      intervals.push(ms);
      tick = callback;
      return {
        unref: () => {
          unrefs.push(true);
        },
      };
    },
    BrowserWindow: { getAllWindows: () => stubs.windows ?? [] },
    isAppUrl: stubs.appUrl ?? ((url: string) => url.startsWith("http://127.0.0.1:5173")),
  };
  vm.runInNewContext(`${stubs.prelude ?? ""}\n${SAMPLING_SANDBOX}`, context);
  const state = context.__state as { rendererSamples: Map<number, { at: number; line: Record<string, unknown> }[]> };
  return {
    context,
    written,
    intervals,
    unrefs,
    clock,
    state,
    fire: () => tick?.(),
    /** 写出去的那几行,拆成 kind + 解析后的 JSON。 */
    lines: () =>
      written.map((line) => ({
        kind: line.split(" ")[0],
        text: line.slice(line.indexOf(" ") + 1),
        json: JSON.parse(line.slice(line.indexOf(" ") + 1)) as Record<string, unknown>,
      })),
  };
}

/** 一块只会照剧本回答的 webContents:每次 executeJavaScript 取一条预置的读数。 */
function stubContents(id: number, replies: unknown[], url = APP_URL) {
  const calls: string[] = [];
  let pending: ((value: unknown) => void) | null = null;
  return {
    id,
    calls,
    getURL: () => url,
    executeJavaScript: (code: string) => {
      calls.push(code);
      return new Promise<unknown>((resolve) => {
        pending = resolve;
        const reply = replies.shift();
        if (reply !== "hold") resolve(reply);
      });
    },
    /** 手动喂下一条读数(给「上一次还挂着」那条用例用)。 */
    release: (value: unknown) => pending?.(value),
  };
}

describe("注入页面的那段脚本", () => {
  /** 一个只有「帧」和「DOM 节点数」的假页面:只实现那段脚本真正碰到的东西。 */
  function fakeWorld(options: { nodes?: number; memory?: boolean } = {}) {
    const queued: (() => void)[] = [];
    const window: Record<string | symbol, unknown> = {
      requestAnimationFrame: (callback: () => void) => {
        queued.push(callback);
        return queued.length;
      },
    };
    const context: Record<string, unknown> = {
      window,
      document: {
        getElementsByTagName: () => ({ length: options.nodes ?? 1234 }),
        readyState: "complete",
        visibilityState: "visible",
      },
      performance: options.memory === false ? {} : { memory: { usedJSHeapSize: 169 * 1024 * 1024, jsHeapSizeLimit: 4096 * 1024 * 1024 } },
    };
    return {
      context,
      window,
      queued,
      /** 跑一帧:把排着的回调全放掉(回调自己会再排一个 —— 正常 rAF 链就是这样)。 */
      tick: () => {
        for (const callback of queued.splice(0, queued.length)) callback();
      },
    };
  }
  const runProbe = (world: ReturnType<typeof fakeWorld>) => vm.runInNewContext(PROBE, world.context) as Record<string, unknown>;

  it("幂等:同一段脚本注入两次只有一个计数器,不会叠出第二条 rAF 链", () => {
    // 500 ms 一次的注入如果不幂等,「帧数异常」这件事就是观测自己造出来的 —— 这一条是整块的地基。
    const world = fakeWorld();
    runProbe(world);
    expect(world.queued).toHaveLength(1);

    const second = runProbe(world);
    expect(world.queued).toHaveLength(1); // 还是那一条链
    expect(second.frames).toBe(0); // 同一个计数器:这一瞬间没有新帧

    world.tick();
    world.tick();
    expect(world.queued).toHaveLength(1); // 那条链自己续了一次,还是一条

    const third = runProbe(world);
    expect(third.frames).toBe(2); // 两帧数在同一个计数器上
    expect(third.framesSinceInstall).toBe(2); // 从头数到现在,也是 2
  });

  it("frames 是「这一窗口里跑了几帧」:0 就是 0(主线程卡住),紧跟着再读要归零", () => {
    const world = fakeWorld();
    const first = runProbe(world);
    expect(first.frames).toBe(0); // 刚装上,还没有帧
    world.tick();
    world.tick();
    world.tick();
    expect(runProbe(world).frames).toBe(3); // 上一次读之后跑了 3 帧
    expect(runProbe(world).frames).toBe(0); // 读走了就归零 —— 于是连续两行之间就是那一段的真实帧数
  });

  it("只读:没有 DOM / 存储 / 网络写入,也没有监听器;幂等那道门在", () => {
    expect(PROBE).toMatch(/if \(!probe\) \{/);
    expect(PROBE).toMatch(/window\[key\] = probe;/);
    expect(PROBE).toMatch(/Symbol\.for\("mosael\.renderer-sample"\)/);
    // 只读:读 DOM 只有 getElementsByTagName,别的一律不许出现(这一档绝不能改页面)。
    expect(PROBE).not.toMatch(
      /innerHTML|outerHTML|appendChild|insertBefore|removeChild|setAttribute|removeAttribute|classList|\.style|addEventListener|removeEventListener|localStorage|sessionStorage|document\.write|indexedDB|fetch\(|XMLHttpRequest|WebSocket|postMessage|dispatchEvent/,
    );
    // 它整段是 main.cjs 里的一个模板字符串:反引号或 ${ 混进来会把注入本身弄坏(而且是在真机上才坏)。
    expect(PROBE).not.toMatch(/[`$]\{/);
    expect(PROBE).not.toMatch(/`/);
  });

  it("读不到 performance.memory 时给 null(不是 0),DOM / 可见性照旧读得到", () => {
    const world = fakeWorld({ memory: false, nodes: 777 });
    const probe = runProbe(world);
    expect(probe.heapUsedBytes).toBeNull();
    expect(probe.heapLimitBytes).toBeNull();
    expect(probe.nodes).toBe(777);
    expect(probe.readyState).toBe("complete");
    expect(probe.visibilityState).toBe("visible");
  });
});

describe("renderer-sample 那一行", () => {
  it("字段齐:local / uptimeSec / heapUsedMB / heapLimitMB / nodes / frames / lastFrameAgoMs + readyState / visibilityState", () => {
    const { context } = runSamplingChain();
    const line = (context.rendererSampleLine as (identity: unknown, sample: unknown) => Record<string, unknown>)(
      { id: 7, url: APP_URL },
      probeReply(),
    );
    expect(line).toEqual({
      local: expect.stringMatching(/^\d\d:\d\d:\d\d$/),
      id: 7,
      url: APP_URL,
      uptimeSec: 42,
      heapUsedMB: 169,
      heapLimitMB: 4096,
      nodes: 10_000,
      frames: 30,
      lastFrameAgoMs: 12,
      framesSinceInstall: 30,
      readyState: "complete",
      visibilityState: "visible",
    });
  });

  it("读不到的字段是 null,不拿 0 顶替(0 会被读成「堆是空的」「DOM 是空的」)", () => {
    const { context } = runSamplingChain();
    const line = (context.rendererSampleLine as (identity: unknown, sample: unknown) => Record<string, unknown>)(
      undefined,
      { heapUsedBytes: Number.NaN, heapLimitBytes: Number.POSITIVE_INFINITY, nodes: "10000", frames: null, readyState: 7 },
    );
    expect(line).toEqual({
      local: expect.stringMatching(/^\d\d:\d\d:\d\d$/),
      id: null,
      url: null,
      uptimeSec: 42,
      heapUsedMB: null,
      heapLimitMB: null,
      nodes: null,
      frames: null,
      lastFrameAgoMs: null,
      framesSinceInstall: null,
      readyState: null,
      visibilityState: null,
    });
    // 页面一个字都没回(undefined)也一样,不是抛。
    expect((context.rendererSampleLine as (i: unknown, s: unknown) => Record<string, unknown>)({ id: 1 }, undefined)).toMatchObject({
      heapUsedMB: null,
      nodes: null,
    });
  });

  it("字节 → MB 保留一位小数;0 是合法的 0(和「读不到」不是一回事)", () => {
    const { context } = runSamplingChain();
    const bytesToMb = context.bytesToMb as (value: unknown) => number | null;
    expect(bytesToMb(177_000_000)).toBe(168.8);
    expect(bytesToMb(1048576)).toBe(1);
    expect(bytesToMb(0)).toBe(0);
    expect(bytesToMb(undefined)).toBeNull();
    expect(bytesToMb("1048576")).toBeNull();
  });
});

describe("崩的那一刻补一条 renderer-at-crash", () => {
  it("最后一次快照 + 最近这一段的走势(堆涨多快 / DOM 多了几个 / 帧率掉没掉)", async () => {
    const { context, clock, written } = runSamplingChain();
    const contents = stubContents(1, [
      probeReply({ heapUsedBytes: 169 * 1024 * 1024, nodes: 10_000, frames: 30, framesSinceInstall: 30 }),
      probeReply({ heapUsedBytes: 220 * 1024 * 1024, nodes: 10_000, frames: 30, framesSinceInstall: 60 }),
      probeReply({ heapUsedBytes: 300 * 1024 * 1024, nodes: 12_000, frames: 28, framesSinceInstall: 90, lastFrameAgoMs: 40 }),
    ]);
    const sample = context.sampleRendererOnce as (contents: unknown) => Promise<void>;
    for (let i = 0; i < 3; i += 1) {
      clock.now += 500; // 先走时间再采:三次采样落在 +500 / +1000 / +1500
      await sample(contents);
    }
    clock.now += 250; // 崩在最后一次采样之后 250 ms

    (context.appendRendererSampleAtCrash as (details: unknown, contents: unknown) => void)({ reason: "crashed", exitCode: 5 }, contents);

    const line = written.at(-1) as string;
    expect(line.startsWith("renderer-at-crash ")).toBe(true);
    const payload = JSON.parse(line.slice("renderer-at-crash ".length)) as Record<string, unknown>;
    expect(payload).toMatchObject({
      local: expect.stringMatching(/^\d\d:\d\d:\d\d$/),
      reason: "crashed",
      exitCode: 5,
      id: 1,
      url: APP_URL,
      samples: 3,
      lastAgoMs: 250,
    });
    // 最后一次快照是完整的那一行(和 renderer-sample 同一个形状)。
    expect(payload.last).toMatchObject({ heapUsedMB: 300, nodes: 12_000, frames: 28, lastFrameAgoMs: 40 });
    // 走势:1 秒里 169 → 300 MB(131 MB/s 这种量级一眼就是源码级的事故,不是抖动)。
    expect(payload.trend).toMatchObject({
      samples: 3,
      spanSec: 1,
      heapFromMB: 169,
      heapToMB: 300,
      heapMaxMB: 300,
      heapDeltaMB: 131,
      heapPerSecMB: 131,
      nodesFrom: 10_000,
      nodesTo: 12_000,
      nodesDelta: 2000,
      framesMin: 28,
      framesMax: 30,
    });
  });

  it("窗口外的旧读数不算进走势(窗口是崩前这一段,不是整轮)", async () => {
    const { context, clock, written } = runSamplingChain();
    const contents = stubContents(1, [
      probeReply({ heapUsedBytes: 100 * 1024 * 1024, framesSinceInstall: 30 }),
      probeReply({ heapUsedBytes: 320 * 1024 * 1024, framesSinceInstall: 60 }),
    ]);
    const sample = context.sampleRendererOnce as (contents: unknown) => Promise<void>;
    await sample(contents);
    clock.now += 30_000; // 中间隔了 30 秒:第一条掉出 10 秒窗口
    await sample(contents);

    (context.appendRendererSampleAtCrash as (details: unknown, contents: unknown) => void)({ reason: "crashed" }, contents);
    const payload = JSON.parse((written.at(-1) as string).slice("renderer-at-crash ".length)) as Record<string, unknown>;
    const trend = payload.trend as Record<string, unknown>;
    expect(trend.samples).toBe(1);
    expect(trend.heapFromMB).toBe(320); // 窗口里只有一条:from = to,涨了多少无从谈起
    expect(trend.heapDeltaMB).toBeNull();
    expect(trend.heapPerSecMB).toBeNull();
    expect(trend.nodesDelta).toBeNull();
    expect(payload.samples).toBe(2); // 环里仍然有两条(走势是窗口,不是环)
  });

  it("一条都没采到也照写一行:last 与 trend 都是 null —— 「没采到」不许被读成「很稳」", () => {
    const { context, written } = runSamplingChain();
    const contents = stubContents(9, []);
    (context.appendRendererSampleAtCrash as (details: unknown, contents: unknown) => void)({ reason: "crashed", exitCode: 5 }, contents);
    const payload = JSON.parse(written[0].slice("renderer-at-crash ".length)) as Record<string, unknown>;
    expect(payload).toMatchObject({ reason: "crashed", exitCode: 5, id: 9, url: APP_URL, samples: 0, lastAgoMs: null, last: null, trend: null });
  });

  it("页面重新载入过(崩后自动重载 / ⌘R):计数器从头数起 ⇒ 环里的旧文档读数丢掉,走势不许跨文档", async () => {
    const { context, clock, state } = runSamplingChain();
    const contents = stubContents(1, [
      probeReply({ heapUsedBytes: 700 * 1024 * 1024, framesSinceInstall: 900 }), // 崩前那一份文档,涨到 700 MB
      probeReply({ heapUsedBytes: 60 * 1024 * 1024, framesSinceInstall: 5 }), // 重载之后的**新文档**:计数器从头数
    ]);
    const sample = context.sampleRendererOnce as (contents: unknown) => Promise<void>;
    await sample(contents);
    clock.now += 500;
    await sample(contents);
    expect(state.rendererSamples.get(1)).toHaveLength(1);
    (context.appendRendererSampleAtCrash as (details: unknown, contents: unknown) => void)({ reason: "crashed" }, contents);
    expect((state.rendererSamples.get(1) as { line: Record<string, unknown> }[])[0].line.heapUsedMB).toBe(60);
  });
});

describe("采样循环(每 500 ms 一次,只注入只读脚本)", () => {
  it("500 ms 一格、unref、开机记一条开关横幅;目标只有停在应用地址上的那个 BrowserWindow", () => {
    const windows = [
      { isDestroyed: () => false, webContents: { id: 1, getURL: () => APP_URL } }, // 主窗口(#/plugins 在它里面)
      { isDestroyed: () => false, webContents: { id: 2, getURL: () => "https://creator.douyin.com/" } }, // 发布账号视图
      { isDestroyed: () => true, webContents: { id: 3, getURL: () => APP_URL } }, // 已经销毁
      { isDestroyed: () => false, webContents: { getURL: () => { throw new Error("gone"); } } }, // 读不到 URL
    ];
    const { context, written, intervals, unrefs } = runSamplingChain({ windows });
    (context.startRendererSampleWatch as () => void)();
    expect(intervals).toEqual([500]);
    expect(unrefs).toEqual([true]);
    expect(written).toEqual([expect.stringMatching(/^renderer-sample mode=on everyMs=500 ring=40 local=\d\d:\d\d:\d\d pid=4242$/)]);
    // 采样目标:按**窗口**挑,而不是按「URL 同源」—— 浮层页(frontend/float-layer.html)与主窗口同源,只按 URL 拦会把它一起采进来。
    expect((context.rendererSampleTargets as () => { id: number }[])().map((entry) => entry.id)).toEqual([1]);
    expect(F.sampleTargets).toMatch(/for \(const win of BrowserWindow\.getAllWindows\(\)\)/);
    expect(F.sampleTargets).toMatch(/if \(!isAppUrl\(win\.webContents\.getURL\(\)\)\) continue;/);
    // 没挂上定时器时,RENDERER_SAMPLE_MODE 那一行仍然说清楚「开着的」。
    expect(MAIN).toMatch(/function startRendererSampleWatch\(\) \{\n\s*if \(RENDERER_SAMPLE_MODE === "off"\) return;/);
  });

  it("开关关掉(MOSAEL_RENDERER_SAMPLE=0):定时器不起、一行都不写(连横幅也没有)", async () => {
    const { context, written, intervals, state } = runSamplingChain({ env: { MOSAEL_RENDERER_SAMPLE: "0" } });
    (context.startRendererSampleWatch as () => void)();
    expect(intervals).toEqual([]);
    // 直接调也一样:函数自己再判一次(定时器根本不该起来,这是第二道锁)。
    const contents = stubContents(1, [probeReply()]);
    await (context.sampleRendererOnce as (contents: unknown) => Promise<void>)(contents);
    (context.appendRendererSampleAtCrash as (details: unknown, contents: unknown) => void)({ reason: "crashed" }, contents);
    expect(contents.calls).toEqual([]);
    expect(state.rendererSamples.size).toBe(0);
    expect(written).toEqual([]);
  });

  it("executeJavaScript reject(页面正在崩)时:不外抛,也不写行;下一次还能照常采", async () => {
    const { context, written } = runSamplingChain();
    let mode = "reject";
    const contents = {
      id: 1,
      getURL: () => APP_URL,
      executeJavaScript: () => (mode === "reject" ? Promise.reject(new Error("renderer is gone")) : Promise.resolve(probeReply())),
    };
    // 「崩的时候它 reject」是这条链上唯一真正会发生的事:绝不许把 promise 抛出去。
    await expect((context.sampleRendererOnce as (contents: unknown) => Promise<void>)(contents)).resolves.toBeUndefined();
    expect(written).toEqual([]);
    expect((context.__state as { rendererSamplePending: Set<number> }).rendererSamplePending.size).toBe(0); // 没把自己锁死

    mode = "ok";
    await (context.sampleRendererOnce as (contents: unknown) => Promise<void>)(contents);
    expect(written).toHaveLength(1);
    expect(written[0].startsWith("renderer-sample ")).toBe(true);
  });

  it("上一次还没回来时不再注入(主线程卡住时不能把 promise 越堆越多)", async () => {
    const { context, written } = runSamplingChain();
    const contents = stubContents(1, ["hold"]);
    const sample = context.sampleRendererOnce as (contents: unknown) => Promise<void>;
    const first = sample(contents);
    const second = sample(contents); // 还挂着:直接返回
    await expect(second).resolves.toBeUndefined();
    expect(contents.calls).toHaveLength(1);

    contents.release(probeReply());
    await first;
    expect(contents.calls).toHaveLength(1);
    expect(written).toHaveLength(1);
  });

  it("定时器挂不上 / 回调里读目标抛了:都只记一行或一声不响,绝不许变成第二次崩溃", () => {
    // 错误造在 vm 自己的 realm 里:`instanceof Error` 跨 realm 为假,而现实里 setInterval 抛的是本 realm 的 Error。
    const broken = runSamplingChain({ prelude: 'globalThis.setInterval = () => { throw new Error("no timers"); };' });
    expect(() => (broken.context.startRendererSampleWatch as () => void)()).not.toThrow();
    // 横幅先出去(它说的是「这一档开着」),然后才是那一条 unavailable —— 两条合起来才分得清「关掉了」和「起不来」。
    expect(broken.written).toEqual([
      expect.stringMatching(/^renderer-sample mode=on everyMs=500 ring=40 local=\d\d:\d\d:\d\d pid=4242$/),
      expect.stringMatching(/^renderer-sample unavailable local=\d\d:\d\d:\d\d no timers$/),
    ]);
    expect(MAIN).toMatch(/appendDiagnosticLog\("renderer-sample", `unavailable local=\$\{localClock\(\)\} \$\{error instanceof Error \? error\.message : String\(error\)\}`\)/);

    // 回调本身:getAllWindows 抛出去 → 定时器回调必须自己兜住(抛出去就是主进程的未捕获异常)。
    const ticking = runSamplingChain({ prelude: 'globalThis.BrowserWindow = { getAllWindows() { throw new Error("no windows"); } };' });
    (ticking.context.startRendererSampleWatch as () => void)();
    expect(() => ticking.fire()).not.toThrow();
    expect(ticking.written).toHaveLength(1); // 只有那条横幅:回调里一声不响
    expect(MAIN).toMatch(/const timer = setInterval\(\(\) => \{\n\s*try \{\n\s*for \(const contents of rendererSampleTargets\(\)\) void sampleRendererOnce\(contents\);/);
  });

  it("定时器 unref(不许拖住退出)—— 和别的诊断同一条规矩", () => {
    const { context, unrefs } = runSamplingChain();
    (context.startRendererSampleWatch as () => void)();
    expect(unrefs).toEqual([true]);
    expect(F.startWatch).toMatch(/timer\.unref\?\.\(\);/);
  });
});

describe("接进 main.cjs", () => {
  it("在 whenReady 里起;既有那两条相邻关系一字不动(memory-spike→plugins-dir→ipc-rate 都被别的测试钉着)", () => {
    // 新的一档挂在**所有**既有诊断后面:插在中间会把 ipcTrace.test.ts / memoryDiagnostics.test.ts 里那两条
    // 「谁是下一个」的正则打断 —— 那两处不是这条线的,不能为了接自己而改它们。
    expect(MAIN).toMatch(/startIpcRateWatch\(\);\n\s*\/\/[^\n]*\n\s*startRendererSampleWatch\(\);/);
    expect(MAIN).toMatch(
      /startGpuDiagnostics\(\);\n\s*startPowerAndDisplayDiagnostics\(\);\n[\s\S]{0,200}?startMemoryDiagnostics\(\);\n\s*startMemorySpikeWatch\(\);\n\s*startPluginsDirectoryDiagnostics\(\);\n\s*\/\/[^\n]*\n\s*startIpcRateWatch\(\);/,
    );
    expect(MAIN).toMatch(/appendIpcTraceAtCrash\(details\);\n\s*\/\/[^\n]*\n\s*appendHttpTraceAtCrash\(details, ipcContentsId\(webContents\)\);\n\s*\/\/[^\n]*\n\s*appendRendererSampleAtCrash\(details, webContents\);/);
  });

  it("沙箱里点名的每个函数都真的在 —— 少一个就会被那些 try/catch 静默吞掉(测试全绿、真机才炸)", () => {
    expect(missingFromSandbox()).toEqual([]);
    // 反面自检:故意抽掉一段就该点名它(证明这条断言不是摆设)。
    expect(missingFromSandbox(SAMPLING_SANDBOX.replace(F.bytesToMb, ""))).toEqual(["bytesToMb"]);
    expect(missingFromSandbox(SAMPLING_SANDBOX.replace(F.finiteOrNull, ""))).toEqual(["finiteOrNull"]);
    // 间接被调用的那一段一样抓得到(ipcTraceUrl 只被 ipcContentsUrl 叫)。
    expect(missingFromSandbox(SAMPLING_SANDBOX.replace(F.ipcTraceUrl, ""))).toEqual(["ipcTraceUrl"]);
  });

  it("只注入、只读:webContents 上只有 executeJavaScript 这一处接触,没有别的写入面", () => {
    const block = extract(/\n\/\/ ─+ 渲染进程内部采样\(只读诊断\)─+\n[\s\S]*?\/\/ ─+ 渲染进程内部采样结束 ─+\n/, "渲染进程内部采样那一块");
    expect(block).toMatch(/contents\.executeJavaScript\(RENDERER_SAMPLE_SCRIPT\)/);
    expect(block).not.toMatch(
      /insertCSS|sendInputEvent|openDevTools|debugger\.attach|setZoomFactor|loadURL|reload\(|\.session|printToPDF|capturePage/,
    );
    expect(block).not.toMatch(/webRequest|onBeforeRequest/);
  });
});
