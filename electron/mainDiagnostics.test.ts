/**
 * 「下次崩溃 / 下次闪窗要留下可查的现场」这两件事都接在 main.cjs 上,这里钉住它们真的接上了。
 *
 * 规则本身很短,不值得单独抽模块;但「崩了有没有现场」这种能力平时看不出来 —— 没有测试就只能等下一次真崩。
 * 所以除了源码断言,崩溃上报那一段是从 main.cjs 里**抠出来真跑**的(和 mainLifecycle.test.ts 抠 zoomWindow 同一个用法):
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

describe("崩溃上报(crashReporter)", () => {
  const BLOCK = extract(/\nconst crashDumpsDir = app\.getPath\("crashDumps"\);[\s\S]*?\n\}\n/, "crash reporter block");

  /** 跑 main.cjs 里那一段真代码,喂桩。 */
  function run({ crashDumps, startError }: { crashDumps: string; startError?: string }) {
    const lines: string[] = [];
    const started: unknown[] = [];
    const context = {
      app: { name: "Mosael", getPath: (name: string) => (name === "crashDumps" ? crashDumps : "") },
      crashReporter: {
        start: (options: unknown) => {
          started.push(options);
          if (startError) throw (context as { boom?: Error }).boom;
        },
      },
      appendMainLog: (kind: string, line: string) => lines.push(`${kind} ${line}`),
      boom: undefined as unknown,
    };
    // 错误要在 vm 自己的 realm 里造:`instanceof Error` 跨 realm 为假,而现实里 crashReporter 抛出来的
    // 是本 realm 的 Error —— 桩得照着现实的样子抛。
    const prelude = startError ? `this.boom = new Error(${JSON.stringify(startError)});` : "";
    vm.runInNewContext(`${prelude}\n${BLOCK}`, context);
    return { lines, started };
  }

  it("只在本地收:uploadToServer 关掉,没有 submitURL(绝不外传)", () => {
    const { started } = run({ crashDumps: "/tmp/probe/Crashpad" });
    expect(started).toEqual([{ uploadToServer: false, productName: "Mosael" }]);
  });

  it("落点用 Electron 的 crashDumps 路径,并把绝对路径写进 main.log", () => {
    const { lines } = run({ crashDumps: "/Users/someone/Library/Application Support/Mosael/Crashpad" });
    expect(lines).toEqual(["crash-reporter started dumps=/Users/someone/Library/Application Support/Mosael/Crashpad"]);
    expect(MAIN).not.toMatch(/Library\/Application Support/); // 目录不写死,打包/冒烟换了 userData 也跟着走
  });

  it("必须在 app.whenReady() 之前 start —— 之后创建的渲染进程才在 crashpad 的监视里", () => {
    expect(MAIN.indexOf("crashReporter.start(")).toBeGreaterThan(-1);
    expect(MAIN.indexOf("crashReporter.start(")).toBeLessThan(MAIN.indexOf("app.whenReady()"));
    expect(MAIN).toMatch(/^const \{[\s\S]*?\bcrashReporter,\n/m);
  });

  it("上报起不来也不能把应用带走:只记一行 start failed", () => {
    const { lines } = run({ crashDumps: "/tmp/probe/Crashpad", startError: "no crashpad handler" });
    expect(lines).toEqual(["crash-reporter start failed: no crashpad handler"]);
  });

  it("不给自己留 process.crash() 之类的自测钩子", () => {
    expect(MAIN).not.toMatch(/process\.crash\(/);
  });
});

describe("崩溃那一刻的补充信号", () => {
  it("render-process-gone 除了 url/reason/exitCode,还记视图身份和当时的内存分布", () => {
    expect(MAIN).toMatch(/app\.on\("render-process-gone", \(_event, webContents, details\) => \{/);
    expect(MAIN).toMatch(/view: \{ id: webContents\.id, type: webContents\.getType\(\) \}/);
    expect(MAIN).toMatch(/memory: memorySnapshot\(\)/);
    expect(MAIN).toMatch(/\.\.\.details,/);
    expect(MAIN).toMatch(/process\s*\.getProcessMemoryInfo\(\)/);
  });

  it("内存快照按进程类型汇总 working set(拿不到就 null,不能少记崩溃本身)", () => {
    const source = extract(/\nfunction memorySnapshot\(\) \{[\s\S]*?\n\}\n/, "memorySnapshot");
    const context = {
      app: {
        getAppMetrics: () => [
          { type: "Browser", memory: { workingSetSize: 100 } },
          { type: "Tab", memory: { workingSetSize: 300 } },
          { type: "Tab", memory: { workingSetSize: 1 } },
          { type: "GPU" },
        ],
      },
      memorySnapshot: null as unknown as () => unknown,
    };
    vm.runInNewContext(`${source}; this.memorySnapshot = memorySnapshot;`, context);
    expect(context.memorySnapshot()).toEqual({ processes: 4, workingSetKb: 401, byType: { Browser: 100, Tab: 301, GPU: 0 } });

    const broken = { app: { getAppMetrics: () => { throw new Error("gone"); } }, memorySnapshot: null as unknown as () => unknown };
    vm.runInNewContext(`${source}; this.memorySnapshot = memorySnapshot;`, broken);
    expect(broken.memorySnapshot()).toBeNull();
  });
});

describe("「整窗闪」的现场", () => {
  it("启动时记一次 GPU 事实:特性状态 + 有没有人被命令行关掉硬件加速", () => {
    expect(MAIN).toMatch(/function startGpuDiagnostics\(\)/);
    expect(MAIN).toMatch(/app\.getGPUFeatureStatus\(\)/);
    expect(MAIN).toMatch(/\.getGPUInfo\("basic"\)/);
    expect(MAIN).toMatch(/hasSwitch\("disable-gpu"\)/);
    expect(MAIN).toMatch(/hasSwitch\("disable-gpu-compositing"\)/);
    expect(MAIN).toMatch(/appendDiagnosticLog\("gpu-facts"/);
    expect(MAIN).toMatch(/appendDiagnosticLog\("gpu-device"/);
    // 只读不改:不许去动硬件加速开关(那会改变现状,掩盖问题)。
    expect(MAIN).not.toMatch(/disableHardwareAcceleration\(\)/);
  });

  it("每 10 秒看一次 GPU 特性,只在值变了时记一行,并带上 uptime 好分辨「刚启动」和「跑到一半」", () => {
    expect(MAIN).toMatch(/setInterval\(\(\) => \{[\s\S]{0,900}?\}, 10_000\)/);
    expect(MAIN).toMatch(/const changed = gpuStatusDelta\(last, features\)/);
    expect(MAIN).toMatch(/changed=\$\{JSON\.stringify\(changed\)\} local=\$\{localClock\(\)\} uptimeSec=\$\{Math\.round\(process\.uptime\(\)\)\}/);
    expect(MAIN).toMatch(/return changed \? .* : "";/); // 没变就是空串,appendDiagnosticLog 不写空行
    expect(MAIN).toMatch(/timer\.unref\?\.\(\)/);
    // 启动时那一次「GPU 初始化完成」的翻转由 Chromium 自己的 gpu-info-update 说清楚,并顺手把轮询基线推过去 ——
    // 免得 10 秒后的第一跳把九项初始化变化报成事故。
    expect(MAIN).toMatch(/app\.on\("gpu-info-update", \(\) =>[\s\S]{0,400}?const \{ features, changed \} = readFeatures\(\);[\s\S]{0,200}?changed, features/);
    expect(MAIN).toMatch(/last = features;/);
  });

  it("gpuStatusDelta 只报变了的项(旧值 → 新值),没变返回 null", () => {
    const source = extract(/\nfunction gpuStatusDelta\(previous, current\) \{[\s\S]*?\n\}\n/, "gpuStatusDelta");
    const context = { gpuStatusDelta: null as unknown as (a: unknown, b: unknown) => unknown };
    vm.runInNewContext(`${source}; this.gpuStatusDelta = gpuStatusDelta;`, context);

    expect(context.gpuStatusDelta({ gpu_compositing: "enabled_on" }, { gpu_compositing: "enabled_on" })).toBeNull();
    expect(context.gpuStatusDelta({ gpu_compositing: "enabled_on" }, { gpu_compositing: "disabled_software" })).toEqual({
      gpu_compositing: ["enabled_on", "disabled_software"],
    });
    expect(context.gpuStatusDelta({ a: "enabled_on" }, {})).toEqual({ a: ["enabled_on", null] });
    expect(context.gpuStatusDelta(null, { a: "enabled_on" })).toEqual({ a: [null, "enabled_on"] });
  });

  it("电源 / 锁屏 / 显示器 / 窗口 / 卡住 这些事件各记一行", () => {
    expect(MAIN).toMatch(/for \(const name of \["suspend", "resume", "lock-screen", "unlock-screen", "on-ac", "on-battery"\]\)/);
    expect(MAIN).toMatch(/powerMonitor\.on\(name, \(\) => appendDiagnosticLog\("power", `\$\{name\} local=\$\{localClock\(\)\}`\)\)/);
    for (const event of ["display-metrics-changed", "display-added", "display-removed"]) {
      expect(MAIN).toMatch(new RegExp(`screen\\.on\\("${event}"`));
    }
    expect(MAIN).toMatch(/"show", "hide", "focus", "blur", "minimize", "restore", "enter-full-screen", "leave-full-screen"/);
    expect(MAIN).toMatch(/app\.on\("browser-window-created", \(_event, win\) => \{/);
    expect(MAIN).toMatch(/win\.on\(name, \(\) => appendDiagnosticLog\("window"/);
    expect(MAIN).toMatch(/for \(const name of \["unresponsive", "responsive"\]\)/);
    expect(MAIN).toMatch(/appendDiagnosticLog\(`web-contents-\$\{name\}`/);
  });

  it("诊断行都带本地时间:main.log 的时间戳是 UTC,和用户看到的钟差一个时区", () => {
    const source = extract(/\nfunction localClock\(date = new Date\(\)\) \{[\s\S]*?\n\}\n/, "localClock");
    const context = { localClock: null as unknown as (date?: Date) => string };
    vm.runInNewContext(`${source}; this.localClock = localClock;`, context);
    expect(context.localClock(new Date(2026, 0, 2, 3, 4, 5))).toBe("03:04:05");

    // 每一条诊断行(第一个参数是字面量的那些调用点)都必须带上本地时间,一条都不许漏。
    const calls = [...MAIN.matchAll(/appendDiagnosticLog\((?:`[^`]*`|"[^"]*")/g)];
    expect(calls.length).toBeGreaterThanOrEqual(10);
    for (const call of calls) {
      expect(MAIN.slice(call.index ?? 0).slice(0, 600)).toMatch(/local[=:]\s*(\$\{)?localClock\(\)/);
    }
  });

  it("记日志不许变成第二次崩溃:读状态抛了就这一条不写,空内容也不写", () => {
    const source = extract(/\nfunction appendDiagnosticLog\(kind, detail\) \{[\s\S]*?\n\}\n/, "appendDiagnosticLog");
    const written: string[] = [];
    const context = {
      appendMainLog: (kind: string, detail: string) => written.push(`${kind} ${detail}`),
      appendDiagnosticLog: null as unknown as (kind: string, detail: string | (() => string)) => void,
    };
    vm.runInNewContext(`${source}; this.appendDiagnosticLog = appendDiagnosticLog;`, context);

    context.appendDiagnosticLog("gpu-feature-status", () => "");
    expect(written).toEqual([]); // 10 秒一次的轮询没变就是空串,不许写成空行
    context.appendDiagnosticLog("window", () => "show local=03:04:05");
    context.appendDiagnosticLog("window", () => {
      throw new Error("window destroyed");
    });
    expect(written).toEqual(["window show local=03:04:05"]);
  });

  /**
   * 这两段跑在 whenReady 的**最前面**:抛出去,后面的起后端、建窗口就全走不到了(实测过:探针里没兜住的
   * 一次 `powerMonitor.on` 就把整个 ready 路径打断了)。诊断只许失败,不许拦路。
   */
  describe("诊断自己出问题时不许拦住启动", () => {
    const HELPERS = [
      extract(/\nfunction appendDiagnosticLog\(kind, detail\) \{[\s\S]*?\n\}\n/, "appendDiagnosticLog"),
      extract(/\nfunction localClock\(date = new Date\(\)\) \{[\s\S]*?\n\}\n/, "localClock"),
    ].join("\n");

    /** 桩里抛的错要在 vm 自己的 realm 里造(instanceof Error 跨 realm 为假)。 */
    function sandbox(stubs: Record<string, unknown>) {
      const written: string[] = [];
      const context: Record<string, unknown> = {
        appendMainLog: (kind: string, detail: string) => written.push(`${kind} ${detail}`),
        boom: undefined,
        ...stubs,
      };
      return { context, written };
    }

    it("GPU 那几项一个都拿不到:只记一行 unavailable", () => {
      const { context, written } = sandbox({
        app: {
          getGPUFeatureStatus: () => {
            throw (context as unknown as { boom: Error }).boom;
          },
          getGPUInfo: () => {
            throw (context as unknown as { boom: Error }).boom;
          },
          commandLine: { hasSwitch: () => false },
          on: () => undefined,
        },
        process: { uptime: () => 1 },
        setInterval: () => undefined,
      });
      const source = [HELPERS, extract(/\nfunction startGpuDiagnostics\(\) \{[\s\S]*?\n\}\n/, "startGpuDiagnostics")].join("\n");
      vm.runInNewContext(`this.boom = new Error("gpu unavailable");\n${source}; this.startGpuDiagnostics = startGpuDiagnostics;`, context);

      expect(() => (context as unknown as { startGpuDiagnostics: () => void }).startGpuDiagnostics()).not.toThrow();
      expect(written).toEqual([expect.stringMatching(/^gpu-facts unavailable local=\d\d:\d\d:\d\d gpu unavailable$/)]);
    });

    it("电源/显示器订阅不上:同样只记一行", () => {
      const { context, written } = sandbox({
        powerMonitor: {
          on: () => {
            throw (context as unknown as { boom: Error }).boom;
          },
        },
        screen: { on: () => undefined, getAllDisplays: () => [] },
      });
      const source = [
        HELPERS,
        extract(/\nfunction startPowerAndDisplayDiagnostics\(\) \{[\s\S]*?\n\}\n/, "startPowerAndDisplayDiagnostics"),
      ].join("\n");
      vm.runInNewContext(
        `this.boom = new Error("powerMonitor is not ready");\n${source}; this.startPowerAndDisplayDiagnostics = startPowerAndDisplayDiagnostics;`,
        context,
      );

      expect(() => (context as unknown as { startPowerAndDisplayDiagnostics: () => void }).startPowerAndDisplayDiagnostics()).not.toThrow();
      expect(written).toEqual([expect.stringMatching(/^display unavailable local=\d\d:\d\d:\d\d powerMonitor is not ready$/)]);
    });
  });
});
