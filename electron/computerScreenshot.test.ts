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
const DRIVER = fs.readFileSync(path.resolve(__dirname, "computerUse/ownWindowDriver.cjs"), "utf8");

// CommonJS is intentional: main.cjs and preload.cjs load this exact runtime contract.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const contract = require("./ipc-contract.cjs") as {
  IPC: { invoke: Record<string, string> };
  parseComputerScreenshot: (value: unknown) => { window: string };
};

function sourceOf(name: string): string {
  // 顶层函数以列 0 的 `}` 收尾;内层块都是缩进的,所以非贪婪匹配不会截到半个函数。
  const pattern = new RegExp(`\\n(?:async )?function ${name}\\([\\s\\S]*?\\n\\}\\n`);
  const found = DRIVER.match(pattern) ?? MAIN.match(pattern);
  if (!found) throw new Error(`${name} 没在 ownWindowDriver.cjs 里找到`);
  return found[0];
}

type FakeImage = {
  isEmpty: () => boolean;
  getSize: () => { width: number; height: number };
  toPNG: () => Buffer;
};

type FakeWindow = {
  label: string;
  webContents: { capturePage: ReturnType<typeof vi.fn>; getSize?: () => [number, number] };
  isDestroyed: () => boolean;
  isMinimized: () => boolean;
  getContentSize?: () => [number, number];
};

function fakeWindow(
  label: string,
  options: {
    destroyed?: boolean;
    minimized?: boolean;
    image?: FakeImage;
    contentSize?: [number, number];
  } = {},
): FakeWindow {
  const image =
    options.image ??
    ({
      isEmpty: () => false,
      getSize: () => ({ width: 800, height: 600 }),
      toPNG: () => Buffer.from(`png:${label}`),
    } satisfies FakeImage);
  const captureSize = image.getSize();
  return {
    label,
    webContents: {
      capturePage: vi.fn(async () => image),
      getSize: () => options.contentSize ?? [captureSize.width, captureSize.height],
    },
    getContentSize: options.contentSize ? () => options.contentSize as [number, number] : undefined,
    isDestroyed: () => options.destroyed ?? false,
    isMinimized: () => options.minimized ?? false,
  };
}

function loadCapture() {
  const context = {
    //: 归一化判断住在 browser/driver/coords(Retina 上 capturePage 给物理像素):沙箱里要把它递进去。
    captureToCss: require("./browser/driver/coords.cjs").captureToCss,
    Object,
    String,
    Error,
    Boolean,
    Number,
    Promise,
    Buffer,
    computerUseWindow: undefined as unknown as (mainWindow?: FakeWindow) => FakeWindow | null,
    captureMosaelWindow: undefined as unknown as (
      mainWindow?: FakeWindow,
    ) => Promise<{ width: number; height: number; image: string }>,
  };
  vm.runInNewContext(
    `${sourceOf("computerUseWindow")}\n${sourceOf("captureMosaelWindow")}\n` +
      "this.computerUseWindow = computerUseWindow;\n" +
      "this.captureMosaelWindow = captureMosaelWindow;",
    context,
  );
  return context;
}

describe("computer_screenshot 的 IPC 契约", () => {
  it("通道名是 computer:screenshot,载荷为空 —— 只有一个窗口,没有 window 可选", () => {
    expect(contract.IPC.invoke.computerScreenshot).toBe("computer:screenshot");
    expect(contract.parseComputerScreenshot(undefined)).toEqual({});
    expect(contract.parseComputerScreenshot({})).toEqual({});
    //: 曾经还有 window="publish"(发布器窗口),那个窗口早就不存在了 —— 现在传它就是多了一个字段。
    expect(() => contract.parseComputerScreenshot({ window: "publish" })).toThrow(/unexpected/);
    expect(() => contract.parseComputerScreenshot({ scale: 0.5 })).toThrow(/unexpected/);
  });
});

describe("只认主窗口", () => {
  it("给主窗口就返回它;没建 / 已销毁就是 null(不回退到窗口列表里随便找一个)", () => {
    const main = fakeWindow("main");
    const publish = fakeWindow("publish");
    const { computerUseWindow } = loadCapture();

    expect(computerUseWindow(main)).toBe(main);
    expect(computerUseWindow(publish)).toBe(publish); // 只看"传进来的是谁",挑谁不在这里
    expect(computerUseWindow(undefined)).toBeNull();
    expect(computerUseWindow(fakeWindow("main", { destroyed: true }))).toBeNull();
  });
});

describe("图上的像素 = 窗口的 CSS 像素(Retina 归一化)", () => {
  it("capturePage 给 2x 图时缩回窗口的 CSS 尺寸 —— 否则点击坐标会差一倍", async () => {
    const image = {
      isEmpty: () => false,
      getSize: () => ({ width: 1600, height: 1136 }),
      toPNG: () => Buffer.from("retina"),
      resize: vi.fn(({ width, height }: { width: number; height: number }) => ({
        isEmpty: () => false,
        getSize: () => ({ width, height }),
        toPNG: () => Buffer.from(`resized:${width}x${height}`),
      })),
    };
    const main = fakeWindow("main", { image, contentSize: [800, 568] });
    const { captureMosaelWindow } = loadCapture();

    const shot = await captureMosaelWindow(main);

    expect(shot.width).toBe(800);
    expect(shot.height).toBe(568);
    expect(Buffer.from(shot.image, "base64").toString()).toBe("resized:800x568");
  });
});

describe("截的是 Mosael 自己的窗口", () => {
  it("只拍传进来的那个窗口,别的窗口一下都不碰", async () => {
    const main = fakeWindow("main");
    const other = fakeWindow("other", {
      image: { isEmpty: () => false, getSize: () => ({ width: 1024, height: 768 }), toPNG: () => Buffer.from("other") },
    });
    const { captureMosaelWindow } = loadCapture();

    const shot = await captureMosaelWindow(other);

    expect(other.webContents.capturePage).toHaveBeenCalledTimes(1);
    expect(main.webContents.capturePage).not.toHaveBeenCalled();
    expect(shot).toEqual({
      width: 1024,
      height: 768,
      image: Buffer.from("other").toString("base64"),
    });
  });

  it("回来的是它的尺寸和 PNG(转 base64 由后端做)", async () => {
    const main = fakeWindow("main");
    const { captureMosaelWindow } = loadCapture();

    const shot = await captureMosaelWindow(main);

    expect(main.webContents.capturePage).toHaveBeenCalledTimes(1);
    expect(shot).toEqual({
      width: 800,
      height: 600,
      image: Buffer.from("png:main").toString("base64"),
    });
  });

  it("主窗口没开 / 已经销毁时回一条可读错误", async () => {
    const { captureMosaelWindow } = loadCapture();
    await expect(captureMosaelWindow(undefined)).rejects.toThrow(/no Mosael window/i);

    const destroyed = fakeWindow("main", { destroyed: true });
    await expect(captureMosaelWindow(destroyed)).rejects.toThrow(/no Mosael window/i);
    expect(destroyed.webContents.capturePage).not.toHaveBeenCalled();
  });

  it("窗口最小化、或 capturePage 拿到空图时,也说清楚是怎么回事", async () => {
    const { captureMosaelWindow } = loadCapture();
    const minimized = fakeWindow("main", { minimized: true });
    await expect(captureMosaelWindow(minimized)).rejects.toThrow(
      /minimi[sz]ed/i,
    );

    const blank = fakeWindow("main", {
      image: { isEmpty: () => true, getSize: () => ({ width: 0, height: 0 }), toPNG: () => Buffer.alloc(0) },
    });
    await expect(captureMosaelWindow(blank)).rejects.toThrow(/empty/i);
  });
});

describe("接线:IPC + 回环桥都走同一个拍摄函数", () => {
  it("注册了 IPC 处理器,而且它拿的是 BrowserWindow 里的窗口和主窗口引用", () => {
    //: 渲染层这条路和桥走**同一个**拍摄函数:参数只有主窗口。
    //: 此前重构漏了这一处,仍是旧签名 `captureMosaelWindow(parseComputerScreenshot(payload), …)`,
    //: 于是 `{}` 被当成窗口交给 `computerUseWindow`,永远回「没有 Mosael 窗口」。
    expect(MAIN).toMatch(/handle\(IPC\.invoke\.computerScreenshot,[\s\S]{0,240}?computerUseDriver\.observe\(\)/);
    //: 桥的截图 handler 直接把**主窗口**交给驱动 —— 没有"按名字挑窗口"这一步了。
    expect(MAIN).toMatch(/\[IPC\.invoke\.computerScreenshot\]: \(\) => computerUseDriver\.observe\(\)/);
  });

  it("后端那条桥只认写死的那几条 computer 通道,并复用同一份解析器与动作函数", () => {
    expect(MAIN).toMatch(/function startHostBridge\(/);
    //: 通道是**一张写死的表**(截图 / 点击 / 输入),不是「把 channel 转给任意处理器」。
    expect(MAIN).toMatch(/const handlers = \{/);
    expect(MAIN).toMatch(/\[IPC\.invoke\.computerScreenshot\]:/);
    expect(MAIN).toMatch(/\[IPC\.invoke\.computerClick\]:/);
    expect(MAIN).toMatch(/\[IPC\.invoke\.computerType\]:/);
    expect(MAIN).toMatch(/Object\.prototype\.hasOwnProperty\.call\(handlers, request\.channel\)/);
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
  cursor: { showAt: (x: number, y: number) => void };
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
    constant("HOST_BRIDGE_FILE"),
    constant("HOST_BRIDGE_MAX_REQUEST"),
    "let hostBridge = null;\nlet hostBridgeStarting = null;\n",
    "const computerUseDriver = new OwnWindowDriver(() => mainWindow);\n",
    sourceOf("hostBridgeFile"),
    sourceOf("computerUseWindow"),
    sourceOf("captureMosaelWindow"),
    sourceOf("hostBridgeTokenMatches"),
    sourceOf("replyHostBridge"),
    sourceOf("answerHostBridgeRequest"),
    sourceOf("desktopObserve"),
    sourceOf("desktopWindows"),
    sourceOf("withDesktopAction"),
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
async function startBridge(options: {
  windows: FakeWindow[];
  main?: FakeWindow | null;
  desktopDriver?: {
    observe: (target?: Record<string, unknown>) => Promise<unknown>;
    act?: (action: Record<string, unknown>) => Promise<unknown>;
  } | null;
}): Promise<BridgeHarness> {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-host-bridge-"));
  const logs: string[] = [];
  const cursor = { showAt: vi.fn() };
  const context = {
    Buffer,
    JSON,
    fs,
    path,
    crypto,
    OwnWindowDriver: require("./computerUse/ownWindowDriver.cjs").OwnWindowDriver,
    nodeNet: net,
    configuredDataDir: dataDir,
    appendMainLog: (scope: string, message: unknown) => {
      logs.push(`${scope}: ${String(message)}`);
    },
    IPC: contract.IPC,
    parseComputerScreenshot: contract.parseComputerScreenshot,
    parseComputerDesktopAccessibility: contract.parseComputerDesktopAccessibility,
    parseComputerDesktopClick: contract.parseComputerDesktopClick,
    parseComputerDesktopScroll: contract.parseComputerDesktopScroll,
    parseComputerDesktopScreenshot: contract.parseComputerDesktopScreenshot,
    parseComputerDesktopType: contract.parseComputerDesktopType,
    parseComputerDesktopWindows: contract.parseComputerDesktopWindows,
    desktopUseDriver: options.desktopDriver ?? null,
    withComputerUse: (action: () => unknown) => action(),
    computerUseCursor: cursor,
    //: 归一化判断住在 browser/driver/coords(Retina 上 capturePage 给物理像素):桥的沙箱里也递进去。
    captureToCss: require("./browser/driver/coords.cjs").captureToCss,
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
    cursor,
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

  it("令牌对、但通道不在那张表里 —— 直接拒，桥不是通用 RPC", async () => {
    const main = fakeWindow("main");
    const bridge = await startBridge({ windows: [main], main });
    try {
      const reply = await bridge.ask({
        token: bridge.bridge.token,
        channel: "computer:launchMissiles",
        payload: {},
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

  it("令牌对、通道对，才真的拍 —— 拍的是主窗口", async () => {
    const main = fakeWindow("main");
    const publish = fakeWindow("publish");
    const bridge = await startBridge({ windows: [main, publish], main });
    try {
      const reply = await bridge.ask({
        token: bridge.bridge.token,
        channel: "computer:screenshot",
        payload: {},
      });
      expect(reply.ok).toBe(true);
      expect(reply.result).toMatchObject({ width: 800, height: 600 });
      expect(main.webContents.capturePage).toHaveBeenCalledTimes(1);
      expect(publish.webContents.capturePage).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });

  it("桌面窗口、截图和 AX 三条只读通道都经过令牌与参数契约", async () => {
    const main = fakeWindow("main");
    const desktopDriver = {
      observe: vi.fn(async (target?: Record<string, unknown>) => {
        if (target?.windowNumber) return { image: "png", width: 800, height: 600, elements: [] };
        if (target?.pid) return { elements: [{ id: "snap:0" }], meta: { snapshot_id: "snap" } };
        return [{ id: 7, pid: 42, owner: "Finder", title: "Documents" }];
      }),
    };
    const bridge = await startBridge({ windows: [main], main, desktopDriver });
    try {
      const token = bridge.bridge.token;
      const windows = await bridge.ask({ token, channel: "computer:desktop-windows", payload: {} });
      expect(windows).toMatchObject({ ok: true, result: { windows: [{ id: 7, pid: 42 }] } });
      const shot = await bridge.ask({ token, channel: "computer:desktop-screenshot", payload: { windowNumber: 7 } });
      expect(shot).toMatchObject({ ok: true, result: { image: "png", width: 800 } });
      const ax = await bridge.ask({ token, channel: "computer:desktop-accessibility", payload: { pid: 42 } });
      expect(ax).toMatchObject({ ok: true, result: { meta: { snapshot_id: "snap" } } });
      expect(desktopDriver.observe.mock.calls).toEqual([[{}], [{ windowNumber: 7 }], [{ pid: 42 }]]);
      expect(main.webContents.capturePage).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });

  it("桌面通道拒绝无效窗口 id,不会落到驱动", async () => {
    const main = fakeWindow("main");
    const desktopDriver = { observe: vi.fn() };
    const bridge = await startBridge({ windows: [main], main, desktopDriver });
    try {
      const reply = await bridge.ask({
        token: bridge.bridge.token,
        channel: "computer:desktop-screenshot",
        payload: { windowNumber: 0 },
      });
      expect(reply).toMatchObject({ ok: false, status: 400 });
      expect(desktopDriver.observe).not.toHaveBeenCalled();
    } finally {
      bridge.close();
    }
  });
  it("桌面动作经写死通道、参数契约和指针提示", async () => {
    const main = fakeWindow("main");
    const desktopDriver = {
      observe: vi.fn(),
      act: vi.fn(async (action: Record<string, unknown>) => ({ ...action, point: { x: 60, y: 40 } })),
    };
    const bridge = await startBridge({ windows: [main], main, desktopDriver });
    try {
      const reply = await bridge.ask({
        token: bridge.bridge.token,
        channel: "computer:desktop-click",
        payload: { token: "snap-1:0", button: "right", clickCount: 2 },
      });
      expect(reply).toMatchObject({ ok: true, result: { point: { x: 60, y: 40 } } });
      expect(desktopDriver.act).toHaveBeenCalledWith({ kind: "click", replay: true, token: "snap-1:0", button: "right", clickCount: 2 });
      expect(bridge.cursor.showAt).toHaveBeenCalledWith(60, 40);
    } finally {
      bridge.close();
    }
  });


});
