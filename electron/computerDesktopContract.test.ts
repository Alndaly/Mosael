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
});
