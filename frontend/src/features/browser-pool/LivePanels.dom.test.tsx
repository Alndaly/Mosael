// @vitest-environment jsdom
import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { LivePanels } from "./LivePanels";

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
};

let publishPanels: ((cards: LivePanelCard[]) => void) | null;
const setPanelMuted = vi.fn(async () => undefined);
const setPanelLayout = vi.fn(async (_change: unknown) => undefined);

beforeEach(() => {
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
    render(<LivePanels />);
    show();

    const button = screen.getByRole("button", { name: "livePanelUnmute" });
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    expect(setPanelMuted).toHaveBeenCalledWith("browser-1", false);
  });

  it("blocks exposed borders and title gaps from reaching the workflow canvas", () => {
    const canvasPointer = vi.fn();
    render(<div onPointerDown={canvasPointer}><LivePanels /></div>);
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
    render(<LivePanels />);
    show();

    const titleButtons = within(shell()).getAllByRole("button").map((button) => button.getAttribute("aria-label"));
    expect(titleButtons).toEqual(["livePanelUnmute", "close"]);
    expect(shell().querySelector("[data-resize-handle]")).toBeNull();
  });

  it("puts a named, focusable handle on each corner and a cursor-only drag zone on each edge", () => {
    render(<LivePanels />);
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
    render(<LivePanels />);
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
    render(<LivePanels />);
    show({ ...CARD, hovered: true });
    expect(handlesLayer().dataset.visible).toBe("true");

    show({ ...CARD, hovered: false });
    act(() => vi.advanceTimersByTime(300));
    expect(handlesLayer().dataset.visible).toBe("false");
  });

  it("keeps the handles up for the whole drag even when the pointer is elsewhere", () => {
    vi.useFakeTimers();
    render(<LivePanels />);
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
    render(<LivePanels />);
    show();

    fireEvent.pointerDown(handle(name), { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 130, clientY: 120 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ handle: name, ...rect });

    fireEvent.pointerUp(window);
    fireEvent.pointerMove(window, { clientX: 200, clientY: 200 });
    expect(setPanelLayout).toHaveBeenCalledTimes(1);
  });

  it("measures the drag from where it started, not from the previous move", () => {
    render(<LivePanels />);
    show();

    fireEvent.pointerDown(handle("e"), { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 150, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 140, clientY: 100 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ handle: "e", x: 20, y: 20, width: 424, height: 265 });
  });

  it("acts on the whole stack through its top card", () => {
    render(<LivePanels />);
    const lower = { ...CARD, id: "browser-0", y: 0 };
    const top = { ...CARD, id: "browser-1", y: 22 };
    show(lower, top);

    expect(handle("se").style.top).toBe(`${top.y + top.height - 8}px`);
    fireEvent.pointerDown(handle("s"), { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: 0, clientY: 10 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ handle: "s", x: 20, y: 22, width: 384, height: 275 });
  });

  it("still moves the stack from the title bar", () => {
    render(<LivePanels />);
    show();

    const title = shell().querySelector(".cursor-grab") as HTMLElement;
    fireEvent.pointerDown(title, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 70, clientY: 140 });
    expect(setPanelLayout).toHaveBeenLastCalledWith({ x: -10, y: 60 });
  });

  it("resizes from a focused corner with the arrow keys: outward grows, inward shrinks", () => {
    render(<LivePanels />);
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
