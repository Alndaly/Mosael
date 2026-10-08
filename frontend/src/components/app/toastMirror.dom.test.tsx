/** @vitest-environment jsdom */

/**
 * 右下角的提示条(ADR 0051 D33 / D40):
 * - 内嵌浏览器、工作台的画布在前台时,提示条画进浮层视图(原生视图盖在一切 DOM 上,DOM 里那份看不见),上面的按钮点得到;
 * - 任何弹窗开着时,提示条上的按钮照样点得到,点了也不把弹窗当成「点了外面」关掉。
 *
 * 真机上实测过:写请求失败、拖到 Dock 上的文件导入失败的提示条在内嵌浏览器里一条都看不见;新建项目的弹窗开着时点更新提示的「查看」,
 * 落在遮罩上,弹窗关了,「查看」没打开。
 */
import React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { toast } from "sonner";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/app/preferences")>()),
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ theme: "light", locale: "zh-CN" }),
}));

import { AppToaster } from "@/app/App";
import { forwardToastsPointer, toastsExtent } from "@/components/app/toastMirror";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { installAppChromeGuards } from "@/components/ui/appChrome";
import { resetNativeViewAside, settleNativeViewAside, stepNativeViewAside } from "@/components/ui/nativeViewAside";
import { resetNativeViewForTests } from "@/lib/nativeView";

type Pointer = { type: "move" | "up" | "leave"; x: number; y: number };

function desktop() {
  let view: ((state: { visible: boolean }) => void) | null = null;
  let pointer: ((value: Pointer) => void) | null = null;
  const bridge = {
    onViewState: (callback: (state: { visible: boolean }) => void) => {
      view = callback;
      return () => (view = null);
    },
    showToasts: vi.fn(),
    hideToasts: vi.fn(),
    onToastsPointer: (callback: (value: Pointer) => void) => {
      pointer = callback;
      return () => (pointer = null);
    },
    setOverlay: vi.fn(async () => undefined),
  };
  vi.stubGlobal("mosaelPublish", bridge);
  return {
    bridge,
    show: (visible: boolean) => act(() => view?.({ visible })),
    pointer: (value: Pointer) => act(() => pointer?.(value)),
    hasPointer: () => pointer !== null,
  };
}

const frame = () => act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
const host = () => document.querySelector<HTMLElement>("[data-app-toaster]")!;

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })) as never;
});

beforeEach(() => {
  resetNativeViewForTests();
  Object.assign(window, { innerWidth: 1440, innerHeight: 900 });
});

afterEach(async () => {
  act(() => void toast.dismiss());
  cleanup();
  await settleNativeViewAside();
  resetNativeViewAside();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetNativeViewForTests();
});

describe("原生视图在前台时,提示条画进浮层视图", () => {
  it("视图不在前台:照常画在 DOM 里,不交给浮层视图", async () => {
    const desk = desktop();
    render(<AppToaster />);
    act(() => void toast("一条提示"));
    await screen.findByText("一条提示");
    await frame();
    expect(desk.bridge.showToasts).not.toHaveBeenCalled();
    expect(host().hasAttribute("data-toasts-mirrored")).toBe(false);
  });

  it("视图亮着:整块交给浮层视图,右下角贴着窗口右下角;DOM 里那份透明着(还在,照常计时、给读屏念)", async () => {
    const desk = desktop();
    render(<AppToaster />);
    desk.show(true);
    act(() => void toast("导入失败"));
    await screen.findByText("导入失败");
    await waitFor(() => expect(desk.bridge.showToasts).toHaveBeenCalled());
    const sent = desk.bridge.showToasts.mock.calls.at(-1)![0] as { html: string; rect: { x: number; y: number; width: number; height: number } };
    expect(sent.html).toContain("导入失败");
    expect(sent.html).toMatch(/^<section/);
    expect(sent.rect.x + sent.rect.width).toBe(1440);
    expect(sent.rect.y + sent.rect.height).toBe(900);
    expect(host().hasAttribute("data-toasts-mirrored")).toBe(true);
  });

  it("浮层视图上点「查看」= 点 DOM 里那一个;指针移进来提示条展开(停住计时),移出去收回", async () => {
    const desk = desktop();
    render(<AppToaster />);
    desk.show(true);
    const onClick = vi.fn();
    act(() => void toast("发现新版本", { action: { label: "查看", onClick } }));
    const button = await screen.findByRole("button", { name: "查看" });
    vi.spyOn(button, "getBoundingClientRect").mockReturnValue({ left: 1300, right: 1350, top: 840, bottom: 864, width: 50, height: 24, x: 1300, y: 840 } as DOMRect);
    await waitFor(() => expect(desk.hasPointer()).toBe(true));
    const item = button.closest<HTMLElement>("[data-sonner-toast]")!;

    desk.pointer({ type: "move", x: 1200, y: 850 });
    await waitFor(() => expect(item.dataset.expanded).toBe("true"));
    desk.pointer({ type: "up", x: 1100, y: 850 });
    expect(onClick, "点在空白处").not.toHaveBeenCalled();
    desk.pointer({ type: "up", x: 1320, y: 850 });
    expect(onClick).toHaveBeenCalledTimes(1);
    desk.pointer({ type: "leave", x: -1, y: -1 });
    await waitFor(() => expect(item.dataset.expanded).toBe("false"));
  });

  it("视图让开着(看大图、命令面板开着):窗口里看得见的全是 DOM,提示条回到 DOM 里;视图收起也一样", async () => {
    const desk = desktop();
    render(<AppToaster />);
    desk.show(true);
    act(() => void toast("一条提示"));
    await waitFor(() => expect(desk.bridge.showToasts).toHaveBeenCalled());

    let release = () => undefined as void;
    act(() => {
      release = stepNativeViewAside();
    });
    await waitFor(() => expect(desk.bridge.hideToasts).toHaveBeenCalledTimes(1));
    expect(host().hasAttribute("data-toasts-mirrored")).toBe(false);

    await act(async () => {
      release();
      await Promise.resolve();
    });
    await waitFor(() => expect(host().hasAttribute("data-toasts-mirrored")).toBe(true));
    await waitFor(() => expect(desk.bridge.showToasts).toHaveBeenCalledTimes(2));

    desk.show(false);
    expect(desk.bridge.hideToasts).toHaveBeenCalledTimes(2);
    expect(host().hasAttribute("data-toasts-mirrored")).toBe(false);
  });

  it("提示条都走了:浮层视图跟着收起", async () => {
    const desk = desktop();
    render(<AppToaster />);
    desk.show(true);
    act(() => void toast("一条提示", { id: "only" }));
    await waitFor(() => expect(desk.bridge.showToasts).toHaveBeenCalled());
    act(() => void toast.dismiss("only"));
    await waitFor(() => expect(desk.bridge.hideToasts).toHaveBeenCalled());
  });
});

describe("toastsExtent:按提示条摆满时的样子量,不按动画此刻走到哪儿", () => {
  function list(expanded: boolean) {
    const ol = document.createElement("ol");
    ol.setAttribute("data-sonner-toaster", "");
    ol.style.setProperty("--front-toast-height", "60px");
    ol.style.setProperty("--gap", "8px");
    [
      { offset: 0, height: 60 },
      { offset: 68, height: 80 },
      { offset: 156, height: 50 },
    ].forEach((one, index) => {
      const li = document.createElement("li");
      li.setAttribute("data-sonner-toast", "");
      Object.assign(li.dataset, { index: String(index), expanded: String(expanded), front: String(index === 0), visible: "true", removed: "false" });
      li.style.setProperty("--offset", `${one.offset}px`);
      li.style.setProperty("--initial-height", `${one.height}px`);
      ol.append(li);
    });
    return ol;
  }

  it("展开着:最上面那条的 --offset 加它自己的高", () => {
    expect(toastsExtent(list(true))).toBe(156 + 50);
  });

  it("收着:最前那条的高,后面每多一条往上露一道 --gap", () => {
    expect(toastsExtent(list(false))).toBe(60 + 8 * 2);
  });

  it("正在走的那条(data-removed)不算", () => {
    const ol = list(true);
    ol.lastElementChild!.setAttribute("data-removed", "true");
    expect(toastsExtent(ol)).toBe(68 + 80);
  });

  it("浮层视图上的指针没落到哪条提示上:什么都不点", () => {
    const host = document.createElement("div");
    host.append(list(false));
    document.body.append(host);
    expect(() => forwardToastsPointer(host, { type: "up", x: 5, y: 5 })).not.toThrow();
    host.remove();
  });
});

describe("任何弹窗开着时,提示条上的按钮照样点得到(D40)", () => {
  let uninstall = () => undefined as void;
  let style: HTMLStyleElement;
  beforeEach(() => {
    uninstall = installAppChromeGuards(document);
    //: 真正放开指针的是 styles.css 里的那一条(jsdom 不加载样式表):原样取出来放进文档
    const css = readFileSync(join(import.meta.dirname, "..", "..", "app", "styles.css"), "utf8");
    style = document.createElement("style");
    style.textContent = css.match(/\[data-app-chrome\]\s*\{[^}]*\}/)![0];
    document.head.append(style);
  });
  afterEach(() => {
    uninstall();
    style.remove();
  });

  it("模态弹窗把 body 设成 pointer-events: none:提示条上的「查看」照样点得到,点了弹窗不关", async () => {
    desktop();
    const listens = vi.spyOn(document, "addEventListener");
    render(
      <>
        <AppToaster />
        <Dialog open>
          <DialogContent>
            <DialogTitle>新建项目</DialogTitle>
          </DialogContent>
        </Dialog>
      </>,
    );
    //: Radix 在打开后的下一拍才开始听「点了外面」:等它挂上,不然弹窗没关只是因为还没在听
    await waitFor(() => expect(listens.mock.calls.some(([type, , options]) => type === "pointerdown" && options === undefined)).toBe(true));
    expect(document.body.style.pointerEvents).toBe("none");
    const onClick = vi.fn();
    act(() => void toast("发现新版本", { action: { label: "查看", onClick } }));
    const button = await screen.findByRole("button", { name: "查看", hidden: true });
    //: 不关掉 user-event 的 pointer-events 检查:它照着样式一层层往上找,和浏览器判「点不点得到」是同一回事
    await userEvent.setup().click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("新建项目")).not.toBeNull();
  });
});
