/**
 * 协议唤起的接线:macOS 的 `open-url`、Windows/Linux 的第二个实例 argv,都必须走**同一个**落点
 * (system/protocol 的 handleDeepLink),把解析出来的东西交给**已经在跑**的那个窗口 —— 不另开窗口。
 *
 * 真正解析的形状由 deepLink.test.ts 管;这里钉的是「怎么送到渲染层」,尤其是新加的社区分享导入
 * (mosael://import?share=…):它也得走同一条路,而不是在 main.cjs 里另起一套。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const handlers = new Map<string, (...args: unknown[]) => void>();

vi.mock("electron", () => ({
  app: {
    on: vi.fn((name: string, handler: (...args: unknown[]) => void) => {
      handlers.set(name, handler);
    }),
    off: vi.fn(),
    setAsDefaultProtocolClient: vi.fn(),
  },
}));

import { IPC } from "../ipc-contract.cjs";
import { adoptSecondInstance, protocol } from "./protocol";
import type { SystemContext } from "./types";

function fakeWindow() {
  return {
    isDestroyed: () => false,
    webContents: {
      isLoading: () => false,
      send: vi.fn(),
      once: vi.fn(),
    },
  };
}

function fakeContext(win: ReturnType<typeof fakeWindow>) {
  return {
    getWindow: () => win,
    showWindow: vi.fn(),
    isDev: true,
  } as unknown as SystemContext;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("mosael:// 协议唤起的落点", () => {
  it("macOS 的 open-url:import 深链交给已在跑的窗口,不另开窗口", () => {
    const win = fakeWindow();
    const ctx = fakeContext(win);
    handlers.clear();
    protocol.register(ctx);
    const openUrl = handlers.get("open-url");
    if (!openUrl) throw new Error("open-url 没接上");

    const event = { preventDefault: vi.fn() };
    openUrl(event, "mosael://import?share=abc");

    expect(event.preventDefault).toHaveBeenCalled();
    // 交给**这个**窗口:没有 BrowserWindow 的构造、也没有别的新窗口。
    expect(ctx.showWindow).toHaveBeenCalledTimes(1);
    expect(win.webContents.send).toHaveBeenCalledWith(IPC.event.deepLink, {
      view: "workflows",
      template: "share:abc",
    });
  });

  it("第二个实例(Windows/Linux)把 import 深链交给当前实例,不自己处理、不建窗口", () => {
    const win = fakeWindow();
    const ctx = fakeContext(win);
    handlers.clear();
    protocol.register(ctx);

    adoptSecondInstance(["C:\\Mosael\\Mosael.exe", "mosael://import?share=Ab_c-123"]);

    expect(win.webContents.send).toHaveBeenCalledWith(IPC.event.deepLink, {
      view: "workflows",
      template: "share:Ab_c-123",
    });
    // 第二次启动只把参数交过来并唤到前台;窗口还是同一个。
    expect(ctx.showWindow).toHaveBeenCalled();
    expect(ctx.getWindow()).toBe(win);
  });

  it("open 的既有行为不变:open-url 与第二个实例都照旧只导航", () => {
    const win = fakeWindow();
    const ctx = fakeContext(win);
    handlers.clear();
    protocol.register(ctx);
    handlers.get("open-url")!({ preventDefault: vi.fn() }, "mosael://open?view=statistics");
    expect(win.webContents.send).toHaveBeenCalledWith(IPC.event.deepLink, { view: "statistics" });

    adoptSecondInstance(["Mosael.exe", "mosael://open?view=plugins&market=dev.mosael.remotion"]);
    expect(win.webContents.send).toHaveBeenLastCalledWith(IPC.event.deepLink, {
      view: "plugins",
      market: "dev.mosael.remotion",
    });
  });
});
