/**
 * Computer Use P1(ADR 0075)的 Electron 一侧:**只对 Mosael 自己的窗口**点击与输入。
 *
 * 不碰真鼠标、不碰系统级输入:用替身窗口,钉四件事 ——
 *   · 坐标原样交给 `webContents.sendInputEvent`(可信输入,只在这个窗口里生效);
 *   · 只有点在窗口范围内才发;越界回来的是**一句带窗口尺寸的人话**;
 *   · 输入走 `webContents.insertText`(和用户打字同一条路),先聚焦;
 *   · 没有窗口 / 窗口最小化时,什么都不点、什么都不输。
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

const MAIN = fs.readFileSync(path.resolve(__dirname, "main.cjs"), "utf8");

// CommonJS is intentional: main.cjs loads this exact runtime contract.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const contract = require("./ipc-contract.cjs") as {
  IPC: { invoke: Record<string, string> };
  parseComputerClick: (value: unknown) => { window: string; x: number; y: number; button: string; clickCount: number };
  parseComputerType: (value: unknown) => { window: string; text: string };
  parseComputerScroll: (value: unknown) => { window: string; dy: number; x: number | null; y: number | null };
};

function sourceOf(name: string): string {
  const found = MAIN.match(new RegExp(`\\n(?:async )?function ${name}\\([\\s\\S]*?\\n\\}\\n`))?.[0];
  if (!found) throw new Error(`${name} 没在 main.cjs 里找到`);
  return found;
}

function windowNamesSource(): string {
  const found = MAIN.match(/\nconst COMPUTER_WINDOW_NAMES = [^\n]+\n/)?.[0];
  if (!found) throw new Error("COMPUTER_WINDOW_NAMES 没在 main.cjs 里找到");
  return found;
}

type FakeWindow = {
  webContents: {
    sendInputEvent: ReturnType<typeof vi.fn>;
    insertText: ReturnType<typeof vi.fn>;
    focus: ReturnType<typeof vi.fn>;
    getSize: () => [number, number];
  };
  focus: ReturnType<typeof vi.fn>;
  isDestroyed: () => boolean;
  isMinimized: () => boolean;
};

function fakeWindow(options: { destroyed?: boolean; minimized?: boolean; size?: [number, number] } = {}): FakeWindow {
  return {
    webContents: {
      sendInputEvent: vi.fn(),
      insertText: vi.fn(),
      focus: vi.fn(),
      getSize: () => options.size ?? [1440, 900],
    },
    focus: vi.fn(),
    isDestroyed: () => options.destroyed ?? false,
    isMinimized: () => options.minimized ?? false,
  };
}

function loadActions() {
  const context = {
    Object,
    String,
    Error,
    Math,
    chooseComputerWindow: undefined as unknown as (
      name: string,
      windows: FakeWindow[],
      roles: Record<string, FakeWindow | undefined>,
    ) => FakeWindow | null,
  };
  vm.runInNewContext(
    `${windowNamesSource()}\n${sourceOf("chooseComputerWindow")}\n${sourceOf("clickMosaelWindow")}\n${sourceOf("scrollMosaelWindow")}\n${sourceOf("typeIntoMosaelWindow")}\n` +
      "this.chooseComputerWindow = chooseComputerWindow;\n" +
      "this.clickMosaelWindow = clickMosaelWindow;\n" +
      "this.typeIntoMosaelWindow = typeIntoMosaelWindow;\n" +
      "this.scrollMosaelWindow = scrollMosaelWindow;",
    context,
  );
  return context as unknown as {
    clickMosaelWindow: (request: Record<string, unknown>, windows: FakeWindow[], roles: Record<string, FakeWindow | undefined>) => Record<string, unknown>;
    typeIntoMosaelWindow: (request: Record<string, unknown>, windows: FakeWindow[], roles: Record<string, FakeWindow | undefined>) => Record<string, unknown>;
    scrollMosaelWindow: (request: Record<string, unknown>, windows: FakeWindow[], roles: Record<string, FakeWindow | undefined>) => Record<string, unknown>;
  };
}

describe("computer_click / computer_type 的 IPC 契约", () => {
  it("两条通道与参数形状:点只认坐标 + 左右键 + 单击/双击;输入只认文本", () => {
    expect(contract.IPC.invoke.computerClick).toBe("computer:click");
    expect(contract.IPC.invoke.computerType).toBe("computer:type");

    expect(contract.parseComputerClick({ x: 10, y: 20 })).toEqual({
      window: "main", x: 10, y: 20, button: "left", clickCount: 1,
    });
    expect(contract.parseComputerClick({ window: " PUBLISH ", x: 1, y: 2, button: "right", clickCount: 2 })).toEqual({
      window: "publish", x: 1, y: 2, button: "right", clickCount: 2,
    });
    expect(() => contract.parseComputerClick({ x: -1, y: 0 })).toThrow(/x must be/);
    expect(() => contract.parseComputerClick({ x: 1, y: 0, button: "middle" })).toThrow(/button/);
    expect(() => contract.parseComputerClick({ x: 1, y: 0, clickCount: 3 })).toThrow(/clickCount/);
    expect(() => contract.parseComputerClick({ x: 1, y: 0, window: "desktop" })).toThrow(/main.*publish/);

    expect(contract.parseComputerType({ text: "hi" })).toEqual({ window: "main", text: "hi" });
    expect(() => contract.parseComputerType({ text: "" })).toThrow(/non-empty/);
    expect(() => contract.parseComputerType({ text: "x".repeat(2001) })).toThrow(/2000/);

    expect(contract.IPC.invoke.computerScroll).toBe("computer:scroll");
    expect(contract.parseComputerScroll({ dy: 3 })).toEqual({ window: "main", dy: 3, x: null, y: null });
    expect(contract.parseComputerScroll({ window: "publish", dy: -2, x: 10, y: 20 })).toEqual({
      window: "publish", dy: -2, x: 10, y: 20,
    });
    expect(() => contract.parseComputerScroll({ dy: 0 })).toThrow(/non-zero/);
    expect(() => contract.parseComputerScroll({ dy: 31 })).toThrow(/30/);
    expect(() => contract.parseComputerScroll({ dy: 1, x: -1 })).toThrow(/non-negative/);
  });
});

describe("点的是 Mosael 自己的窗口", () => {
  it("坐标原样交给 sendInputEvent:移动 → 按下 → 抬起,按钮与连点跟着走", () => {
    const main = fakeWindow();
    const { clickMosaelWindow } = loadActions();

    const result = clickMosaelWindow(
      { window: "main", x: 120, y: 80, button: "right", clickCount: 2 },
      [main],
      { main },
    );

    const sent = main.webContents.sendInputEvent.mock.calls.map(([event]) => event);
    expect(sent).toEqual([
      { type: "mouseMove", x: 120, y: 80 },
      { type: "mouseDown", x: 120, y: 80, button: "right", clickCount: 2 },
      { type: "mouseUp", x: 120, y: 80, button: "right", clickCount: 2 },
    ]);
    expect(result).toEqual({ window: "main", x: 120, y: 80, button: "right", clickCount: 2 });
    //: 点之前先聚焦窗口与页面 —— sendInputEvent 作用的对象是窗口里那个页面。
    expect(main.focus).toHaveBeenCalledTimes(1);
    expect(main.webContents.focus).toHaveBeenCalledTimes(1);
  });

  it("点在窗口外面:一下都不发,回来的是一句带尺寸的人话", () => {
    const main = fakeWindow({ size: [1440, 900] });
    const { clickMosaelWindow } = loadActions();

    expect(() => clickMosaelWindow({ window: "main", x: 1440, y: 10 }, [main], { main })).toThrow(
      /outside the main window.*1440×900/,
    );
    expect(main.webContents.sendInputEvent).not.toHaveBeenCalled();
  });

  it("窗口最小化 / 不在:什么都不点", () => {
    const minimized = fakeWindow({ minimized: true });
    const { clickMosaelWindow } = loadActions();
    expect(() => clickMosaelWindow({ window: "main", x: 1, y: 1 }, [minimized], { main: minimized })).toThrow(
      /minimized/,
    );
    expect(minimized.webContents.sendInputEvent).not.toHaveBeenCalled();

    expect(() => clickMosaelWindow({ window: "publish", x: 1, y: 1 }, [], {})).toThrow(/no publish window/);
  });
});

describe("输入到 Mosael 自己的窗口", () => {
  it("先聚焦,再用 insertText 交给页面(和用户打字同一条路)", () => {
    const main = fakeWindow();
    const { typeIntoMosaelWindow } = loadActions();

    const result = typeIntoMosaelWindow({ window: "main", text: "你好" }, [main], { main });

    expect(main.focus).toHaveBeenCalledTimes(1);
    expect(main.webContents.focus).toHaveBeenCalledTimes(1);
    expect(main.webContents.insertText).toHaveBeenCalledWith("你好");
    expect(result).toEqual({ window: "main", typed: 2 });
  });

  it("滚动:滚轮事件落在窗口正中(不给位置时),dy 会换算成 Chromium 的 deltaY", () => {
    const main = fakeWindow({ size: [1000, 800] });
    const { scrollMosaelWindow } = loadActions();

    const result = scrollMosaelWindow({ window: "main", dy: 3, x: null, y: null }, [main], { main });

    //: 一格 ≈ 100 像素(3 行):只发 deltaY = -dy 的话「滚 3 格」只走 3 像素,看起来就是没动。
    expect(main.webContents.sendInputEvent).toHaveBeenCalledWith({
      type: "mouseWheel", x: 500, y: 400, deltaY: -300, canScroll: true,
    });
    expect(result).toEqual({ window: "main", dy: 3, x: 500, y: 400 });

    // 指到坐标上就照给的来;往上的 dy 是正的 deltaY。
    scrollMosaelWindow({ window: "main", dy: -2, x: 10, y: 20 }, [main], { main });
    expect(main.webContents.sendInputEvent).toHaveBeenLastCalledWith({
      type: "mouseWheel", x: 10, y: 20, deltaY: 200, canScroll: true,
    });
  });

  it("滚动越界 / 最小化:一下都不发", () => {
    const main = fakeWindow({ size: [1000, 800] });
    const { scrollMosaelWindow } = loadActions();
    expect(() => scrollMosaelWindow({ window: "main", dy: 1, x: 1000, y: 10 }, [main], { main })).toThrow(
      /outside the main window/,
    );
    expect(main.webContents.sendInputEvent).not.toHaveBeenCalled();

    const minimized = fakeWindow({ minimized: true });
    expect(() => scrollMosaelWindow({ window: "main", dy: 1, x: null, y: null }, [minimized], { main: minimized })).toThrow(
      /minimized/,
    );
    expect(minimized.webContents.sendInputEvent).not.toHaveBeenCalled();
  });

  it("窗口最小化 / 不在:什么都不输", () => {
    const minimized = fakeWindow({ minimized: true });
    const { typeIntoMosaelWindow } = loadActions();
    expect(() => typeIntoMosaelWindow({ window: "main", text: "x" }, [minimized], { main: minimized })).toThrow(
      /minimized/,
    );
    expect(minimized.webContents.insertText).not.toHaveBeenCalled();
    expect(() => typeIntoMosaelWindow({ window: "publish", text: "x" }, [], {})).toThrow(/no publish window/);
  });
});
