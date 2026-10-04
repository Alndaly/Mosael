// @vitest-environment jsdom
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 浏览器会话左侧的页面列表:走用户会点的那几下 —— 切页、关页、新建、拖动排序、收起展开(记住)、开满了的
 * 提示。主进程换成记账的假 window.mosaelPublish:要验的是「交给主进程的是什么」、左侧让出多宽。
 */
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "browserPagesLimit" ? "limit {n}" : key),
}));

import { BrowserPageList, PAGE_LIST_COLLAPSED_WIDTH, PAGE_LIST_WIDTH } from "./BrowserPageList";
import { moveBefore } from "./pageListState";

const PAGES = [
  { id: "1", title: "首页", url: "https://example.com/", favicon: "", current: false },
  { id: "2", title: "Google 账号登录", url: "https://accounts.google.com/signin", favicon: "https://accounts.google.com/favicon.ico", current: true },
  { id: "3", title: "", url: "about:blank", favicon: "", current: false },
];

const bridge = {
  switchPage: vi.fn(async () => true),
  closePage: vi.fn(async () => true),
  reorderPages: vi.fn(async () => true),
  newPage: vi.fn(async () => true),
  setPagesInset: vi.fn(async () => undefined),
};

beforeEach(() => {
  for (const fn of Object.values(bridge)) fn.mockClear();
  window.localStorage.clear();
  Object.defineProperty(window, "mosaelPublish", { configurable: true, value: bridge });
});

function state(extra: Partial<PublishViewState> = {}): PublishViewState {
  return { visible: true, accountId: "persist:pool-p1", accountName: "档案", pages: PAGES, pageLimit: 10, pageLimitHitAt: 0, ...extra };
}

const row = (id: string) => document.querySelector(`[data-page-row="${id}"]`) as HTMLElement;

describe("页面列表", () => {
  it("列出每一页,当前页高亮;点一页切过去;悬停看网址;没标题的叫「新页面」", () => {
    render(<BrowserPageList state={state()} top={56} />);
    expect(row("2").dataset.current).toBe("true");
    expect(row("2").querySelector("[aria-current=page]")).not.toBeNull();
    expect(row("2").querySelector("img")?.getAttribute("src")).toBe("https://accounts.google.com/favicon.ico");
    expect(row("1").querySelector("button")?.getAttribute("title")).toBe("首页\nhttps://example.com/");
    expect(row("3").textContent).toContain("browserPagesUntitled");
    fireEvent.click(row("1").querySelector("button")!);
    expect(bridge.switchPage).toHaveBeenCalledWith("1");
  });

  it("关一页;只剩一页时没有关闭按钮", () => {
    const { rerender } = render(<BrowserPageList state={state()} top={56} />);
    fireEvent.click(row("3").querySelector("[data-page-close]")!);
    expect(bridge.closePage).toHaveBeenCalledWith("3");
    rerender(<BrowserPageList state={state({ pages: [PAGES[0]] })} top={56} />);
    expect(row("1").querySelector("[data-page-close]")).toBeNull();
  });

  it("新建页面:敲地址回车就开;Esc 收起", () => {
    render(<BrowserPageList state={state()} top={56} />);
    fireEvent.click(document.querySelector("[data-page-list-new]")!);
    const input = document.querySelector("[data-page-list-address]") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "bilibili.com" } });
    fireEvent.submit(input.closest("form")!);
    expect(bridge.newPage).toHaveBeenCalledWith("bilibili.com");
    expect(document.querySelector("[data-page-list-address]")).toBeNull();

    fireEvent.click(document.querySelector("[data-page-list-new]")!);
    fireEvent.keyDown(document.querySelector("[data-page-list-address]")!, { key: "Escape" });
    expect(document.querySelector("[data-page-list-address]")).toBeNull();
  });

  it("拖动排序:把一页拖到另一页上,交给主进程整份新次序", () => {
    render(<BrowserPageList state={state()} top={56} />);
    fireEvent.dragStart(row("3"), { dataTransfer: { setData: () => undefined, effectAllowed: "" } });
    fireEvent.drop(row("1"));
    expect(bridge.reorderPages).toHaveBeenCalledWith(["3", "1", "2"]);
  });

  it("挂上时左侧让出列表那么宽;收起成图标条变窄并记住;卸载时还回去", () => {
    const { unmount } = render(<BrowserPageList state={state()} top={56} />);
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_WIDTH);
    fireEvent.click(document.querySelector("[data-page-list-toggle]")!);
    expect(document.querySelector("[data-page-list]")?.getAttribute("data-page-list")).toBe("collapsed");
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_COLLAPSED_WIDTH);
    expect(window.localStorage.getItem("mosael.browserPages.collapsed")).toBe("1");
    unmount();
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(0);

    // 下次打开还是收起的。
    render(<BrowserPageList state={state()} top={56} />);
    expect(document.querySelector("[data-page-list]")?.getAttribute("data-page-list")).toBe("collapsed");
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_COLLAPSED_WIDTH);
  });

  it("开满了被拦下时说一句(挂上之前那次不算)", () => {
    vi.useFakeTimers();
    const { rerender } = render(<BrowserPageList state={state({ pageLimitHitAt: 5 })} top={56} />);
    expect(screen.queryByRole("status")).toBeNull();
    rerender(<BrowserPageList state={state({ pageLimitHitAt: 9 })} top={56} />);
    expect(screen.getByRole("status").textContent).toBe("limit 10");
    act(() => {
      vi.advanceTimersByTime(6_100);
    });
    expect(screen.queryByRole("status")).toBeNull();
    vi.useRealTimers();
  });

  it("没有页面信息(老主进程 / 不是浏览器会话)时不画", () => {
    render(<BrowserPageList state={state({ pages: [] })} top={56} />);
    expect(document.querySelector("[data-page-list]")).toBeNull();
  });
});

describe("拖动重排的次序", () => {
  it("往上拖放到目标前面,往下拖放到目标后面(落在谁身上占谁的位置)", () => {
    expect(moveBefore(["a", "b", "c", "d"], "d", "b")).toEqual(["a", "d", "b", "c"]);
    expect(moveBefore(["a", "b", "c", "d"], "a", "c")).toEqual(["b", "c", "a", "d"]);
    expect(moveBefore(["a", "b"], "a", "a")).toEqual(["a", "b"]);
    expect(moveBefore(["a", "b"], "x", "a")).toEqual(["a", "b"]);
  });
});
