/** @vitest-environment jsdom */
import { act, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { stepNativeViewAside } from "@/components/ui/nativeViewAside";
import { installEmbeddedFocus, pageAfterPointer } from "./embeddedFocus";

/**
 * 键盘焦点在 Mosael 和内嵌网页之间怎么走:回到 Mosael 时焦点落回打开之前的那个按钮;网页亮着时,落在 Mosael
 * 看不见的地方的按键不让它生效(交给网页);外壳里用鼠标点完,键盘交回网页。
 */
type ViewState = { visible: boolean; accountId: string | null; accountName: string | null };
let listeners: Array<(state: ViewState) => void> = [];
const focusPage = vi.fn(async () => undefined);
const emit = (state: ViewState) => act(() => listeners.forEach((listener) => listener(state)));
const frame = () => act(() => new Promise((resolve) => setTimeout(resolve, 20)));
let uninstall = () => undefined as void;

beforeEach(() => {
  listeners = [];
  focusPage.mockClear();
  document.body.innerHTML = `
    <div role="dialog"><button id="opener">在工作台里打开</button><button id="other">别的</button></div>
    <div data-app-chrome=""><input id="address" aria-label="地址栏" /><button id="back">返回 Mosael</button></div>`;
  Object.defineProperty(window, "mosaelPublish", {
    configurable: true,
    value: {
      focusPage,
      onViewState: (callback: (state: ViewState) => void) => {
        listeners.push(callback);
        return () => {
          listeners = listeners.filter((one) => one !== callback);
        };
      },
    },
  });
  uninstall = installEmbeddedFocus();
});
afterEach(() => uninstall());

const byId = (id: string) => document.getElementById(id) as HTMLElement;
const show = () => emit({ visible: true, accountId: "persist:pool-comfyui-i1", accountName: "ComfyUI" });
const hide = () => emit({ visible: false, accountId: null, accountName: null });

describe("回到 Mosael 时焦点落回打开之前的那个按钮", () => {
  it("点「在工作台里打开」进去,在顶栏里点过东西,回来焦点还在「在工作台里打开」上", async () => {
    act(() => byId("opener").focus());
    show();
    act(() => byId("address").focus());
    hide();
    await frame();
    expect(document.activeElement).toBe(byId("opener"));
  });

  it("那个按钮已经不在了(弹窗关了)就不硬找", async () => {
    act(() => byId("opener").focus());
    show();
    byId("opener").remove();
    hide();
    await frame();
    expect(document.activeElement).not.toBe(byId("opener"));
  });
});

describe("网页亮着时,落在 Mosael 看不见的地方的按键", () => {
  it("不让它生效(不然回车会把底下看不见的按钮再点一次),键盘交给网页", () => {
    act(() => byId("opener").focus());
    show();
    const onKey = vi.fn();
    byId("opener").addEventListener("keydown", onKey);
    const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    byId("opener").dispatchEvent(event);
    expect(onKey).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(true);
    expect(focusPage).toHaveBeenCalled();
  });

  it("外壳里的按键照常(地址栏能打字);网页没亮着时什么都不管", () => {
    show();
    const onKey = vi.fn();
    byId("address").addEventListener("keydown", onKey);
    fireEvent.keyDown(byId("address"), { key: "a" });
    expect(onKey).toHaveBeenCalledTimes(1);
    hide();
    const onOther = vi.fn();
    byId("other").addEventListener("keydown", onOther);
    fireEvent.keyDown(byId("other"), { key: "Enter" });
    expect(onOther).toHaveBeenCalledTimes(1);
    expect(focusPage).not.toHaveBeenCalled();
  });

  it("大图开着(网页挪到了窗口外):按键是给大图的 —— Esc、左右翻页不被吞,也不把键盘交给挪开的网页", () => {
    show();
    const release = stepNativeViewAside();
    const onKey = vi.fn();
    document.body.addEventListener("keydown", onKey);
    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    document.body.dispatchEvent(event);
    expect(onKey).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(false);
    expect(focusPage).not.toHaveBeenCalled();
    release();
    document.body.removeEventListener("keydown", onKey);
  });
});

describe("外壳里用鼠标点完,键盘交回网页", () => {
  it("鼠标点的交回网页;键盘按的(Enter / 空格,click 的 detail 是 0)焦点留在外壳里接着走", () => {
    pageAfterPointer({ detail: 1 });
    expect(focusPage).toHaveBeenCalledTimes(1);
    pageAfterPointer({ detail: 0 });
    expect(focusPage).toHaveBeenCalledTimes(1);
  });
});
