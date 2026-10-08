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
import { PAGE_LIST_MOTION_MS } from "./usePageListMotion";

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
  setPagesInset: vi.fn(async (_inset: number) => undefined),
  focusPage: vi.fn(async () => undefined),
};

beforeEach(() => {
  for (const fn of Object.values(bridge)) fn.mockClear();
  bridge.snapshotPage.mockImplementation(async () => SNAPSHOT);
  bridge.setPagesInset.mockImplementation(async () => undefined);
  bridge.coverPage.mockImplementation(async () => undefined);
  window.localStorage.clear();
  Object.defineProperty(window, "mosaelPublish", { configurable: true, value: bridge });
});

function state(extra: Partial<PublishViewState> = {}): PublishViewState {
  return { visible: true, accountId: "persist:pool-p1", accountName: "档案", pages: PAGES, pageLimit: 10, pageLimitHitAt: 0, ...extra };
}

const row = (id: string) => document.querySelector(`[data-page-row="${id}"]`) as HTMLElement;
const nav = () => document.querySelector("[data-page-list]") as HTMLElement;
const listState = () => nav().getAttribute("data-page-list");
/** 铺在原处的那张画面(一个裁切框里放着画面本身)。 */
const backdrop = () => document.querySelector("[data-page-backdrop] img") as HTMLImageElement | null;
const backdropFrame = () => document.querySelector("[data-page-backdrop]") as HTMLElement | null;
const pause = (ms: number) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));
/** 某一次调用排在第几(跨 mock 比先后)。 */
const order = (fn: { mock: { calls: unknown[][]; invocationCallOrder: number[] } }, ...args: unknown[]) => {
  const index = fn.mock.calls.findIndex((call) => JSON.stringify(call) === JSON.stringify(args));
  return index < 0 ? Number.POSITIVE_INFINITY : fn.mock.invocationCallOrder[index];
};

/** 等新拍的那张画面铺上(它加载完才挪开原生视图)。上一张可能还没拿掉,只认没加载过的那张。 */
async function coverLoads() {
  await waitFor(() => expect(backdrop() && !backdrop()!.dataset.loaded).toBe(true));
  const image = backdrop()!;
  image.dataset.loaded = "1";
  const covers = bridge.coverPage.mock.calls.filter(([covered]) => covered).length;
  fireEvent.load(image);
  await waitFor(() => expect(bridge.coverPage.mock.calls.filter(([covered]) => covered).length).toBe(covers + 1));
}

/** 临时展开:先等画面铺好,再等列表展开。 */
async function peekOut(start: () => void) {
  start();
  await coverLoads();
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

  it("挂上时左侧让出列表那么宽;收起成图标条变窄并记住;卸载时还回去", async () => {
    const { unmount } = render(<BrowserPageList state={state()} top={56} />);
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_WIDTH);
    fireEvent.click(document.querySelector("[data-page-list-toggle]")!);
    expect(window.localStorage.getItem("mosael.browserPages.collapsed")).toBe("1");
    await coverLoads();
    await waitFor(() => expect(listState()).toBe("collapsed"));
    expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_COLLAPSED_WIDTH);
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
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
    expect(backdrop()!.getAttribute("src")).toBe(SNAPSHOT.frame);
    const frame = backdropFrame()!;
    expect([frame.style.left, frame.style.top, frame.style.width, frame.style.height]).toEqual(["48px", "56px", "1392px", "844px"]);
    expect([backdrop()!.style.width, backdrop()!.style.height]).toEqual(["1392px", "844px"]);
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
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
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
    //: 让出多宽跟着动画的形状(usePageListMotion 的 shape)走,比 listState 晚一步;慢机器上晚得更多 —— 等它,不量先后。
    await waitFor(() => expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_WIDTH));
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

describe("展开、收起的过渡", () => {
  it("固定展开 → 收起:先拍下画面盖住网页,再让网页左侧变窄;列表和画面一起滑过去,走完才揭开", async () => {
    //: 「网页变窄」那一刻的样子在那一刻记下来:滑动只有 160ms,事后再看,机器一忙(waitFor 隔 50ms 才看一眼、线程被抢)
    //: 看到时已经滑完、揭开了 —— 并行满载时实测 `coverPage` 已经被叫过 false。
    let sliding: Record<string, unknown> | null = null;
    bridge.setPagesInset.mockImplementation(async (inset: number) => {
      if (inset !== PAGE_LIST_COLLAPSED_WIDTH || sliding) return;
      sliding = {
        navWidth: nav().style.width,
        navTransition: nav().style.transition,
        frameLeft: backdropFrame()?.style.left,
        frameTransition: backdropFrame()?.style.transition,
        uncovered: bridge.coverPage.mock.calls.some(([covered]) => covered === false),
      };
    });
    render(<BrowserPageList state={state()} top={56} />);
    bridge.snapshotPage.mockImplementation(async () => ({ ...SNAPSHOT, bounds: { ...SNAPSHOT.bounds, x: 220, width: 1220 } }));
    fireEvent.click(document.querySelector("[data-page-list-toggle]")!);
    // 画面没盖好之前,网页和列表都不动。
    expect(bridge.setPagesInset).not.toHaveBeenCalledWith(PAGE_LIST_COLLAPSED_WIDTH);
    expect(nav().style.width).toBe(`${PAGE_LIST_WIDTH}px`);
    await coverLoads();
    // 画面先铺在网页原来的位置,对齐到像素。
    await waitFor(() => expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_COLLAPSED_WIDTH));
    // 盖着的时候列表和画面的左沿一起往回滑(同一条过渡),那时还没揭开。
    expect(sliding).toEqual({
      navWidth: `${PAGE_LIST_COLLAPSED_WIDTH}px`,
      navTransition: expect.stringContaining(`width ${PAGE_LIST_MOTION_MS}ms`),
      frameLeft: `${PAGE_LIST_COLLAPSED_WIDTH}px`,
      frameTransition: expect.stringContaining(`left ${PAGE_LIST_MOTION_MS}ms`),
      uncovered: false,
    });
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
    await waitFor(() => expect(backdrop()).toBeNull());
    expect(order(bridge.snapshotPage)).toBeLessThan(order(bridge.coverPage, true));
    expect(order(bridge.coverPage, true)).toBeLessThan(order(bridge.setPagesInset, PAGE_LIST_COLLAPSED_WIDTH));
    expect(order(bridge.setPagesInset, PAGE_LIST_COLLAPSED_WIDTH)).toBeLessThan(order(bridge.coverPage, false));
  });

  it("画面起步时就在网页原来的位置(收起前是 220)", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    bridge.snapshotPage.mockImplementation(async () => ({ ...SNAPSHOT, bounds: { ...SNAPSHOT.bounds, x: 220, width: 1220 } }));
    fireEvent.click(document.querySelector("[data-page-list-toggle]")!);
    await waitFor(() => expect(backdrop()).not.toBeNull());
    expect(backdropFrame()!.style.left).toBe("220px");
    expect(backdropFrame()!.style.width).toBe("1220px");
    expect(backdrop()!.style.width).toBe("1220px");
  });

  it("收起 → 展开(图标条上的按钮,不等临时展开):一样先盖后揭,网页挪好了才揭开", async () => {
    window.localStorage.setItem("mosael.browserPages.collapsed", "1");
    render(<BrowserPageList state={state()} top={56} />);
    fireEvent.click(document.querySelector("[data-page-list-toggle]")!);
    await coverLoads();
    await waitFor(() => expect(listState()).toBe("expanded"));
    expect(nav().style.width).toBe(`${PAGE_LIST_WIDTH}px`);
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
    expect(order(bridge.coverPage, true)).toBeLessThan(order(bridge.setPagesInset, PAGE_LIST_WIDTH));
    expect(order(bridge.setPagesInset, PAGE_LIST_WIDTH)).toBeLessThan(order(bridge.coverPage, false));
    expect(window.localStorage.getItem("mosael.browserPages.collapsed")).toBeNull();
  });

  it("临时展开 → 固定展开:一直盖着,中途不揭开(不会先露出窄的网页再跳到宽的)", async () => {
    window.localStorage.setItem("mosael.browserPages.collapsed", "1");
    render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => fireEvent.mouseEnter(nav()));
    fireEvent.click(document.querySelector("[data-page-list-toggle]")!);
    await waitFor(() => expect(bridge.setPagesInset).toHaveBeenLastCalledWith(PAGE_LIST_WIDTH));
    expect(bridge.snapshotPage).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
    //: 中途一次都没揭开:揭开只有最后那一次,排在网页挪好之后。按调用先后判,不在「看见网页挪好」那一刻去看还没揭开 ——
    //: 那一刻之后只剩 160ms 的滑动,机器一忙,看的时候已经滑完、揭开了(并行满载时实测)。
    expect(bridge.coverPage.mock.calls.filter(([covered]) => covered === false)).toHaveLength(1);
    expect(order(bridge.setPagesInset, PAGE_LIST_WIDTH)).toBeLessThan(order(bridge.coverPage, false));
  });

  it("临时展开、收回也是滑出去滑回来:列表宽度带过渡,收回时滑完了才揭开", async () => {
    window.localStorage.setItem("mosael.browserPages.collapsed", "1");
    render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => fireEvent.mouseEnter(nav()));
    expect(nav().style.transition).toContain(`width ${PAGE_LIST_MOTION_MS}ms`);
    //: 揭开那一刻列表是什么样子,在那一刻记下来(同上:不在事后去看「还没揭开」)。
    const atUncover: (string | null)[] = [];
    bridge.coverPage.mockImplementation(async (covered: boolean) => {
      if (!covered) atUncover.push(listState());
    });
    fireEvent.mouseLeave(nav());
    await waitFor(() => expect(listState()).toBe("collapsed"));
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
    expect(atUncover, "揭开时列表已经收回了,不是一边揭开一边还在临时展开").toEqual(["collapsed"]);
  });

  it("要求减少动态:不过渡,但照样先盖后揭", async () => {
    const matchMedia = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
    try {
      render(<BrowserPageList state={state()} top={56} />);
      expect(nav().style.transition).toBe("none");
      fireEvent.click(document.querySelector("[data-page-list-toggle]")!);
      await coverLoads();
      await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
      expect(order(bridge.coverPage, true)).toBeLessThan(order(bridge.setPagesInset, PAGE_LIST_COLLAPSED_WIDTH));
    } finally {
      window.matchMedia = matchMedia;
    }
  });
});

describe("键盘焦点", () => {
  it("选了一页、开了新页面、关了一页:键盘交给网页(接着打字的是网页)", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    fireEvent.click(row("1").querySelector("button")!, { detail: 1 });
    expect(bridge.focusPage).toHaveBeenCalledTimes(1);
    fireEvent.click(row("3").querySelector("[data-page-close]")!, { detail: 1 });
    expect(bridge.focusPage).toHaveBeenCalledTimes(2);
    fireEvent.click(document.querySelector("[data-page-list-new]")!);
    const input = document.querySelector("[data-page-list-address]") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "bilibili.com" } });
    fireEvent.submit(input.closest("form")!);
    expect(bridge.focusPage).toHaveBeenCalledTimes(3);
  });

  it("用鼠标点收起:键盘交给网页;用键盘按的(detail 0),焦点留在按钮上", async () => {
    render(<BrowserPageList state={state()} top={56} />);
    const toggle = document.querySelector("[data-page-list-toggle]") as HTMLButtonElement;
    act(() => toggle.focus());
    fireEvent.click(toggle, { detail: 0 });
    expect(bridge.focusPage).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(toggle);
    await coverLoads();
    await waitFor(() => expect(bridge.coverPage).toHaveBeenLastCalledWith(false));
    fireEvent.click(document.querySelector("[data-page-list-toggle]")!, { detail: 1 });
    expect(bridge.focusPage).toHaveBeenCalledTimes(1);
  });

  it("临时展开时按 Esc:收回,键盘交给网页", async () => {
    window.localStorage.setItem("mosael.browserPages.collapsed", "1");
    render(<BrowserPageList state={state()} top={56} />);
    await peekOut(() => act(() => row("2").querySelector("button")!.focus()));
    fireEvent.keyDown(row("2").querySelector("button")!, { key: "Escape" });
    await waitFor(() => expect(listState()).toBe("collapsed"));
    expect(bridge.focusPage).toHaveBeenCalled();
  });
});
