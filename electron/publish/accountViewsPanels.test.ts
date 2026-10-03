/**
 * AccountViewManager 的悬浮面板编排,真跑管理器,只把 Electron 换成记账的假货 —— 视图的 bounds、
 * 窗口里的子视图次序、下发给渲染层的卡片矩形就是要验的东西。几何改动走的是和 main.cjs 同一条路:
 * 渲染层的载荷先过 ipc-contract 的 parsePanelLayout,再交给 setPanelLayout。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void;
  class Emitter {
    private handlers = new Map<string, Handler[]>();
    on(event: string, handler: Handler) {
      this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
      return this;
    }
    emit(event: string, ...args: unknown[]) {
      for (const handler of this.handlers.get(event) ?? []) handler(...args);
    }
  }
  class WebContents extends Emitter {
    zoom = 1;
    muted = false;
    destroyed = false;
    navigationHistory = { canGoBack: () => false, canGoForward: () => false };
    debugger = { isAttached: () => false };
    mainFrame = { routingId: 1, framesInSubtree: [], executeJavaScript: async () => undefined };
    getUserAgent() {
      return "Mozilla/5.0 Electron/44.4.5";
    }
    setUserAgent() {}
    setAudioMuted(muted: boolean) {
      this.muted = muted;
    }
    isAudioMuted() {
      return this.muted;
    }
    setWindowOpenHandler() {}
    isDestroyed() {
      return this.destroyed;
    }
    getZoomFactor() {
      return this.zoom;
    }
    setZoomFactor(zoom: number) {
      this.zoom = zoom;
    }
    getURL() {
      return "";
    }
    isLoading() {
      return false;
    }
    close() {
      this.destroyed = true;
      this.emit("destroyed");
    }
  }
  class WebContentsView {
    webContents = new WebContents();
    bounds = { x: 0, y: 0, width: 0, height: 0 };
    setBounds(bounds: { x: number; y: number; width: number; height: number }) {
      this.bounds = bounds;
    }
    getBounds() {
      return this.bounds;
    }
    setBackgroundColor() {}
  }
  class Window extends Emitter {
    size: [number, number] = [1440, 900];
    /** 子视图,按 z 序从下到上(和 Electron 的 contentView.children 一样)。 */
    children: WebContentsView[] = [];
    contentView = (() => {
      const window = this;
      return {
        get children() {
          return window.children;
        },
        addChildView(view: WebContentsView) {
          // 再加一次同一个视图 = 把它挪到最上面(Electron View API 的语义)。
          window.children = [...window.children.filter((child) => child !== view), view];
        },
        removeChildView(view: WebContentsView) {
          window.children = window.children.filter((child) => child !== view);
        },
      };
    })();
    getContentSize() {
      return this.size;
    }
    /** 用户拖窗口边改大小:尺寸变了再发 resize(Electron 的顺序)。 */
    resizeTo(width: number, height: number) {
      this.size = [width, height];
      this.emit("resize");
    }
    getContentBounds() {
      return { x: 0, y: 0, width: this.size[0], height: this.size[1] };
    }
    isDestroyed() {
      return false;
    }
  }
  return { WebContentsView, Window, userData: "" };
});

vi.mock("electron", () => ({
  app: { getPath: () => fake.userData },
  screen: { getCursorScreenPoint: () => ({ x: -1, y: -1 }) },
  session: { fromPartition: () => ({}) },
  WebContentsView: fake.WebContentsView,
}));

const { AccountViewManager } = await import("./accountViews");
const { panelHeightFor } = await import("./panelGeometry");
// main.cjs 就是这么接的:ipcMain.handle(publishPanelLayout, (_e, p) => setPanelLayout(parsePanelLayout(p)))。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { parsePanelLayout } = require("../ipc-contract.cjs") as { parsePanelLayout: (value: unknown) => never };
type PanelCard = import("./accountViews").PanelCard;
type FakeView = InstanceType<typeof fake.WebContentsView>;

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const intersects = (a: Rect, b: Rect) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

let window: InstanceType<typeof fake.Window>;
let manager: InstanceType<typeof AccountViewManager>;
let cards: PanelCard[];

function viewOf(id: string): FakeView {
  return (manager as unknown as { views: Map<string, FakeView> }).views.get(id)!;
}

function attach(...ids: string[]) {
  for (const id of ids) {
    manager.registerSession(id, `ephemeral-${id}`);
    expect(manager.panelAttach(id)).toBe(true);
  }
}

beforeEach(() => {
  fake.userData = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-panels-"));
  window = new fake.Window();
  cards = [];
  manager = new AccountViewManager(() => undefined, (next) => {
    cards = next;
  });
  manager.attachWindow(window as never, () => null);
});

afterEach(() => {
  manager.destroyAll();
  fs.rmSync(fake.userData, { recursive: true, force: true });
});

type Handle = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

const topCard = (): Rect => {
  const { x, y, width, height } = cards[cards.length - 1];
  return { x, y, width, height };
};

/** 渲染层(PanelResizeHandles)送的东西:按下时冻结的卡片 + 指针位移 → 指针要的矩形。 */
function requested(handle: Handle, from: Rect, dx: number, dy: number): Rect {
  const rect = { ...from };
  if (handle.includes("w")) {
    rect.x += dx;
    rect.width -= dx;
  }
  if (handle.includes("e")) rect.width += dx;
  if (handle.includes("n")) {
    rect.y += dy;
    rect.height -= dy;
  }
  if (handle.includes("s")) rect.height += dy;
  return rect;
}

/** 拖一个手柄,分几步走,每步都按 main.cjs 的路径(解析 → setPanelLayout)送一次。 */
function drag(handle: Handle, dx: number, dy: number): Rect[] {
  const from = topCard();
  const trail = [from];
  for (let step = 1; step <= 4; step += 1) {
    manager.setPanelLayout(parsePanelLayout({ handle, ...requested(handle, from, (dx * step) / 4, (dy * step) / 4) }));
    trail.push(topCard());
  }
  return trail;
}

/** 这个手柄拖动时不该动的那个点:对角,或对边的中点。 */
function anchorOf(handle: Handle, rect: Rect): [number, number] {
  const fx = handle.includes("w") ? 1 : handle.includes("e") ? 0 : 0.5;
  const fy = handle.includes("n") ? 1 : handle.includes("s") ? 0 : 0.5;
  return [rect.x + fx * rect.width, rect.y + fy * rect.height];
}

const OUTWARD: Record<Handle, [number, number]> = {
  nw: [-60, -40], n: [0, -40], ne: [60, -40], e: [60, 0], se: [60, 40], s: [0, 40], sw: [-60, 40], w: [-60, 0],
};

describe("resizing a panel from its handles", () => {
  const HANDLES = Object.keys(OUTWARD) as Handle[];

  it.each(HANDLES)("%s only resizes: the opposite corner / edge midpoint never moves, at any step", (handle) => {
    attach("a");
    manager.setPanelLayout(parsePanelLayout({ x: 400, y: 250 }));
    const [dx, dy] = OUTWARD[handle];
    for (const direction of [1, -1]) {
      const trail = drag(handle, dx * direction, dy * direction);
      const [ax, ay] = anchorOf(handle, trail[0]);
      for (const rect of trail.slice(1)) {
        const [x, y] = anchorOf(handle, rect);
        expect(Math.abs(x - ax), `${handle} ${JSON.stringify(rect)}`).toBeLessThanOrEqual(0.5);
        expect(Math.abs(y - ay), `${handle} ${JSON.stringify(rect)}`).toBeLessThanOrEqual(0.5);
      }
      expect(trail.at(-1)!.width).not.toBe(trail[0].width);
    }
  });

  it.each(HANDLES)("%s does not slide the panel when it sits in the default bottom-right corner", (handle) => {
    attach("a");
    // 默认贴右下角,离窗口边只有 16px:往外拖很快撞边。撞边时尺寸停下,锚点照样不动。
    const trail = drag(handle, ...OUTWARD[handle]);
    const [ax, ay] = anchorOf(handle, trail[0]);
    for (const rect of trail.slice(1)) {
      const [x, y] = anchorOf(handle, rect);
      expect(Math.abs(x - ax), `${handle} ${JSON.stringify(rect)}`).toBeLessThanOrEqual(0.5);
      expect(Math.abs(y - ay), `${handle} ${JSON.stringify(rect)}`).toBeLessThanOrEqual(0.5);
    }
  });
});

describe("stacked panels", () => {
  it("keeps every page clear of the top card's title bar, rim and resize handles", () => {
    attach("a", "b", "c");
    const top = cards[cards.length - 1];
    expect(top.id).toBe("c");

    // 最上面那张卡片的网页区域:标题条以下、四周让出内缩边。它以外的部分(标题条、那圈边、
    // 伸出卡片的手柄热区)都是渲染层要收指针的地方,任何一块原生视图都不许压上去。
    const content = viewOf("c").getBounds();
    const chrome: Rect[] = [
      { x: top.x - 10, y: top.y - 10, width: top.width + 20, height: top.header + 10 },
      { x: top.x - 10, y: top.y, width: 10 + (content.x - top.x), height: top.height + 10 },
      { x: content.x + content.width, y: top.y, width: top.x + top.width + 10 - (content.x + content.width), height: top.height + 10 },
      { x: top.x - 10, y: content.y + content.height, width: top.width + 20, height: top.y + top.height + 10 - (content.y + content.height) },
    ];
    for (const id of ["a", "b", "c"]) {
      for (const region of chrome) expect(intersects(viewOf(id).getBounds(), region), `${id} over ${JSON.stringify(region)}`).toBe(false);
    }
  });

  it("still shows the lower cards' title bars peeking above the top one", () => {
    attach("a", "b", "c");
    const [a, b, c] = cards;
    expect(c.y - b.y).toBeGreaterThan(0);
    expect(b.y - a.y).toBeGreaterThan(0);
    // 下层卡片露出来的那截标题条上也没有任何原生视图(关闭按钮在那儿)。
    for (const lower of [a, b]) {
      const peek = { x: lower.x, y: lower.y, width: lower.width, height: Math.min(lower.header, c.y - lower.y) };
      for (const id of ["a", "b", "c"]) expect(intersects(viewOf(id).getBounds(), peek)).toBe(false);
    }
  });

  it("keeps lower pages fully laid out at the panel size, just covered by the top one", () => {
    attach("a", "b");
    // 被压在下面的页面照样挂着、照样是同样大小的视口(可信输入要靠它),只是看不见。
    expect(viewOf("a").getBounds()).toEqual(viewOf("b").getBounds());
    expect(window.children).toEqual([viewOf("a"), viewOf("b")]);
  });

  it("puts a panel brought back from the full view on top of the stack, page and card alike", () => {
    attach("a", "b");
    manager.show("a");
    manager.hide();

    expect(cards.map((card) => card.id)).toEqual(["b", "a"]);
    expect(window.children.at(-1)).toBe(viewOf("a"));
  });
});

describe("window resizing", () => {
  const layoutFile = () => path.join(fake.userData, "panel-layout.json");

  it("pulls the panel back inside a shrunken window with the usual limits, and remembers it", () => {
    attach("a");
    manager.setPanelLayout(parsePanelLayout({ handle: "nw", x: 560, y: 300, width: 624, height: 484 }));
    expect(topCard().x + topCard().width).toBe(1184);

    window.resizeTo(800, 600);
    const card = topCard();
    // 800×600:宽上限 min(800−32, 800×0.6) = 480,高上限 min(600−56−16, 600×0.6) = 360 → 折成宽 536。
    expect(card.width).toBe(480);
    expect(card.height).toBe(panelHeightFor(480));
    expect(card.x + card.width).toBeLessThanOrEqual(800);
    expect(card.y).toBeGreaterThanOrEqual(56);
    expect(card.y + card.height).toBeLessThanOrEqual(600);
    // 网页跟着卡片走,缩放跟着宽走(布局视口仍是 1280 宽)。
    expect(viewOf("a").getBounds()).toEqual({ x: card.x + 4, y: card.y + 26, width: card.width - 8, height: card.height - 30 });
    expect(viewOf("a").webContents.zoom).toBeCloseTo((card.width - 8) / 1280);
    expect(JSON.parse(fs.readFileSync(layoutFile(), "utf8"))).toEqual({ x: card.x, y: card.y, width: card.width });
  });

  it("shrinks a never-moved panel in place and keeps it tucked into the bottom-right corner", () => {
    attach("a");
    window.resizeTo(500, 400);
    const card = topCard();
    // 500×400:宽上限 min(468, 300) = 300。
    expect(card.width).toBe(300);
    expect(card).toEqual({ x: 500 - 300 - 16, y: 400 - panelHeightFor(300) - 16, width: 300, height: panelHeightFor(300) });
    expect(JSON.parse(fs.readFileSync(layoutFile(), "utf8"))).toEqual({ x: null, y: null, width: 300 });
  });

  it("leaves a panel that still fits alone and does not rewrite the file", () => {
    attach("a");
    manager.setPanelLayout(parsePanelLayout({ x: 100, y: 100 }));
    const before = topCard();
    fs.rmSync(layoutFile());

    window.resizeTo(1600, 1000);
    window.resizeTo(1000, 700);
    expect(topCard()).toEqual(before);
    expect(fs.existsSync(layoutFile())).toBe(false);
  });
});
