// @vitest-environment jsdom
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "livePanelRunTitle" ? "{workflow} · {time}" : key),
}));

const sessions = vi.hoisted(() => ({ getBrowserSession: vi.fn() }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...sessions,
}));

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { hoverHint, readHint } from "@/test/hint";
import { LivePanels } from "./LivePanels";

/** 卡片标题要问后端「这个会话是谁开的」(react-query);缺省它是发布账号那种 —— 不是会话,404。 */
function renderPanels(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const CARD: LivePanelCard = {
  id: "browser-1",
  x: 20,
  y: 20,
  width: 384,
  height: 265,
  header: 26,
  radius: 12,
  muted: true,
  hovered: false,
  pages: 1,
  page: 1,
};

let publishPanels: ((cards: LivePanelCard[]) => void) | null;
const setPanelMuted = vi.fn(async () => undefined);
const setPanelLayout = vi.fn(async (_change: unknown) => undefined);

beforeEach(() => {
  sessions.getBrowserSession.mockReset();
  sessions.getBrowserSession.mockRejectedValue(new ApiError("not found", 404, ""));
  publishPanels = null;
  setPanelMuted.mockClear();
  setPanelLayout.mockClear();
  Object.defineProperty(window, "mosaelPublish", {
    configurable: true,
    value: {
      onPanels: (callback: (cards: LivePanelCard[]) => void) => {
        publishPanels = callback;
        return () => undefined;
      },
      setPanelMuted,
      setPanelLayout,
    },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

function show(...cards: LivePanelCard[]) {
  act(() => publishPanels?.(cards.length ? cards : [CARD]));
}

const shell = (id = CARD.id) => document.querySelector(`[data-live-panel="${id}"]`) as HTMLElement;
const handlesLayer = () => document.querySelector("[data-live-panel-handles]") as HTMLElement;
const handle = (name: LivePanelHandle) => document.querySelector(`[data-resize-handle="${name}"]`) as HTMLElement;

describe("LivePanels audio", () => {
  it("uses the main-process mute state and toggles the top embedded browser", () => {
    renderPanels(<LivePanels />);
    show();

    const button = screen.getByRole("button", { name: "livePanelUnmute" });
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    expect(setPanelMuted).toHaveBeenCalledWith("browser-1", false);
  });

  it("blocks exposed borders and title gaps from reaching the workflow canvas", () => {
    const canvasPointer = vi.fn();
    renderPanels(<div onPointerDown={canvasPointer}><LivePanels /></div>);
    show();

    expect(shell().className).toContain("pointer-events-auto");
    fireEvent.pointerDown(shell());
    // 手柄热区有一半伸在卡片外,同样不能把按下漏给画布。
    fireEvent.pointerDown(handle("e"), { clientX: 0, clientY: 0 });
    fireEvent.pointerUp(window);
    expect(canvasPointer).not.toHaveBeenCalled();
  });
});

describe("LivePanels resize handles", () => {
  it("keeps the title bar to move / mute / close — resizing lives on the card's edges", () => {
    renderPanels(<LivePanels />);
    show();

    const titleButtons = within(shell()).getAllByRole("button").map((button) => button.getAttribute("aria-label"));
    expect(titleButtons).toEqual(["livePanelUnmute", "close"]);
    expect(shell().querySelector("[data-resize-handle]")).toBeNull();
  });

  it("puts a named, focusable handle on each corner and a cursor-only drag zone on each edge", () => {
    renderPanels(<LivePanels />);
    show();

    for (const [corner, label] of [
      ["nw", "livePanelResizeTopLeft"],
      ["ne", "livePanelResizeTopRight"],
      ["sw", "livePanelResizeBottomLeft"],
      ["se", "livePanelResizeBottomRight"],
    ] as const) {
      expect(screen.getByRole("button", { name: label })).toBe(handle(corner));
    }
    expect(handle("se").style.cursor).toBe("nwse-resize");
    expect(handle("ne").style.cursor).toBe("nesw-resize");
    for (const [edge, cursor] of [["n", "ns-resize"], ["s", "ns-resize"], ["e", "ew-resize"], ["w", "ew-resize"]] as const) {
      expect(handle(edge).getAttribute("aria-hidden")).toBe("true");
      expect(handle(edge).style.cursor).toBe(cursor);
    }
    // 热区骑在卡片边沿上:一半在卡片那圈边里,一半伸到卡片外 —— 不侵入网页区域。
    expect(handle("e").style.left).toBe(`${CARD.x + CARD.width - 4}px`);
    expect(handle("e").style.width).toBe("8px");
    expect(handle("se").style.left).toBe(`${CARD.x + CARD.width - 8}px`);
    expect(handle("se").style.top).toBe(`${CARD.y + CARD.height - 8}px`);
  });

  it("shows the handles while the pointer is on the card and fades them after it leaves", () => {
    vi.useFakeTimers();
    renderPanels(<LivePanels />);
    show();
    expect(handlesLayer().dataset.visible).toBe("false");

    fireEvent.pointerEnter(shell());
    expect(handlesLayer().dataset.visible).toBe("true");

    fireEvent.pointerLeave(shell());
    // 指针从卡片边沿进到网页上时,两路悬停信号会短暂都为假 —— 不能立刻收。
    expect(handlesLayer().dataset.visible).toBe("true");
    act(() => vi.advanceTimersByTime(300));
    expect(handlesLayer().dataset.visible).toBe("false");
  });

  it("shows the handles while the main process reports the pointer over the web page", () => {
    vi.useFakeTimers();
    renderPanels(<LivePanels />);
    show({ ...CARD, hovered: true });
    expect(handlesLayer().dataset.visible).toBe("true");

    show({ ...CARD, hovered: false });
    act(() => vi.advanceTimersByTime(300));
    expect(handlesLayer().dataset.visible).toBe("false");
  });

  it("keeps the handles up for the whole drag even when the pointer is elsewhere", () => {
    vi.useFakeTimers();
    renderPanels(<LivePanels />);
    show();

    fireEvent.pointerDown(handle("se"), { clientX: 100, clientY: 100 });
    act(() => vi.advanceTimersByTime(2000));
    expect(handlesLayer().dataset.visible).toBe("true");
    // 拖动期间光标恒为那个方向的样式。
    expect((document.querySelector('[style*="nwse-resize"][aria-hidden]') as HTMLElement).className).toContain("inset-0");

    fireEvent.pointerUp(window);
    act(() => vi.advanceTimersByTime(300));
    expect(handlesLayer().dataset.visible).toBe("false");
  });

  it.each([
    // 被拖的边跟着指针走,对边 / 对角不动(锚点、比例与上下限由主进程按这个矩形去定)。
    ["se", { x: 20, y: 20, width: 414, height: 285 }],
    ["nw", { x: 50, y: 40, width: 354, height: 245 }],
    ["ne", { x: 20, y: 40, width: 414, height: 245 }],
    ["sw", { x: 50, y: 20, width: 354, height: 285 }],
    ["n", { x: 20, y: 40, width: 384, height: 245 }],
    ["s", { x: 20, y: 20, width: 384, height: 285 }],
    ["e", { x: 20, y: 20, width: 414, height: 265 }],
    ["w", { x: 50, y: 20, width: 354, height: 265 }],
  ] as const)("dragging %s sends the rectangle the pointer asks for", (name, rect) => {
    renderPanels(<LivePanels />);
    show();

    fireEvent.pointerDown(handle(name), { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 130, clientY: 120 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ handle: name, ...rect });

    fireEvent.pointerUp(window);
    fireEvent.pointerMove(window, { clientX: 200, clientY: 200 });
    expect(setPanelLayout).toHaveBeenCalledTimes(1);
  });

  it("dragging a top corner or the top edge only resizes — it never also drags the title bar under it", () => {
    renderPanels(<LivePanels />);
    show();

    for (const name of ["nw", "n", "ne"] as const) {
      // 这三个热区压在标题条上方:必须画在卡片外壳之后(盖在上面),也不能是标题条的后代(冒泡上去)。
      expect(shell().compareDocumentPosition(handle(name)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(shell().contains(handle(name))).toBe(false);

      setPanelLayout.mockClear();
      fireEvent.pointerDown(handle(name), { clientX: 100, clientY: 100 });
      fireEvent.pointerMove(window, { clientX: 80, clientY: 70 });
      fireEvent.pointerMove(window, { clientX: 60, clientY: 40 });
      fireEvent.pointerUp(window);
      fireEvent.pointerMove(window, { clientX: 300, clientY: 300 });
      const changes = setPanelLayout.mock.calls.map(([change]) => change as Record<string, unknown>);
      expect(changes).toHaveLength(2);
      for (const change of changes) expect(change.handle).toBe(name);
    }
  });

  it("measures the drag from where it started, not from the previous move", () => {
    renderPanels(<LivePanels />);
    show();

    fireEvent.pointerDown(handle("e"), { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 150, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 140, clientY: 100 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ handle: "e", x: 20, y: 20, width: 424, height: 265 });
  });

  it("acts on the whole stack through its top card", () => {
    renderPanels(<LivePanels />);
    const lower = { ...CARD, id: "browser-0", y: 0 };
    const top = { ...CARD, id: "browser-1", y: 22 };
    show(lower, top);

    expect(handle("se").style.top).toBe(`${top.y + top.height - 8}px`);
    fireEvent.pointerDown(handle("s"), { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: 0, clientY: 10 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ handle: "s", x: 20, y: 22, width: 384, height: 275 });
  });

  it("still moves the stack from the title bar", () => {
    renderPanels(<LivePanels />);
    show();

    const title = shell().querySelector(".cursor-grab") as HTMLElement;
    fireEvent.pointerDown(title, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 70, clientY: 140 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ x: -10, y: 60 });
  });

  it("resizes from a focused corner with the arrow keys: outward grows, inward shrinks", () => {
    renderPanels(<LivePanels />);
    show();
    const ratio = CARD.height / CARD.width;

    fireEvent.keyDown(handle("se"), { key: "ArrowRight" });
    expect(setPanelLayout).toHaveBeenLastCalledWith({
      handle: "se", x: 20, y: 20, width: CARD.width + 16, height: CARD.height + 16 * ratio,
    });
    fireEvent.keyDown(handle("se"), { key: "ArrowUp" });
    expect(setPanelLayout).toHaveBeenLastCalledWith({
      handle: "se", x: 20, y: 20, width: CARD.width - 16, height: CARD.height - 16 * ratio,
    });
    // 左上角:往左上是朝外;Shift 走大步。右下角那一点不动。
    fireEvent.keyDown(handle("nw"), { key: "ArrowLeft", shiftKey: true });
    expect(setPanelLayout).toHaveBeenLastCalledWith({
      handle: "nw", x: 20 - 64, y: 20 - 64 * ratio, width: CARD.width + 64, height: CARD.height + 64 * ratio,
    });

    setPanelLayout.mockClear();
    fireEvent.keyDown(handle("nw"), { key: "Enter" });
    expect(setPanelLayout).not.toHaveBeenCalled();
  });
});


describe("LivePanels 标题:属于哪个工作流的哪次运行", () => {
  it("工作流运行开的浏览器:标题写工作流名和运行开始时间,点它跳到那次运行", async () => {
    sessions.getBrowserSession.mockResolvedValue({
      id: "browser-1",
      run: { job_id: "job-9", workflow_id: "wf-3", workflow_name: "爆款拆解", started_at: "2026-10-04T06:32:00" },
    });
    const opened: string[] = [];
    const listen = (event: Event) => opened.push((event as CustomEvent<string>).detail);
    window.addEventListener("mosael:open-workflow-run", listen);
    const { container } = renderPanels(<LivePanels />);
    show();

    const title = await within(shell()).findByRole("button", { name: /爆款拆解/ });
    // 后端时间是 UTC:按本地时区显示「月-日 时:分」
    const at = new Date("2026-10-04T06:32:00Z");
    const pad = (n: number) => String(n).padStart(2, "0");
    expect(title.textContent).toBe(`爆款拆解 · ${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`);
    expect(await readHint(title)).toBe("livePanelOpenRun");
    expect(sessions.getBrowserSession).toHaveBeenCalledWith("browser-1");

    // 按在标题上是要跳过去,不是拖:不进入拖动(拖动时全屏垫一层 grabbing 光标的遮罩)
    const dragging = () => container.querySelector('[style*="cursor: grabbing"]');
    fireEvent.pointerDown(title, { clientX: 0, clientY: 0 });
    expect(dragging()).toBeNull();
    fireEvent.pointerUp(window);

    fireEvent.click(title);
    expect(window.location.hash).toBe("#/workflows");
    expect(opened).toEqual(["wf-3/job-9"]);
    window.removeEventListener("mosael:open-workflow-run", listen);
  });

  it("不是会话的卡片(发布账号):照旧显示执行器报来的步骤名,没有可点的标题", async () => {
    renderPanels(<LivePanels />);
    show();
    await waitFor(() => expect(sessions.getBrowserSession).toHaveBeenCalledWith("browser-1"));
    const titleButtons = within(shell()).getAllByRole("button").map((button) => button.getAttribute("aria-label"));
    expect(titleButtons).toEqual(["livePanelUnmute", "close"]);
  });
});

describe("LivePanels page count", () => {
  it("marks a session with several pages as current/total on the title bar, and nothing when there is one page", async () => {
    renderPanels(<LivePanels />);
    show();
    expect(shell().querySelector("[data-live-panel-pages]")).toBeNull();
    show({ ...CARD, pages: 3, page: 2 });
    const badge = shell().querySelector("[data-live-panel-pages]") as HTMLElement;
    expect(badge.textContent).toBe("2/3");
    // 徽标不是能聚焦的控件:像用户那样把指针停上去读说明。
    expect(await hoverHint(badge)).toBe("livePanelPages");
  });
});
