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
    resume: boolean;
  };
  parseBrowserProfile: (value: unknown) => { partition: string };
  parsePanelLayout: (value: unknown) => Record<string, number | string>;
  parsePanelMuted: (value: unknown) => { id: string; muted: boolean };
  parseAuthToken: (value: unknown, channel: string) => { token: string };
  parseRestoreStage: (value: unknown) => { stageId: string };
  parseLocale: (value: unknown) => { locale: string };
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
      resume: false,
    });
    expect(() => contract.parseBrowserLogin({ partition: "persist:publish-user", url: "https://example.com" }))
      .toThrow(/partition/);
    expect(() => contract.parseBrowserLogin({ partition: "persist:pool-user", url: "file:\/\/\/tmp/x" }))
      .toThrow(/http/);

    // 清登录数据是破坏性的:只许碰通用档案的分区,发布账号走 publish:signOut。
    expect(contract.parseBrowserProfile({ partition: "persist:pool-user" })).toEqual({ partition: "persist:pool-user" });
    expect(() => contract.parseBrowserProfile({ partition: "persist:mosael-account" })).toThrow(/partition/);

    // 挪位置:只有 x/y。
    expect(contract.parsePanelLayout({ x: 10, y: 20 })).toEqual({ x: 10, y: 20 });
    // 认不出的字段一律拒收,不能「半懂地执行」:开发时渲染层热更新、主进程不重启,两边常常不是同一版。
    // 旧版解析器悄悄丢掉了新字段 handle,把缩放当成「挪到这里 + 改宽」,拖角时整张卡片跟着平移。
    expect(() => contract.parsePanelLayout({ x: 10, y: 20, width: 300 })).toThrow(/width/);
    expect(() => contract.parsePanelLayout({ handle: "se", x: 1, y: 2, width: 3, height: 4, anchor: "nw" }))
      .toThrow(/anchor/);
    expect(() => contract.parsePanelLayout({ x: 10 })).toThrow(/y/);
    // 缩放:手柄 + 指针要的整块矩形,缺一不可。
    expect(contract.parsePanelLayout({ handle: "nw", x: 1, y: 2, width: 300, height: 200 }))
      .toEqual({ handle: "nw", x: 1, y: 2, width: 300, height: 200 });
    expect(() => contract.parsePanelLayout({ handle: "se", x: 1, y: 2, width: Number.NaN, height: 200 }))
      .toThrow(/width/);
    expect(() => contract.parsePanelLayout({ handle: "se", x: 1, y: 2, width: 300 })).toThrow(/height/);
    expect(() => contract.parsePanelLayout({ handle: "middle", x: 1, y: 2, width: 300, height: 200 }))
      .toThrow(/handle/);
    expect(contract.parsePanelMuted({ id: " browser-1 ", muted: false })).toEqual({ id: "browser-1", muted: false });
    expect(() => contract.parsePanelMuted({ id: "browser-1", muted: "false" })).toThrow(/muted/);
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

  it("accepts only a language tag as the interface locale", () => {
    expect(contract.parseLocale({ locale: " en-US " })).toEqual({ locale: "en-US" });
    expect(contract.parseLocale({ locale: "zh-Hant-TW" })).toEqual({ locale: "zh-Hant-TW" });
    expect(() => contract.parseLocale({ locale: "" })).toThrow(/locale/);
    expect(() => contract.parseLocale({ locale: "en US; rm -rf" })).toThrow(/locale/);
    expect(() => contract.parseLocale("en")).toThrow(/mosael:locale/);
  });
});
