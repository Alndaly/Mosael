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
