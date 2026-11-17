import { describe, expect, it, vi } from "vitest";

import { OwnWindowDriver } from "./ownWindowDriver.cjs";

type FakeImage = { isEmpty: () => boolean; getSize: () => { width: number; height: number }; toPNG: () => Buffer };
type FakeWindow = {
  webContents: {
    capturePage: ReturnType<typeof vi.fn>;
    sendInputEvent: ReturnType<typeof vi.fn>;
    insertText: ReturnType<typeof vi.fn>;
    focus: ReturnType<typeof vi.fn>;
    getSize: () => [number, number];
    executeJavaScript?: ReturnType<typeof vi.fn>;
  };
  focus: ReturnType<typeof vi.fn>;
  isDestroyed: () => boolean;
  isMinimized: () => boolean;
};

function fakeWindow(): FakeWindow {
  const image: FakeImage = {
    isEmpty: () => false,
    getSize: () => ({ width: 800, height: 600 }),
    toPNG: () => Buffer.from("png"),
  };
  return {
    webContents: {
      capturePage: vi.fn(async () => image),
      sendInputEvent: vi.fn(),
      insertText: vi.fn(),
      focus: vi.fn(),
      getSize: () => [800, 600],
    },
    focus: vi.fn(),
    isDestroyed: () => false,
    isMinimized: () => false,
  };
}

describe("OwnWindowDriver(ADR 0081 P0)", () => {
  it("capabilities 只声明 L1 有的东西:有截图与输入,没有可访问性树", () => {
    const driver = new OwnWindowDriver(() => fakeWindow());
    expect(driver.capabilities()).toEqual({
      tree: false,
      screenshots: true,
      input: true,
      platforms: ["mosael-window"],
    });
  });

  it("observe 返回主窗口的图,并明确 elements 为空", async () => {
    const driver = new OwnWindowDriver(() => fakeWindow());
    const shot = await driver.observe();
    expect(shot.elements).toEqual([]);
    expect(shot.meta).toEqual({ window: "main" });
    expect(shot.width).toBe(800);
    expect(shot.height).toBe(600);
    expect(shot.image).toBe(Buffer.from("png").toString("base64"));
  });

  it("observe 同时给出可操作元素的 CSS 坐标清单", async () => {
    const win = fakeWindow();
    win.webContents.executeJavaScript = vi.fn(async () => [
      { role: "button", name: "保存", x: 10, y: 20, width: 80, height: 30, disabled: false },
      { role: "input", name: "搜索", x: 100, y: 20, width: 200, height: 30, disabled: false },
    ]);
    const driver = new OwnWindowDriver(() => win);

    const shot = await driver.observe();

    expect(shot.elements).toHaveLength(2);
    expect(shot.elements[0]).toMatchObject({ role: "button", name: "保存", x: 10, y: 20 });
    expect(win.webContents.executeJavaScript).toHaveBeenCalledOnce();
  });

  it("act 把三种动作交给原来的实现:click / type / scroll", async () => {
    const win = fakeWindow();
    const driver = new OwnWindowDriver(() => win);
    const click = await driver.act({ kind: "click", x: 10, y: 20, button: "left", clickCount: 1 });
    expect(click).toEqual({ x: 10, y: 20, button: "left", clickCount: 1 });
    const typed = await driver.act({ kind: "type", text: "hi" });
    expect(typed).toEqual({ typed: 2 });
    const scrolled = await driver.act({ kind: "scroll", dy: 2, x: null, y: null });
    expect(scrolled.dy).toBe(2);
    const pressed = await driver.act({ kind: "key", key: "Enter", modifiers: ["cmd"] });
    expect(pressed).toEqual({ key: "Enter", modifiers: ["cmd"], keyCode: "Enter" });
    expect(win.webContents.sendInputEvent).toHaveBeenLastCalledWith({ type: "keyUp", keyCode: "Enter", modifiers: ["command"] });
    expect(win.webContents.sendInputEvent).toHaveBeenCalled();
    expect(win.webContents.insertText).toHaveBeenCalledWith("hi");

    const dragged = await driver.act({
      kind: "drag", fromX: 10, fromY: 20, toX: 100, toY: 200, button: "left", durationMs: 200,
    });
    expect(dragged).toEqual({ fromX: 10, fromY: 20, toX: 100, toY: 200, button: "left", durationMs: 200 });
    expect(win.webContents.sendInputEvent).toHaveBeenLastCalledWith({
      type: "mouseUp", x: 100, y: 200, button: "left", clickCount: 1,
    });
  });

  it("verify 明确不支持,不冒充已验证", () => {
    const driver = new OwnWindowDriver(() => fakeWindow());
    expect(driver.verify()).toEqual({ ok: false, reason: "verify_not_supported", evidence: null });
  });

  it("未知动作直接拒", async () => {
    const driver = new OwnWindowDriver(() => fakeWindow());
    await expect(driver.act({ kind: "evaluate" })).rejects.toThrow(/Unknown computer-use action/);
  });
});
