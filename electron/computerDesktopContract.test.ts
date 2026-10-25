import { describe, expect, it } from "vitest";

// CommonJS is intentional: main.cjs loads this exact runtime contract.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const contract = require("./ipc-contract.cjs");

describe("desktop observation IPC contract(ADR 0081)", () => {
  it("窗口列表不收任何字段", () => {
    expect(contract.parseComputerDesktopWindows(undefined)).toEqual({});
    expect(contract.parseComputerDesktopWindows({})).toEqual({});
    expect(() => contract.parseComputerDesktopWindows({ path: "/tmp" })).toThrow("unexpected field path");
  });

  it("截图只收正整数 windowNumber", () => {
    expect(contract.parseComputerDesktopScreenshot({ windowNumber: 7 })).toEqual({ windowNumber: 7 });
    for (const value of [0, -1, 1.5, "7", true, null]) {
      expect(() => contract.parseComputerDesktopScreenshot({ windowNumber: value })).toThrow("positive integer");
    }
    expect(() => contract.parseComputerDesktopScreenshot({ windowNumber: 7, script: "steal()" })).toThrow("unexpected field script");
  });

  it("AX 只收正整数 pid", () => {
    expect(contract.parseComputerDesktopAccessibility({ pid: 42 })).toEqual({ pid: 42 });
    for (const value of [0, -1, 1.5, "42", false, null]) {
      expect(() => contract.parseComputerDesktopAccessibility({ pid: value })).toThrow("positive integer");
    }
  });

  it("动作只收一种目标:令牌,或截图编号加坐标", () => {
    const capture = "11111111-1111-1111-1111-111111111111";
    expect(contract.parseComputerDesktopClick({ token: "snap-1:0" })).toEqual({
      token: "snap-1:0",
      button: "left",
      clickCount: 1,
    });
    expect(contract.parseComputerDesktopClick({ captureId: capture, x: 10, y: 20 })).toMatchObject({
      captureId: capture,
      x: 10,
      y: 20,
    });
    expect(() => contract.parseComputerDesktopClick({})).toThrow("exactly one");
    expect(() => contract.parseComputerDesktopClick({ token: "snap-1:0", captureId: capture, x: 1, y: 2 }))
      .toThrow("exactly one");
    expect(() => contract.parseComputerDesktopClick({ captureId: capture })).toThrow("non-negative integer");
    expect(() => contract.parseComputerDesktopClick({ token: "snap-1:0", script: "steal()" })).toThrow("unexpected field script");
  });

  it("输入与滚动只接受各自的动作参数", () => {
    expect(contract.parseComputerDesktopType({ token: "snap-1:0", text: "hello" })).toEqual({
      token: "snap-1:0",
      text: "hello",
    });
    expect(() => contract.parseComputerDesktopType({ token: "snap-1:0", text: "" })).toThrow("non-empty");
    expect(contract.parseComputerDesktopScroll({ token: "snap-1:0", dy: -3 })).toEqual({
      token: "snap-1:0",
      dy: -3,
    });
    expect(() => contract.parseComputerDesktopScroll({ token: "snap-1:0", dy: 0 })).toThrow("non-zero");
  });
});
