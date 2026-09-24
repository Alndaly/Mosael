/** @vitest-environment jsdom */
/**
 * 界面语言怎么到主进程:preload 盯着 `<html lang>`,变了就报(见 preload.cjs 那一段)。
 *
 * 钉三件事:脚本写上去的值会报;同一个值重写(偏好每次保存都重写 lang)不重复报;
 * index.html 里静态的那个 lang 不报 —— 否则英文用户每次启动菜单都先闪一下中文。
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import vm from "node:vm";

import { describe, expect, it, vi } from "vitest";

const SOURCE = fs.readFileSync(path.join(__dirname, "preload.cjs"), "utf8");
const realRequire = createRequire(import.meta.url);
const { IPC } = realRequire("./ipc-contract.cjs");

function loadPreload() {
  const send = vi.fn();
  const electron = {
    contextBridge: { exposeInMainWorld: vi.fn() },
    ipcRenderer: { on: vi.fn(), send, invoke: vi.fn(), removeListener: vi.fn() },
  };
  vm.runInNewContext(SOURCE, {
    require: (name: string) => (name === "electron" ? electron : realRequire(name)),
    document,
    window,
    MutationObserver,
    CustomEvent,
    process,
  });
  return send;
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const localeCalls = (send: ReturnType<typeof vi.fn>) =>
  send.mock.calls.filter(([channel]) => channel === IPC.send.locale).map(([, payload]) => payload);

describe("界面语言上报", () => {
  it("报渲染层写上去的 lang,重写同一个值不重复报,切换时再报", async () => {
    document.documentElement.setAttribute("lang", "zh-CN"); // index.html 里的静态值
    const send = loadPreload();
    await flush();
    expect(localeCalls(send)).toEqual([]);

    document.documentElement.lang = "en-US";
    await flush();
    document.documentElement.lang = "en-US";
    await flush();
    expect(localeCalls(send)).toEqual([{ locale: "en-US" }]);

    document.documentElement.lang = "zh-CN";
    await flush();
    expect(localeCalls(send)).toEqual([{ locale: "en-US" }, { locale: "zh-CN" }]);
  });
});
