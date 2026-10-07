/** @vitest-environment jsdom */
/**
 * 内嵌视图的状态是主进程**推**的:渲染层(重新)加载时主进程在 did-finish-load 补播一帧,而应用是动态 import 进来的、React
 * 订阅得更晚。漏了那一帧,渲染层以为没有视图、不画顶栏(内嵌浏览器的、工作台的),原生视图却还盖在窗口上 —— 维护者截图里
 * 插件页上压着的那块光秃秃的 ComfyUI 画布。preload 一加载就订阅、记住最新的一帧,订阅时先补发它(和全屏状态同一个做法)。
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
  const bridges: Record<string, Record<string, (...args: never[]) => unknown>> = {};
  const electron = {
    contextBridge: { exposeInMainWorld: (name: string, value: Record<string, (...args: never[]) => unknown>) => (bridges[name] = value) },
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
  const push = (state: unknown) => (listeners.get(IPC.event.publishView) ?? []).forEach((listener) => listener({}, state));
  const onViewState = bridges.mosaelPublish.onViewState as unknown as (callback: (state: unknown) => void) => () => void;
  return { push, onViewState };
}

const COMFY = { visible: true, accountId: "persist:pool-comfyui-c1", partition: "persist:pool-comfyui-c1", accountName: "ComfyUI" };

it("主进程补播的那一帧早于订阅:订阅时补发最新的一帧,之后的照常收", () => {
  const { push, onViewState } = loadPreload();
  push({ ...COMFY, title: "旧的一帧" });
  push(COMFY);
  const seen: unknown[] = [];
  const stop = onViewState((state) => seen.push(state));
  expect(seen, "订阅时就知道视图亮着:顶栏画得出来").toEqual([COMFY]);
  push({ visible: false, accountId: null, accountName: null });
  expect(seen).toHaveLength(2);
  stop();
  push(COMFY);
  expect(seen, "退订之后不再收").toHaveLength(2);
});

it("还没收到过就不补发(不编一帧「没有视图」出来)", () => {
  const { onViewState } = loadPreload();
  const seen: unknown[] = [];
  onViewState((state) => seen.push(state));
  expect(seen).toEqual([]);
});
