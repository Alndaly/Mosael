import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// CommonJS is intentional: main.cjs and preload.cjs load this exact runtime contract.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const contract = require("./ipc-contract.cjs") as {
  IPC: {
    invoke: Record<string, string>;
    send: Record<string, string>;
    event: Record<string, string>;
  };
  parsePublishTarget: (value: unknown, channel: string) => { accountId: string; platform: string };
  parseBrowserLogin: (value: unknown) => {
    partition: string;
    url: string;
    name: string;
    proxy: string | null;
  };
  parsePanelLayout: (value: unknown) => Record<string, number>;
  parseAuthToken: (value: unknown, channel: string) => { token: string };
  parseRestoreStage: (value: unknown) => { stageId: string };
};

const ROOT = path.resolve(__dirname);

describe("Electron IPC contract", () => {
  it("assigns every channel one name and one direction", () => {
    const channels = Object.values(contract.IPC).flatMap((group) => Object.values(group));

    expect(new Set(channels).size).toBe(channels.length);
    expect(channels).toContain("recording-permissions:request");
    expect(channels).toContain("publish:panels");
    expect(channels).toContain("data:exportDiagnostics");
    expect(channels).toContain("data:createBackup");
    expect(channels).toContain("data:applyRestore");
    expect(channels).not.toContain("publish:exit");
  });

  it("keeps raw IPC names out of process-boundary product code", () => {
    const files = [
      "main.cjs",
      "preload.cjs",
      "system/customCss.ts",
      "system/notify.ts",
      "system/protocol.ts",
    ];
    const rawCall = /(?:ipcMain\.(?:handle|on)|ipcRenderer\.(?:invoke|send|on)|webContents\.send)\(\s*["']/;

    for (const file of files) {
      expect(fs.readFileSync(path.join(ROOT, file), "utf8"), file).not.toMatch(rawCall);
    }
  });

  it("rejects malformed publish identity payloads before handlers see them", () => {
    expect(contract.parsePublishTarget({ accountId: " account ", platform: " youtube " }, "publish:login"))
      .toEqual({ accountId: "account", platform: "youtube" });
    expect(() => contract.parsePublishTarget({ accountId: "", platform: "youtube" }, "publish:login"))
      .toThrow(/accountId/);
    expect(() => contract.parsePublishTarget(null, "publish:login")).toThrow(/publish:login/);
  });

  it("validates browser-login and panel-layout payloads", () => {
    expect(contract.parseBrowserLogin({
      partition: "persist:pool-user",
      url: "https://example.com/login",
      name: " Example ",
    })).toEqual({
      partition: "persist:pool-user",
      url: "https://example.com/login",
      name: "Example",
      proxy: null,
    });
    expect(() => contract.parseBrowserLogin({ partition: "persist:publish-user", url: "https://example.com" }))
      .toThrow(/partition/);
    expect(() => contract.parseBrowserLogin({ partition: "persist:pool-user", url: "file:\/\/\/tmp/x" }))
      .toThrow(/http/);

    expect(contract.parsePanelLayout({ x: 10, y: 20, width: undefined, ignored: 3 })).toEqual({ x: 10, y: 20 });
    expect(() => contract.parsePanelLayout({ width: Number.NaN })).toThrow(/width/);
  });

  it("accepts only a bounded authentication token for privileged data IPC", () => {
    expect(contract.parseAuthToken({ token: " bearer-token " }, "data:createBackup"))
      .toEqual({ token: "bearer-token" });
    expect(() => contract.parseAuthToken({ token: "" }, "data:createBackup")).toThrow(/token/);
    expect(() => contract.parseAuthToken({ token: "x".repeat(16_385) }, "data:createBackup"))
      .toThrow(/token/);
  });

  it("accepts only opaque restore stage identifiers", () => {
    expect(contract.parseRestoreStage({ stageId: "a".repeat(32) })).toEqual({ stageId: "a".repeat(32) });
    expect(() => contract.parseRestoreStage({ stageId: "../live" })).toThrow(/stageId/);
  });
});
