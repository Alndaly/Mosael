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
  parseCaptureMode: (value: unknown) => { mode: string };
  parseRegionSelection: (value: unknown) => { selection: Record<string, number> | null };
  parseImageUrls: (value: unknown) => { urls: string[] };
  parseReadMode: (value: unknown) => { mode: string };
  parseToolsInset: (value: unknown) => { right: number };
  parseSaveDownload: (value: unknown) => Record<string, string | null>;
  parsePageId: (value: unknown, channel: string) => { id: string };
  parsePageOrder: (value: unknown) => { ids: string[] };
  parseNewPage: (value: unknown) => { url: string };
  parsePagesInset: (value: unknown) => { left: number };
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

  it("validates page-tool payloads before handlers see them: closed option lists, bounded values, no unexpected fields", () => {
    expect(contract.parseCaptureMode({ mode: "full" })).toEqual({ mode: "full" });
    expect(() => contract.parseCaptureMode({ mode: "region" })).toThrow(/mode/);
    expect(() => contract.parseCaptureMode({ mode: "visible", target: "pool-other" })).toThrow(/unexpected field target/);

    expect(contract.parseRegionSelection({ selection: null })).toEqual({ selection: null });
    expect(contract.parseRegionSelection({ selection: { x: 0.1, y: 0.2, width: 0.5, height: 0.3 } })).toEqual({
      selection: { x: 0.1, y: 0.2, width: 0.5, height: 0.3 },
    });
    expect(() => contract.parseRegionSelection({ selection: { x: 0.8, y: 0, width: 0.5, height: 0.5 } })).toThrow(/inside the frame/);
    expect(() => contract.parseRegionSelection({ selection: { x: -1, y: 0, width: 0.5, height: 0.5 } })).toThrow(/selection.x/);
    expect(() => contract.parseRegionSelection({ selection: { x: 0, y: 0, width: 400, height: 300 } })).toThrow(/selection.width/);

    expect(contract.parseImageUrls({ urls: ["https://example.com/a.png"] })).toEqual({ urls: ["https://example.com/a.png"] });
    expect(() => contract.parseImageUrls({ urls: [] })).toThrow(/urls/);
    expect(() => contract.parseImageUrls({ urls: ["file:///etc/passwd"] })).toThrow(/http/);
    expect(() => contract.parseImageUrls({ urls: Array.from({ length: 121 }, (_, i) => `https://e.com/${i}.png`) })).toThrow(/urls/);

    expect(contract.parseReadMode({ mode: "selection" })).toEqual({ mode: "selection" });
    expect(() => contract.parseReadMode({ mode: "html" })).toThrow(/mode/);

    expect(contract.parseToolsInset({ right: 360 })).toEqual({ right: 360 });
    expect(() => contract.parseToolsInset({ right: -1 })).toThrow(/right/);
    expect(() => contract.parseToolsInset({ right: Number.NaN })).toThrow(/right/);
  });

  it("decodes the page list's requests: page ids are the main process's numbers, the order is a list of them", () => {
    expect(contract.parsePageId({ id: "42" }, "publish:switchPage")).toEqual({ id: "42" });
    expect(() => contract.parsePageId({ id: "../x" }, "publish:switchPage")).toThrow(/page id/);
    expect(() => contract.parsePageId({ id: "1", accountId: "x" }, "publish:switchPage")).toThrow(/unexpected field accountId/);
    expect(contract.parsePageOrder({ ids: ["3", "1", "2"] })).toEqual({ ids: ["3", "1", "2"] });
    expect(() => contract.parsePageOrder({ ids: [] })).toThrow(/ids/);
    expect(() => contract.parsePageOrder({ ids: [1, 2] })).toThrow(/page id/);
    expect(contract.parseNewPage({ url: "bilibili.com" })).toEqual({ url: "bilibili.com" });
    expect(() => contract.parseNewPage({ url: "" })).toThrow(/url/);
    expect(contract.parsePagesInset({ left: 220 })).toEqual({ left: 220 });
    expect(() => contract.parsePagesInset({ left: -1 })).toThrow(/left/);
  });

  it("decodes saving a finished download: an http(s) server, a token, a workspace, nothing else", () => {
    const request = {
      id: "0f8fad5b-d9cb-469f-a165-70867728950e",
      server: "http://127.0.0.1:8800",
      token: "tok",
      workspaceId: "ws1",
      projectId: null,
    };
    expect(contract.parseSaveDownload(request)).toEqual(request);
    expect(contract.parseSaveDownload({ ...request, projectId: "p1" }).projectId).toBe("p1");
    expect(() => contract.parseSaveDownload({ ...request, id: "../etc" })).toThrow(/id/);
    expect(() => contract.parseSaveDownload({ ...request, server: "file:///tmp" })).toThrow(/server/);
    expect(() => contract.parseSaveDownload({ ...request, token: "" })).toThrow(/token/);
    expect(() => contract.parseSaveDownload({ ...request, token: "x".repeat(20_000) })).toThrow(/token/);
    expect(() => contract.parseSaveDownload({ ...request, path: "/etc/passwd" })).toThrow(/unexpected field path/);
  });
});
