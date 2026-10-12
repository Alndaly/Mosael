/**
 * 「渲染进程的 CHECK 文案要落到文件里」这件事接在 main.cjs 上,这里钉住它真的接上了。
 *
 * 为什么值得单独钉:这条通道平时**看不出来** —— 没有测试就只能等下一次真崩,而它恰恰是为「下一次崩」准备的。
 * 和 mainDiagnostics.test.ts 同一个用法:那段代码从 main.cjs 里**抠出来真跑**(只喂桩),不启动 Electron、
 * 更不会为了测试去崩一次应用;另外几条是源码断言(开关的语义、加开关的时机、路径不许写死)。
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

describe("Chromium / 渲染进程日志通道(startChromiumLogging)", () => {
  const BLOCK = extract(/\nfunction startChromiumLogging\(\) \{[\s\S]*?\n\}\n/, "startChromiumLogging");

  /** 跑 main.cjs 里那一段真代码,喂桩。 */
  function run({ verbose = false, boom = "" } = {}) {
    const lines: string[] = [];
    const switches: Array<[string, string]> = [];
    const order: string[] = [];
    const context: Record<string, unknown> = {
      // env 只给这一个键:verbose 档就是靠它开的。
      process: { env: verbose ? { MOSAEL_CHROMIUM_LOG: "1" } : {}, pid: 4242 },
      chromiumLogPath: "/tmp/mosael-electron-user-data/logs/chromium.log",
      rotateLogIfLarge: (file: string) => order.push(`rotate:${file}`),
      appendMainLog: (kind: string, detail: string) => lines.push(`${kind} ${detail}`),
      localClock: () => "03:04:05",
      app: {
        commandLine: {
          appendSwitch: (name: string, value: string) => {
            if (boom) throw (context as unknown as { err: Error }).err;
            order.push(`switch:${name}=${value}`);
            switches.push([name, value]);
          },
        },
      },
      err: undefined,
    };
    // 错误要在 vm 自己的 realm 里造:`instanceof Error` 跨 realm 为假,而现实里 appendSwitch 抛的是本 realm 的 Error。
    const prelude = boom ? `this.err = new Error(${JSON.stringify(boom)});` : "";
    vm.runInNewContext(`${prelude}\n${BLOCK}; this.startChromiumLogging = startChromiumLogging;`, context);
    (context as unknown as { startChromiumLogging: () => void }).startChromiumLogging();
    return { lines, switches, order };
  }

  it("默认档:落文件 + 只要 ERROR 及以上,并把落点和档位写进 main.log", () => {
    const { lines, switches } = run();
    // Electron 的语义:`--enable-logging` 单独用是 stderr,`=file` 才是文件(shell/common/logging.cc)。
    expect(switches).toEqual([
      ["enable-logging", "file"],
      ["log-file", "/tmp/mosael-electron-user-data/logs/chromium.log"],
      ["log-level", "2"],
    ]);
    expect(lines).toEqual([
      "chromium-log file=/tmp/mosael-electron-user-data/logs/chromium.log level=error local=03:04:05 pid=4242",
    ]);
  });

  it("verbose 档(MOSAEL_CHROMIUM_LOG=1):放开级别并加 --v=1,文件还是同一个", () => {
    const { lines, switches } = run({ verbose: true });
    expect(switches).toEqual([
      ["enable-logging", "file"],
      ["log-file", "/tmp/mosael-electron-user-data/logs/chromium.log"],
      ["v", "1"],
    ]);
    // 两档不能同时给:--v 自己就把最低级别压到 VERBOSE,--log-level 会被 Electron 忽略(GetMinLogLevel() < 0)。
    expect(switches.map(([name]) => name)).not.toContain("log-level");
    expect(lines[0]).toContain("level=verbose");
  });

  it("默认档不许带 --v:用户日志不能被 verbose 刷爆", () => {
    expect(run().switches.map(([name]) => name)).not.toContain("v");
    expect(MAIN).toMatch(/process\.env\.MOSAEL_CHROMIUM_LOG === "1"/);
  });

  it("先轮转再开文件:此刻 Chromium 还没打开它,重命名不会把正在写的 fd 甩掉", () => {
    const { order } = run();
    expect(order[0]).toBe("rotate:/tmp/mosael-electron-user-data/logs/chromium.log");
    expect(order.indexOf("switch:log-file=/tmp/mosael-electron-user-data/logs/chromium.log")).toBeGreaterThan(0);
  });

  it("开关加不上也不能把应用带走:只记一行 failed", () => {
    const { lines } = run({ boom: "command line is frozen" });
    expect(lines).toEqual(["chromium-log failed: command line is frozen"]);
  });

  it("落点跟着 userData 走,不写死路径(冒烟换了 userData 也要跟着换)", () => {
    expect(MAIN).toMatch(/const chromiumLogPath = path\.join\(electronLogDir, "chromium\.log"\);/);
    expect(MAIN).not.toMatch(/Library\/Application Support/);
    expect(MAIN).not.toMatch(/\/Users\//);
    expect(MAIN).not.toMatch(/MOSAEL_CHROMIUM_LOG_FILE/); // 没有第二条自造的路径开关
  });

  it("必须在 app.whenReady() 之前加开关 —— 之后创建的渲染进程才吃得到", () => {
    const called = MAIN.indexOf("startChromiumLogging();");
    expect(called).toBeGreaterThan(-1);
    expect(called).toBeLessThan(MAIN.indexOf("app.whenReady()"));
    // 渲染进程拿到的 argv 里有这两个开关(实测),前提就是它们加在 fork 之前。
    expect(MAIN).toMatch(/app\.commandLine\.appendSwitch\("log-file", chromiumLogPath\)/);
  });

  it("记的是**本地**墙钟:要和 main.log 里 render-process-gone 那行的 local=HH:MM:SS 对得上", () => {
    const { lines } = run();
    expect(lines[0]).toMatch(/local=\d\d:\d\d:\d\d/);
    expect(MAIN).toMatch(/appendMainLog\(\s*"chromium-log",\s*`file=\$\{chromiumLogPath\} level=\$\{verbose \? "verbose" : "error"\} local=\$\{localClock\(\)\} pid=\$\{process\.pid\}`/);
  });

  it("轮转沿用 main.log 那一套(同目录、同 .1 后缀、同一个函数)", () => {
    expect(BLOCK).toMatch(/rotateLogIfLarge\(chromiumLogPath\)/);
    expect(MAIN).toMatch(/function rotateLogIfLarge\(file, maxBytes = 5 \* 1024 \* 1024\)/);
  });

  it("只加日志通道:不碰窗口 / 硬件加速 / 已有的崩溃上报", () => {
    expect(MAIN).not.toMatch(/disableHardwareAcceleration\(\)/);
    expect(BLOCK).not.toMatch(/new BrowserWindow|loadURL|disable-gpu/);
    // 已有的那几段原样留着(crash-reporter / render-process-gone / gpu-facts)。
    expect(MAIN).toMatch(/crashReporter\.start\(\{ uploadToServer: false, productName: app\.name \}\)/);
    expect(MAIN).toMatch(/app\.on\("render-process-gone", \(_event, webContents, details\) => \{/);
    expect(MAIN).toMatch(/function startGpuDiagnostics\(\)/);
  });
});
