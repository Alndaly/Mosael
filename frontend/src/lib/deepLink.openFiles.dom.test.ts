/**
 * 应用**还没起来**时系统交过来的那批文件,不能丢。
 *
 * 主进程那侧(见 electron/system/protocol 的 deliver)是等 `did-finish-load` 就把 `open-files`
 * 发出来的 —— 那时候页面脚本刚跑完,React 还什么都没挂。而渲染层这一侧听 `mosael:open-files` 的
 * `listenDesktopDeepLinks` 由 App.tsx 的 Studio 挂上,也就是**登录完、工作区列表回来之后**。中间那
 * 段是空窗:事件照发,没人接。
 *
 * 现象是①(图片进「打开方式」)最要紧的那条路整条失效:双击一张图把 Mosael 冷启起来 —— 窗口开了,
 * 素材库里什么都没有,也没有任何提示。已经在跑的时候反而没事(那时 Studio 早挂上了)。
 *
 * 所以和 `lib/inviteLinks` 同一条做法:`main.tsx` 在渲染之前先 `installOpenFilesInbox()`。
 */
/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from "vitest";

const emit = (paths: unknown) =>
  window.dispatchEvent(new CustomEvent("mosael:open-files", { detail: paths }));

/** 模块状态是模块级的(它要活过 React 的挂载),每条用例都重新 import 一份干净的。 */
async function fresh() {
  vi.resetModules();
  return import("./deepLink");
}

beforeEach(() => vi.resetModules());

describe("「用 Mosael 打开」交过来的文件:还没挂载时的信箱", () => {
  it("先来后到:应用还没挂上时到的,挂上时补齐", async () => {
    const { installOpenFilesInbox, listenDesktopDeepLinks } = await fresh();
    installOpenFilesInbox();

    emit(["/a.png"]);
    emit(["/b.mp4", "/c.png"]);

    const seen: string[][] = [];
    listenDesktopDeepLinks((paths) => seen.push([...paths]));
    expect(seen).toEqual([["/a.png"], ["/b.mp4", "/c.png"]]);
  });

  it("取走就不再投 —— 否则每次重挂都会把同一批再导一遍", async () => {
    const { installOpenFilesInbox, listenDesktopDeepLinks } = await fresh();
    installOpenFilesInbox();
    emit(["/a.png"]);

    listenDesktopDeepLinks(() => {});
    const again: string[][] = [];
    listenDesktopDeepLinks((paths) => again.push([...paths]));
    expect(again).toEqual([]);
  });

  it("应用已经开着:当场送到,不进信箱", async () => {
    const { installOpenFilesInbox, listenDesktopDeepLinks } = await fresh();
    installOpenFilesInbox();
    const seen: string[][] = [];
    listenDesktopDeepLinks((paths) => seen.push([...paths]));

    emit(["/a.png"]);
    expect(seen).toEqual([["/a.png"]]);
  });

  it("退订之后到的重新进信箱 —— 切工作区会重新挂一次,期间到的文件不该丢", async () => {
    const { installOpenFilesInbox, listenDesktopDeepLinks } = await fresh();
    installOpenFilesInbox();
    const first = vi.fn();
    const stop = listenDesktopDeepLinks(first);

    emit(["/a.png"]);
    stop();
    emit(["/b.png"]);
    expect(first).toHaveBeenCalledTimes(1);

    const second = vi.fn();
    listenDesktopDeepLinks(second);
    expect(second).toHaveBeenCalledTimes(1);
    expect(second.mock.calls[0][0]).toEqual(["/b.png"]);
  });

  it("空数组、坏形状不当成一批:混进来的非字符串剔掉,那一批其余照旧", async () => {
    const { installOpenFilesInbox, listenDesktopDeepLinks } = await fresh();
    installOpenFilesInbox();

    emit([]);
    emit(undefined);
    emit("nope");
    emit([42, null, "/a.png"]);

    const seen: string[][] = [];
    listenDesktopDeepLinks((paths) => seen.push([...paths]));
    expect(seen).toEqual([["/a.png"]]);
  });

  it("听筒没挂上之前到的,找不回来 —— 所以 main.tsx 那一次必须是第一件事", async () => {
    const { installOpenFilesInbox, listenDesktopDeepLinks } = await fresh();
    //: 渲染之前的调用漏了(或者被挪到了 import App 之后),冷启动那批就真的没了。
    emit(["/too-early.png"]);
    installOpenFilesInbox();

    const seen: string[][] = [];
    listenDesktopDeepLinks((paths) => seen.push([...paths]));
    expect(seen).toEqual([]);
  });
});

describe("和深链共用同一个落点", () => {
  it("listenDesktopDeepLinks 仍然接得住 mosael:deep-link", async () => {
    const { listenDesktopDeepLinks } = await fresh();
    const files = vi.fn();
    const stop = listenDesktopDeepLinks(files);
    //: 文件那条通道没被碰坏,深链那条也照旧(只导航 —— 这里只证明它没被这次的改动弄丢)。
    expect(() => window.dispatchEvent(new CustomEvent("mosael:deep-link", { detail: { view: "editor" } }))).not.toThrow();
    stop();
  });
});
