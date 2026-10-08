/** @vitest-environment jsdom */
/**
 * 「有新版本」的消息:主进程启动 5 秒后、之后每天查一次就推过来,而界面要到登录进去(AppShell 挂上)才订阅。preload 记住最新
 * 的一条、订阅时补发 —— 此前启动时还停在登录页的那一次就丢了。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";

import { expect, it, vi } from "vitest";

const SOURCE = fs.readFileSync(path.join(__dirname, "preload.cjs"), "utf8");
const realRequire = createRequire(import.meta.url);
const { IPC } = realRequire("./ipc-contract.cjs");

function loadPreload() {
  const listeners = new Map<string, ((event: unknown, payload: unknown) => void)[]>();
  const bridges: Record<string, Record<string, unknown>> = {};
  const electron = {
    contextBridge: { exposeInMainWorld: (name: string, value: Record<string, unknown>) => (bridges[name] = value) },
    ipcRenderer: {
      on: (channel: string, listener: (event: unknown, payload: unknown) => void) =>
        listeners.set(channel, [...(listeners.get(channel) ?? []), listener]),
      removeListener: (channel: string, listener: (event: unknown, payload: unknown) => void) =>
        listeners.set(channel, (listeners.get(channel) ?? []).filter((one) => one !== listener)),
      send: vi.fn(),
      invoke: vi.fn(async () => undefined),
    },
  };
  vm.runInNewContext(SOURCE, {
    require: (name: string) => (name === "electron" ? electron : realRequire(name)),
    document, window, MutationObserver, CustomEvent, process,
  });
  const push = (info: unknown) => (listeners.get(IPC.event.updateAvailable) ?? []).forEach((listener) => listener({}, info));
  const onUpdateAvailable = bridges.mosaelDesktop.onUpdateAvailable as (callback: (info: unknown) => void) => () => void;
  const desktop = bridges.mosaelDesktop as { backend: { retry: () => Promise<unknown> } };
  return { push, onUpdateAvailable, electron, desktop };
}

const INFO = { current: "1.9.3", latest: "1.9.4", hasUpdate: true, url: "https://github.com/Alndaly/Mosael/releases/tag/v1.9.4" };

it("消息早于订阅:订阅时补发最新的一条", () => {
  const { push, onUpdateAvailable } = loadPreload();
  push(INFO);
  const seen: unknown[] = [];
  onUpdateAvailable((info) => seen.push(info));
  expect(seen).toEqual([INFO]);
});

it("没收到过就不补发", () => {
  const { onUpdateAvailable } = loadPreload();
  const seen: unknown[] = [];
  onUpdateAvailable((info) => seen.push(info));
  expect(seen).toEqual([]);
});

it("「重试」能请主进程重拉后端(backend:retry)", async () => {
  const { electron, desktop } = loadPreload();
  await desktop.backend.retry();
  expect(electron.ipcRenderer.invoke).toHaveBeenCalledWith(IPC.invoke.backendRetry);
});
