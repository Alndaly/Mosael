/** @vitest-environment jsdom */
/**
 * 「保存到本地」那座桥(见 preload.cjs):渲染层调到的是主进程那四个通道,送过去的就是它手里的那个请求
 * (建议名、一块字节、手柄原样,不在这一层改样)。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";

import { expect, it, vi } from "vitest";

const SOURCE = fs.readFileSync(path.join(__dirname, "preload.cjs"), "utf8");
const realRequire = createRequire(import.meta.url);
const { IPC } = realRequire("./ipc-contract.cjs");

type SaveFileBridge = {
  begin: (request: { name: string }) => Promise<unknown>;
  write: (request: { id: string; bytes: Uint8Array }) => Promise<unknown>;
  end: (request: { id: string }) => Promise<unknown>;
  abort: (request: { id: string }) => Promise<unknown>;
};

function loadPreload() {
  const bridges: Record<string, Record<string, unknown>> = {};
  const electron = {
    contextBridge: { exposeInMainWorld: (name: string, value: Record<string, unknown>) => (bridges[name] = value) },
    ipcRenderer: {
      on: vi.fn(),
      removeListener: vi.fn(),
      send: vi.fn(),
      invoke: vi.fn(async () => undefined),
    },
  };
  vm.runInNewContext(SOURCE, {
    require: (name: string) => (name === "electron" ? electron : realRequire(name)),
    document, window, MutationObserver, CustomEvent, process,
  });
  return { electron, saveFile: (bridges.mosaelPublish as { saveFile: SaveFileBridge }).saveFile };
}

it("四个动作各自对上一个通道,请求原样送过去(字节不改样)", async () => {
  const { electron, saveFile } = loadPreload();
  const id = "0f8fad5b-d9cb-469f-a165-70867728950e";
  const bytes = new Uint8Array([1, 2, 3]);

  await saveFile.begin({ name: "配音.wav" });
  expect(electron.ipcRenderer.invoke).toHaveBeenNthCalledWith(1, IPC.invoke.saveFileBegin, { name: "配音.wav" });
  await saveFile.write({ id, bytes });
  expect(electron.ipcRenderer.invoke).toHaveBeenNthCalledWith(2, IPC.invoke.saveFileWrite, { id, bytes });
  await saveFile.end({ id });
  expect(electron.ipcRenderer.invoke).toHaveBeenNthCalledWith(3, IPC.invoke.saveFileEnd, { id });
  await saveFile.abort({ id });
  expect(electron.ipcRenderer.invoke).toHaveBeenNthCalledWith(4, IPC.invoke.saveFileAbort, { id });
});
