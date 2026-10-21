/**
 * Computer Use P0(ADR 0075)的 Electron 一侧:只截 **Mosael 自己的窗口**。
 *
 * 不碰真屏幕、不申请屏幕录制权限:这里用替身窗口,只钉三件事 ——
 *   · 按 `window` 参数挑的是哪一个窗口(截的必须是它,别的窗口一下都不许碰);
 *   · 没有窗口 / 窗口最小化 / 拿到空图时,回来的是**一句人话**;
 *   · 走的是 `webContents.capturePage()`,不是系统截屏(`desktopCapturer` / `screencapture`)。
 */
import crypto from "node:crypto";
import fs from "node:fs";
import net, { type AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

const MAIN = fs.readFileSync(path.resolve(__dirname, "main.cjs"), "utf8");

// CommonJS is intentional: main.cjs and preload.cjs load this exact runtime contract.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const contract = require("./ipc-contract.cjs") as {
  IPC: { invoke: Record<string, string> };
  parseComputerScreenshot: (value: unknown) => { window: string };
};

function sourceOf(name: string): string {
  // 顶层函数以列 0 的 `}` 收尾;内层块都是缩进的,所以非贪婪匹配不会截到半个函数。
  const found = MAIN.match(new RegExp(`\\n(?:async )?function ${name}\\([\\s\\S]*?\\n\\}\\n`))?.[0];
  if (!found) throw new Error(`${name} 没在 main.cjs 里找到`);
  return found;
}

/** 窗口名常量也在 main.cjs 里,和函数一起塞进沙箱,免得测试自己抄第二份名单。 */
function windowNamesSource(): string {
  const found = MAIN.match(/\nconst COMPUTER_WINDOW_NAMES = [^\n]+\n/)?.[0];
  if (!found) throw new Error("COMPUTER_WINDOW_NAMES 没在 main.cjs 里找到");
  return found;
}

type FakeImage = {
  isEmpty: () => boolean;
  getSize: () => { width: number; height: number };
  toPNG: () => Buffer;
};

type FakeWindow = {
  label: string;
  webContents: { capturePage: ReturnType<typeof vi.fn> };
  isDestroyed: () => boolean;
  isMinimized: () => boolean;
};

function fakeWindow(
  label: string,
  options: { destroyed?: boolean; minimized?: boolean; image?: FakeImage } = {},
): FakeWindow {
  const image =
    options.image ??
    ({
      isEmpty: () => false,
      getSize: () => ({ width: 800, height: 600 }),
      toPNG: () => Buffer.from(`png:${label}`),
    } satisfies FakeImage);
  return {
    label,
    webContents: { capturePage: vi.fn(async () => image) },
    isDestroyed: () => options.destroyed ?? false,
    isMinimized: () => options.minimized ?? false,
  };
}

function loadCapture() {
  const context = {
    Object,
    String,
    Error,
    Boolean,
    Number,
    Promise,
    Buffer,
    chooseComputerWindow: undefined as unknown as (
      name: string,
      windows: FakeWindow[],
      roles: Record<string, FakeWindow | undefined>,
    ) => FakeWindow | null,
    captureMosaelWindow: undefined as unknown as (
      request: unknown,
      windows: FakeWindow[],
      roles: Record<string, FakeWindow | undefined>,
    ) => Promise<{ window: string; width: number; height: number; image: string }>,
  };
  vm.runInNewContext(
    `${windowNamesSource()}\n${sourceOf("chooseComputerWindow")}\n${sourceOf("captureMosaelWindow")}\n` +
      "this.chooseComputerWindow = chooseComputerWindow;\n" +
      "this.captureMosaelWindow = captureMosaelWindow;",
    context,
  );
  return context;
}

describe("computer_screenshot 的 IPC 契约", () => {
  it("通道名是 computer:screenshot,缺省截主窗口,只认 main / publish", () => {
    expect(contract.IPC.invoke.computerScreenshot).toBe("computer:screenshot");
    expect(contract.parseComputerScreenshot(undefined)).toEqual({ window: "main" });
    expect(contract.parseComputerScreenshot({})).toEqual({ window: "main" });
    expect(contract.parseComputerScreenshot({ window: "main" })).toEqual({ window: "main" });
    expect(contract.parseComputerScreenshot({ window: " PUBLISH " })).toEqual({ window: "publish" });
    expect(() => contract.parseComputerScreenshot({ window: "desktop" })).toThrow(/main.*publish/);
    expect(() => contract.parseComputerScreenshot({ window: "main", scale: 0.5 })).toThrow(/unexpected/);
  });
});

describe("按 window 参数挑窗口", () => {
  it("main 挑主窗口,publish 挑发布窗口 —— 不会退回到「随便哪个窗口」", () => {
    const main = fakeWindow("main");
    const publish = fakeWindow("publish");
    const { chooseComputerWindow } = loadCapture();

    expect(chooseComputerWindow("main", [publish, main], { main, publish })).toBe(main);
    expect(chooseComputerWindow("publish", [main, publish], { main, publish })).toBe(publish);
    expect(chooseComputerWindow("publish", [main], { main })).toBeNull();
  });

  it("不认识的窗口名是一句人话,不是一句 undefined", () => {
    const { chooseComputerWindow } = loadCapture();
    expect(() => chooseComputerWindow("desktop", [], {})).toThrow(/Unknown window "desktop".*"main".*"publish"/);
  });
});

describe("截的是 Mosael 自己的窗口", () => {
  it("用被选中那个窗口的 webContents.capturePage(),别的窗口一下都不碰", async () => {
    const main = fakeWindow("main");
    const publish = fakeWindow("publish", {
      image: { isEmpty: () => false, getSize: () => ({ width: 1024, height: 768 }), toPNG: () => Buffer.from("pub") },
    });
    const { captureMosaelWindow } = loadCapture();

    const shot = await captureMosaelWindow({ window: "publish" }, [main, publish], { main, publish });

    expect(publish.webContents.capturePage).toHaveBeenCalledTimes(1);
    expect(main.webContents.capturePage).not.toHaveBeenCalled();
    expect(shot).toEqual({
      window: "publish",
      width: 1024,
      height: 768,
      image: Buffer.from("pub").toString("base64"),
    });
  });

  it("不给 window 就截主窗口,回来的是它的尺寸和 PNG(转 base64 由后端做)", async () => {
    const main = fakeWindow("main");
    const { captureMosaelWindow } = loadCapture();

    const shot = await captureMosaelWindow(undefined, [main], { main });

    expect(main.webContents.capturePage).toHaveBeenCalledTimes(1);
    expect(shot).toEqual({
      window: "main",
      width: 800,
      height: 600,
      image: Buffer.from("png:main").toString("base64"),
    });
  });

  it("主窗口没开 / 已经销毁时回一条可读错误", async () => {
    const { captureMosaelWindow } = loadCapture();
    await expect(captureMosaelWindow({ window: "main" }, [], {})).rejects.toThrow(/no main window/i);

    const destroyed = fakeWindow("main", { destroyed: true });
    await expect(captureMosaelWindow({ window: "main" }, [destroyed], { main: destroyed })).rejects.toThrow(
      /no main window/i,
    );
    expect(destroyed.webContents.capturePage).not.toHaveBeenCalled();
  });

  it("窗口最小化、或 capturePage 拿到空图时,也说清楚是怎么回事", async () => {
    const { captureMosaelWindow } = loadCapture();
    const minimized = fakeWindow("main", { minimized: true });
    await expect(captureMosaelWindow({ window: "main" }, [minimized], { main: minimized })).rejects.toThrow(
      /minimi[sz]ed/i,
    );

    const blank = fakeWindow("main", {
      image: { isEmpty: () => true, getSize: () => ({ width: 0, height: 0 }), toPNG: () => Buffer.alloc(0) },
    });
    await expect(captureMosaelWindow({ window: "main" }, [blank], { main: blank })).rejects.toThrow(/empty/i);
  });
});

describe("接线:IPC + 回环桥都走同一个拍摄函数", () => {
  it("注册了 IPC 处理器,而且它拿的是 BrowserWindow 里的窗口和主窗口引用", () => {
    expect(MAIN).toMatch(/handle\(IPC\.invoke\.computerScreenshot,/);
    expect(MAIN).toMatch(
      /captureMosaelWindow\(\s*parseComputerScreenshot\([^)]*\),\s*BrowserWindow\.getAllWindows\(\),\s*\{\s*main: mainWindow\s*\}/,
    );
  });

  it("后端那条桥也只认 computer:screenshot,并复用同一个解析器和拍摄函数", () => {
    expect(MAIN).toMatch(/function startHostBridge\(/);
    expect(MAIN).toMatch(/request\.channel !== IPC\.invoke\.computerScreenshot/);
    // 桥的地址与令牌落在数据目录的 host-bridge.json(0600),后端按同一个数据目录找它。
    expect(MAIN).toMatch(/const HOST_BRIDGE_FILE = "host-bridge\.json"/);
    expect(MAIN).toMatch(/fs\.writeFileSync\(hostBridgeFile\(\), JSON\.stringify\(\{ port: hostBridge\.port, token \}\), \{ mode: 0o600 \}\)/);
    expect(MAIN).toMatch(/stringify\(\{ port: hostBridge\.port, token \}\)/);
    expect(MAIN).toMatch(/hostBridgeTokenMatches\(request\.token\)/);
  });

  it("拉起后端时经环境变量把桥的端口与令牌交过去,退出时收掉桥", () => {
    // 壳拉起的后端走环境变量(壳自己知道端口/令牌,不必读文件);令牌不进 argv、不进日志。
    expect(MAIN).toMatch(/MOSAEL_HOST_BRIDGE_PORT: hostBridge \? String\(hostBridge\.port\) : ""/);
    expect(MAIN).toMatch(/MOSAEL_HOST_BRIDGE_TOKEN: hostBridge \? hostBridge\.token : ""/);
    // 壳退出时桥和那份 0600 文件一起收掉,后端下次会回一句人话而不是连一个没人听的端口。
    expect(MAIN).toMatch(/app\.on\("will-quit",[\s\S]*stopHostBridge\(\)/);
  });

  it("拍的是应用自己的渲染:capturePage,不是系统截屏", () => {
    const body = sourceOf("captureMosaelWindow");
    expect(body).toMatch(/webContents\.capturePage\(\)/);
    expect(body).not.toMatch(/desktopCapturer|screencapture|getSources/);
  });
});

// ---------------- 宿主桥的安全边界 ----------------
//
// 后端跑在另一个进程里，它要拍图只能经这条**只绑回环**的一问一答桥。桥的形状就是威胁模型：
// 本机别的进程也能连到这个端口，能挡住它们的是「端口随机 + 每进程随机令牌 + 只认一条通道」，
// 而不是「反正只有我们自己会连」。下面四条是必须守住的边界 —— 少一条，这条桥就从内部通道
// 变成一台本机可执行面。
//
// 这里起的是**真的 TCP 服务**（只绑 127.0.0.1、端口 0），只是把窗口和 capturePage 换成替身：
// 测的是握手、鉴权、路由和绑定地址，不是真屏幕。

type BridgeReply = {
  ok: boolean;
  status?: number;
  error?: string;
  result?: Record<string, unknown>;
};

type HostBridge = {
  port: number;
  token: string;
  server: { address: () => AddressInfo | string | null; close: () => void };
};

type BridgeHarness = {
  dataDir: string;
  logs: string[];
  bridge: HostBridge;
  ask: (message: unknown) => Promise<BridgeReply>;
  close: () => void;
};

/** 从 main.cjs 里原样取出桥的实现（和上面两个函数同一套做法：测试不抄第二份实现）。 */
function bridgeSources(): string {
  const constant = (name: string): string => {
    const found = MAIN.match(new RegExp(`\\nconst ${name} = [^\\n]+\\n`))?.[0];
    if (!found) throw new Error(`${name} 没在 main.cjs 里找到`);
    return found;
  };
  return [
    windowNamesSource(),
    constant("HOST_BRIDGE_FILE"),
    constant("HOST_BRIDGE_MAX_REQUEST"),
    "let hostBridge = null;\nlet hostBridgeStarting = null;\n",
    sourceOf("hostBridgeFile"),
    sourceOf("chooseComputerWindow"),
    sourceOf("captureMosaelWindow"),
    sourceOf("hostBridgeTokenMatches"),
    sourceOf("replyHostBridge"),
    sourceOf("answerHostBridgeRequest"),
    sourceOf("startHostBridge"),
    sourceOf("startHostBridgeOnce"),
    sourceOf("stopHostBridge"),
  ].join("\n");
}

function askBridge(port: number, message: unknown): Promise<BridgeReply> {
  return new Promise((resolve, reject) => {
    let buffered = "";
    let settled = false;
    const finish = (error: Error | null, reply?: BridgeReply) => {
      if (settled) return;
      settled = true;
      if (error) reject(error);
      else resolve(reply as BridgeReply);
    };
    const socket = net.createConnection({ host: "127.0.0.1", port }, () => {
      socket.write(`${JSON.stringify(message)}\n`);
    });
    socket.setEncoding("utf8");
    socket.setTimeout(5_000, () => {
      socket.destroy();
      finish(new Error("宿主桥超时未回话"));
    });
    socket.on("data", (chunk: string) => {
      buffered += chunk;
    });
    socket.on("error", (error) => finish(error));
    socket.on("end", () => {
      const line = buffered.split("\n")[0] ?? "";
      if (!line) return finish(new Error(`宿主桥没有回话（收到 ${JSON.stringify(buffered)}）`));
      try {
        finish(null, JSON.parse(line) as BridgeReply);
      } catch (error) {
        finish(error as Error);
      }
    });
    socket.on("close", () => {
      if (!buffered) finish(new Error("宿主桥关掉了连接，没有回话"));
    });
  });
}

/** 起一个真的桥：数据目录用临时目录，窗口和 capturePage 是替身，其余原样。 */
async function startBridge(options: { windows: FakeWindow[]; main?: FakeWindow | null }): Promise<BridgeHarness> {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-host-bridge-"));
  const logs: string[] = [];
  const context = {
    Buffer,
    JSON,
    fs,
    path,
    crypto,
    nodeNet: net,
    configuredDataDir: dataDir,
    appendMainLog: (scope: string, message: unknown) => {
      logs.push(`${scope}: ${String(message)}`);
    },
    IPC: contract.IPC,
    parseComputerScreenshot: contract.parseComputerScreenshot,
    BrowserWindow: { getAllWindows: () => options.windows },
    mainWindow: options.main ?? null,
  };
  const api = vm.runInNewContext(`${bridgeSources()}\n({ startHostBridge, stopHostBridge })`, context) as {
    startHostBridge: () => Promise<HostBridge>;
    stopHostBridge: () => void;
  };
  const bridge = await api.startHostBridge();
  return {
    dataDir,
    logs,
    bridge,
    ask: (message) => askBridge(bridge.port, message),
    close: () => {
      api.stopHostBridge();
      fs.rmSync(dataDir, { recursive: true, force: true });
    },
  };
}

describe("宿主桥的安全边界", () => {
  it("没有令牌的请求一律 401 —— 而且一下都不碰窗口", async () => {
    const main = fakeWindow("main");
    const bridge = await startBridge({ windows: [main], main });
    try {
      const reply = await bridge.ask({ channel: "computer:screenshot", payload: {} });
      expect(reply).toMatchObject({ ok: false, status: 401 });
      expect(main.webContents.capturePage).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });

  it("令牌错了也是 401（等长、只有最后一个字符不同也一样）", async () => {
    const main = fakeWindow("main");
    const bridge = await startBridge({ windows: [main], main });
    try {
      const wrong = `${"0".repeat(bridge.bridge.token.length - 1)}x`;
      const reply = await bridge.ask({ token: wrong, channel: "computer:screenshot", payload: {} });
      expect(reply).toMatchObject({ ok: false, status: 401 });
      expect(main.webContents.capturePage).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });

  it("令牌对、但方法不是 screenshot —— 直接拒，桥不是通用 RPC", async () => {
    const main = fakeWindow("main");
    const bridge = await startBridge({ windows: [main], main });
    try {
      const reply = await bridge.ask({
        token: bridge.bridge.token,
        channel: "computer:click",
        payload: { x: 10, y: 20 },
      });
      expect(reply).toMatchObject({ ok: false, status: 405 });
      expect(reply.error).toMatch(/computer:screenshot/);
      expect(main.webContents.capturePage).not.toHaveBeenCalled();

      // 换一个真实存在的通道名也一样：桥背后没有第二个处理器。
      const other = await bridge.ask({
        token: bridge.bridge.token,
        channel: contract.IPC.invoke.saveFileBegin,
        payload: {},
      });
      expect(other.ok).toBe(false);
      expect(main.webContents.capturePage).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });

  it("只监听 127.0.0.1（不是 0.0.0.0），端口由系统随机挑", async () => {
    const main = fakeWindow("main");
    const bridge = await startBridge({ windows: [main], main });
    try {
      const address = bridge.bridge.server.address() as AddressInfo;
      expect(address.address).toBe("127.0.0.1");
      expect(address.family).toBe("IPv4");
      expect(address.port).toBeGreaterThan(0);
    } finally {
      bridge.close();
    }
  });

  it("令牌文件只有本人可读（0600），令牌不进日志，退出时文件跟着收掉", async () => {
    const main = fakeWindow("main");
    const bridge = await startBridge({ windows: [main], main });
    const file = path.join(bridge.dataDir, "host-bridge.json");
    try {
      expect(fs.statSync(file).mode & 0o777).toBe(0o600);
      expect(bridge.logs.join("\n")).not.toContain(bridge.bridge.token);
      await bridge.ask({ token: "wrong", channel: "computer:screenshot", payload: {} });
      expect(bridge.logs.join("\n")).not.toContain(bridge.bridge.token);
    } finally {
      bridge.close();
    }
    expect(fs.existsSync(file)).toBe(false);
  });

  it("令牌对、通道对，才真的拍 —— 用的是被选中窗口的 capturePage", async () => {
    const main = fakeWindow("main");
    const publish = fakeWindow("publish");
    const bridge = await startBridge({ windows: [main, publish], main });
    try {
      const reply = await bridge.ask({
        token: bridge.bridge.token,
        channel: "computer:screenshot",
        payload: { window: "main" },
      });
      expect(reply.ok).toBe(true);
      expect(reply.result).toMatchObject({ window: "main", width: 800, height: 600 });
      expect(main.webContents.capturePage).toHaveBeenCalledTimes(1);
      expect(publish.webContents.capturePage).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });

  it("令牌对、参数不对（未知窗口）—— 回一句人话，不拍", async () => {
    const main = fakeWindow("main");
    const bridge = await startBridge({ windows: [main], main });
    try {
      const reply = await bridge.ask({
        token: bridge.bridge.token,
        channel: "computer:screenshot",
        payload: { window: "desktop" },
      });
      expect(reply).toMatchObject({ ok: false, status: 400 });
      expect(reply.error).toMatch(/"main".*"publish"/);
      expect(main.webContents.capturePage).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });
});
