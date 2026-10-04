// @vitest-environment jsdom
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const SNAPSHOT = { frame: "data:image/jpeg;base64,AAAA", bounds: { x: 48, y: 56, width: 1392, height: 844 } };

const bridge = {
  snapshotPage: vi.fn(async (): Promise<typeof SNAPSHOT | null> => SNAPSHOT),
  coverPage: vi.fn(async (_covered: boolean) => undefined),
  switchPage: vi.fn(async () => true),
  closePage: vi.fn(async () => true),
  reorderPages: vi.fn(async () => true),
  newPage: vi.fn(async () => true),
  setPagesInset: vi.fn(async () => undefined),
};

beforeEach(() => {
  for (const fn of Object.values(bridge)) fn.mockClear();
  bridge.snapshotPage.mockImplementation(async () => SNAPSHOT);
  window.localStorage.clear();
  Object.defineProperty(window, "mosaelPublish", { configurable: true, value: bridge });
});

function state(extra: Partial<PublishViewState> = {}): PublishViewState {
  return { visible: true, accountId: "persist:pool-p1", accountName: "档案", pages: PAGES, pageLimit: 10, pageLimitHitAt: 0, ...extra };
}

const row = (id: string) => document.querySelector(`[data-page-row="${id}"]`) as HTMLElement;
const nav = () => document.querySelector("[data-page-list]") as HTMLElement;
const listState = () => nav().getAttribute("data-page-list");
const backdrop = () => document.querySelector("[data-page-peek-backdrop]") as HTMLImageElement | null;
const pause = (ms: number) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));

/** 临时展开:先等那张画面铺好(它加载完才藏原生视图),再等列表展开。 */
async function peekOut(start: () => void) {
  start();
  await waitFor(() => expect(backdrop()).not.toBeNull());
  fireEvent.load(backdrop()!);
  await waitFor(() => expect(listState()).toBe("peek"));
}

describe("页面列表", () => {
  it("列出每一页,当前页高亮;点一页切过去;悬停看网址;没标题的叫「新页面」", () => {
    render(<BrowserPageList state={state()} top={56} />);
    expect(row("2").dataset.current).toBe("true");
    expect(row("2").querySelector("[aria-current=page]")).not.toBeNull();
    expect(row("2").querySelector("img")?.getAttribute("src")).toBe("https://accounts.google.com/favicon.ico");
    // 网址在标题下面那一行(悬停这一行时露出来),不靠原生 title。
    expect(row("1").querySelector("button")?.textContent).toBe("首页https://example.com/");
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

describe("收起时临时展开(像 Arc)", () => {
  beforeEach(() => {
    window.localStorage.setItem("mosael.browserPages.collapsed", "1");
  });

  it("鼠标停在图标条上:拍下网页的画面铺在原处、藏起原生视图,列表盖在上面展开到完整宽度;移开就收回", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    expect(listState()).toBe("collapsed");
    await peekOut(() => fireEvent.mouseEnter(nav()));
    expect(bridge.snapshotPage).toHaveBeenCalledTimes(1);
    const shot = backdrop()!;
    expect(shot.getAttribute("src")).toBe(SNAPSHOT.frame);
    expect([shot.style.left, shot.style.top, shot.style.width, shot.style.height]).toEqual(["48px", "56px", "1392px", "844px"]);
    expect(bridge.coverPage).toHaveBeenLastCalledWith(true);
    expect(nav().style.width).toBe(`${PAGE_LIST_WIDTH}px`);
    // 盖在网页上,不推挤它:左侧让出的还是图标条那么宽。
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_COLLAPSED_WIDTH);
    // 每页的标题和网址都看得见(网址在悬停、聚焦那一行时露出来,和展开时一样)。
    expect(row("1").querySelector("button")?.textContent).toBe("首页https://example.com/");

    fireEvent.mouseLeave(nav());
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
    await waitFor(() => expect(backdrop()).toBeNull());
    expect(listState()).toBe("collapsed");
    expect(window.localStorage.getItem("mosael.browserPages.collapsed")).toBe("1");
  });

  it("一掠而过不展开:鼠标没停住就移开,不拍画面、不藏视图", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    fireEvent.mouseEnter(nav());
    fireEvent.mouseLeave(nav());
    await pause(300);
    expect(bridge.snapshotPage).not.toHaveBeenCalled();
    expect(bridge.coverPage).not.toHaveBeenCalled();
  });

  it("键盘切进列表也展开;焦点离开就收回", async () => {
    render(
      <>
        <button type="button" data-outside>
          outside
        </button>
        <BrowserPageList state={state()} top={56} />
      </>,
    );
    await peekOut(() => act(() => row("2").querySelector("button")!.focus()));
    act(() => (document.querySelector("[data-outside]") as HTMLElement).focus());
    await waitFor(() => expect(listState()).toBe("collapsed"));
    expect(bridge.coverPage).toHaveBeenLastCalledWith(false);
  });

  it("在展开的列表里点一页:切过去,马上收回让人看到那一页;鼠标移开再回来才再展开", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => fireEvent.mouseEnter(nav()));
    fireEvent.click(row("1").querySelector("button")!);
    expect(bridge.switchPage).toHaveBeenCalledWith("1");
    await waitFor(() => expect(backdrop()).toBeNull());
    expect(listState()).toBe("collapsed");
    expect(bridge.coverPage).toHaveBeenLastCalledWith(false);
    await pause(300);
    expect(bridge.snapshotPage).toHaveBeenCalledTimes(1);

    fireEvent.mouseLeave(nav());
    await pause(250);
    await peekOut(() => fireEvent.mouseEnter(nav()));
    expect(bridge.snapshotPage).toHaveBeenCalledTimes(2);
  });

  it("用键盘选了一页收回之后,鼠标再停上来照样展开(不用先移开一次)", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => act(() => row("2").querySelector("button")!.focus()));
    fireEvent.click(row("1").querySelector("button")!); // 键盘回车也是一次 click
    await waitFor(() => expect(listState()).toBe("collapsed"));
    await peekOut(() => fireEvent.mouseEnter(nav()));
    expect(bridge.snapshotPage).toHaveBeenCalledTimes(2);
  });

  it("新建页面:收起时点加号就展开出地址框;回车开了就收回;「收起」不变", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => fireEvent.click(document.querySelector("[data-page-list-new]")!));
    const input = document.querySelector("[data-page-list-address]") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "bilibili.com" } });
    fireEvent.submit(input.closest("form")!);
    expect(bridge.newPage).toHaveBeenCalledWith("bilibili.com");
    await waitFor(() => expect(listState()).toBe("collapsed"));
    expect(window.localStorage.getItem("mosael.browserPages.collapsed")).toBe("1");
  });

  it("「收起」照旧记在本机:临时展开不改它;在展开的列表里点「固定展开」才改", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => fireEvent.mouseEnter(nav()));
    const toggle = document.querySelector("[data-page-list-toggle]")!;
    expect(toggle.getAttribute("aria-label")).toBe("browserPagesPin");
    fireEvent.click(toggle);
    await waitFor(() => expect(listState()).toBe("expanded"));
    expect(window.localStorage.getItem("mosael.browserPages.collapsed")).toBeNull();
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_WIDTH);
    await waitFor(() => expect(backdrop()).toBeNull());
    expect(bridge.coverPage).toHaveBeenLastCalledWith(false);
  });

  it("展开着被卸掉(回到 Mosael)时把网页亮回来;拍不到画面就不展开", async () => {
    const { unmount } = render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => fireEvent.mouseEnter(nav()));
    unmount();
    expect(bridge.coverPage).toHaveBeenLastCalledWith(false);

    bridge.coverPage.mockClear();
    bridge.snapshotPage.mockImplementation(async () => null);
    render(<BrowserPageList state={state()} top={56} />);
    fireEvent.mouseEnter(nav());
    await waitFor(() => expect(bridge.snapshotPage).toHaveBeenCalled());
    await pause(100);
    expect(listState()).toBe("collapsed");
    expect(backdrop()).toBeNull();
    expect(bridge.coverPage).not.toHaveBeenCalled();
  });
});
