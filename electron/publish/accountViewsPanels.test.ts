/**
 * AccountViewManager 的悬浮面板编排,真跑管理器,只把 Electron 换成记账的假货 —— 视图的 bounds、
 * 窗口里的子视图次序、下发给渲染层的卡片矩形就是要验的东西。几何改动走的是和 main.cjs 同一条路:
 * 渲染层的载荷先过 ipc-contract 的 parsePanelLayout,再交给 setPanelLayout。
 */
import { EventEmitter } from "node:events";
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
    once(event: string, handler: Handler) {
      return this.on(event, handler);
    }
    emit(event: string, ...args: unknown[]) {
      for (const handler of this.handlers.get(event) ?? []) handler(...args);
    }
  }
  let nextContentsId = 1;
  class WebContents extends Emitter {
    id = nextContentsId++;
    zoom = 1;
    muted = false;
    destroyed = false;
    /**
     * 媒体记录器按会话挂 webRequest 观察钩子(见 mediaRecorder);下载路由在会话上接 will-download
     * (见 downloads.ts)。这里只记下挂了什么。
     */
    session = new (class extends Emitter {
      webRequest = { onResponseStarted: () => undefined };
    })();
    navigationHistory = { canGoBack: () => false, canGoForward: () => false };
    debugger = { isAttached: () => false };
    mainFrame = { routingId: 1, framesInSubtree: [] as unknown[], executeJavaScript: async (_code?: string): Promise<unknown> => undefined };
    /** 系统焦点在不在这个网页上(webContents.focus())。 */
    focused = false;
    focus() {
      this.focused = true;
    }
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
    /** 页面要开新窗口时 Electron 会问它(见 accountViews.openWindow)。 */
    openHandler: ((details: { url: string; disposition: string }) => unknown) | null = null;
    setWindowOpenHandler(handler: (details: { url: string; disposition: string }) => unknown) {
      this.openHandler = handler;
    }
    url = "";
    title = "";
    loadURL(url: string) {
      this.url = url;
      return Promise.resolve();
    }
    isWaitingForResponse() {
      return false;
    }
    /** 挂上之后等页面排好版用:这里总是已经排好了。 */
    executeJavaScript() {
      return Promise.resolve(1280);
    }
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
      return this.url;
    }
    getTitle() {
      return this.title;
    }
    isLoading() {
      return false;
    }
    /** 页面当前的画面(页面列表临时展开时铺在原处的那张)。 */
    capturePage() {
      return Promise.resolve({ isEmpty: () => false, toJPEG: () => Buffer.from("frame") });
    }
    close() {
      this.destroyed = true;
      this.emit("destroyed");
    }
  }
  class WebContentsView {
    webContents: WebContents;
    /** 新窗口收进来时,Electron 把它为 window.open 建好的那个 WebContents 交给视图收养。 */
    constructor(options?: { webContents?: WebContents }) {
      this.webContents = options?.webContents ?? new WebContents();
    }
    bounds = { x: 0, y: 0, width: 0, height: 0 };
    visible = true;
    setVisible(visible: boolean) {
      this.visible = visible;
    }
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
    /** 主窗口自己的网页(Mosael 的界面)。 */
    webContents = { focused: false, focus() { this.focused = true; }, isDestroyed: () => false, on: () => undefined };
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
  return { WebContentsView, WebContents, Window, userData: "" };
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

/**
 * 页面开新窗口:按 Electron 的顺序走一遍 —— 先问 setWindowOpenHandler 的处理器,放行的话调它给的
 * createWindow,把 Chromium 为这个 window.open 建好的 WebContents 交进去。返回新页面(放行了的话)。
 */
function openWindow(opener: FakeView, url: string, disposition = "foreground-tab") {
  const answer = opener.webContents.openHandler!({ url, disposition }) as {
    action: string;
    outlivesOpener?: boolean;
    createWindow?: (options: unknown) => InstanceType<typeof fake.WebContents>;
  };
  if (answer.action !== "allow") return null;
  // 列表里的页面是平级的:关掉开它的那一页,它照样留着(Electron 默认会跟着 opener 一起关)。
  expect(answer.outlivesOpener).toBe(true);
  const guest = new fake.WebContents();
  guest.url = url;
  const returned = answer.createWindow!({ webContents: guest, webPreferences: {} });
  expect(returned).toBe(guest); // createWindow 必须交回收养的那一个
  return guest;
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

describe("keyboard focus between Mosael and the embedded page", () => {
  const escape = (view: FakeView) => view.webContents.emit("before-input-event", {}, { type: "keyDown", key: "Escape" });

  it("entering the embedded browser puts the keyboard in the page; going back puts it in Mosael", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    expect(viewOf("pool-a").webContents.focused).toBe(true);
    manager.hide();
    expect(window.webContents.focused).toBe(true);
  });

  it("switching to another page of the shown session puts the keyboard in that page", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    openWindow(viewOf("pool-a"), "https://example.com/next");
    const firstId = manager.pagesOf("pool-a")[0].id;
    manager.switchVisiblePage(firstId);
    expect(viewOf("pool-a").webContents.focused).toBe(true);
  });

  it("hands the keyboard back to the page on request (after a click in the toolbar or the page list)", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    viewOf("pool-a").webContents.focused = false;
    manager.focusForeground();
    expect(viewOf("pool-a").webContents.focused).toBe(true);
  });

  it("remembers which page had the keyboard last (the float layer hands focus back to it)", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    expect(manager.focusTarget()).toBe(window.webContents);
    viewOf("pool-a").webContents.emit("focus");
    expect(manager.focusTarget()).toBe(viewOf("pool-a").webContents);
  });

  it("Esc twice leaves the embedded browser — but not while typing in the page (the page gets both)", async () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    const page = viewOf("pool-a");
    page.webContents.mainFrame.executeJavaScript = async () => true; // 焦点在网页的输入框里
    escape(page);
    escape(page);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(manager.foreground()).not.toBeNull();
    page.webContents.mainFrame.executeJavaScript = async () => false;
    escape(page);
    escape(page);
    await vi.waitFor(() => expect(manager.foreground()).toBeNull());
  });
});

describe("the foreground view and the toolbar's page tools", () => {
  const HEADER = 56;

  it("hands the page tools only the foreground view, together with its partition", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    attach("rpa-b");
    expect(manager.foreground()).toBeNull();
    manager.show("pool-a");
    expect(manager.foreground()).toMatchObject({ id: "pool-a", partition: "persist:pool-a" });
    manager.hide();
    expect(manager.foreground()).toBeNull();
  });

  it("makes room on the right for the tools drawer, never more than half the window, and gives it back", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    manager.setShellInset(360);
    expect(viewOf("pool-a").bounds).toEqual({ x: 0, y: HEADER, width: 1440 - 360, height: 900 - HEADER });
    manager.setShellInset(5000);
    expect(viewOf("pool-a").bounds.width).toBe(720);
    // 收起再亮出来:上一回的侧栏不该还占着位置。
    manager.hide();
    manager.show("pool-a");
    expect(viewOf("pool-a").bounds.width).toBe(1440);
  });

  it("follows the workbench column while it's dragged wider or narrower: every new inset re-lays the page at once", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    // 拖着右边那一列:渲染层每一帧报一次(拖动时多让出一截安全边,见 workbench/columnWidth)
    for (const right of [420, 437, 512, 640, 300]) {
      manager.setShellInset(right);
      expect(viewOf("pool-a").bounds).toEqual({ x: 0, y: HEADER, width: 1440 - right, height: 900 - HEADER });
    }
    manager.setShellInset(300.6);
    expect(viewOf("pool-a").bounds.width, "按整像素让").toBe(1440 - 301);
  });

  it("steps the page out of the window while a Mosael overlay (the image viewer) is up, and puts it back where it was", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    manager.setShellInset(420);
    const placed = { x: 0, y: HEADER, width: 1440 - 420, height: 900 - HEADER };
    expect(viewOf("pool-a").bounds).toEqual(placed);
    manager.setForegroundHidden("overlay", true);
    const page = viewOf("pool-a");
    // 挪到窗口外、照常出帧(不是藏起来):关掉大图时回来的就是它此刻的样子
    expect(page.visible).toBe(true);
    expect(page.bounds.x + page.bounds.width).toBeLessThanOrEqual(0);
    // 大图开着时列宽变了:人还在窗口外,宽度跟着变
    manager.setShellInset(500);
    expect(page.bounds.width).toBe(1440 - 500);
    expect(page.bounds.x + page.bounds.width).toBeLessThanOrEqual(0);
    // 页面列表的 cover 和大图的 overlay 各管各的:一件收了,另一件还要它让开就接着让
    manager.setForegroundHidden("cover", true);
    manager.setForegroundHidden("overlay", false);
    expect(page.bounds.x + page.bounds.width).toBeLessThanOrEqual(0);
    manager.setForegroundHidden("cover", false);
    expect(page.bounds).toEqual({ ...placed, width: 1440 - 500 });
  });

  it("hides the page while a region is picked, and never leaves the next foreground view hidden", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.registerSession("pool-b", "persist:pool-b");
    manager.show("pool-a");
    manager.setForegroundHidden("region", true);
    expect(viewOf("pool-a").visible).toBe(false);
    manager.show("pool-b");
    expect(viewOf("pool-a").visible).toBe(true);
    expect(viewOf("pool-b").visible).toBe(true);
  });

  it("snapshots the page as shown and where it's shown, for the page list to lay over while it moves", async () => {
    manager.registerSession("pool-a", "persist:pool-a");
    expect(await manager.snapshotForeground()).toBeNull();
    manager.show("pool-a");
    manager.setPagesInset(48);
    const shown = { x: 48, y: HEADER, width: 1440 - 48, height: 900 - HEADER };
    expect(await manager.snapshotForeground()).toEqual({
      frame: `data:image/jpeg;base64,${Buffer.from("frame").toString("base64")}`,
      bounds: shown,
    });
    // 已经盖着(视图挪开了)再拍:说的还是网页在窗口里该在的位置。
    manager.setForegroundHidden("cover", true);
    expect((await manager.snapshotForeground())?.bounds).toEqual(shown);
  });

  it("moves the page out of the window while the page list covers it — still laid out, still drawing — and back where it belongs", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    manager.setPagesInset(220);
    manager.setForegroundHidden("cover", true);
    const page = viewOf("pool-a");
    // 不是藏起来(藏起来的视图不出帧,揭开时第一帧是旧的):照常显示,只是整块在窗口外面、大小不变。
    expect(page.visible).toBe(true);
    expect(page.bounds.x + page.bounds.width).toBeLessThanOrEqual(0);
    expect([page.bounds.y, page.bounds.width, page.bounds.height]).toEqual([HEADER, 1440 - 220, 900 - HEADER]);
    // 盖着的时候列表收起了:宽度跟着变,人还在窗口外。
    manager.setPagesInset(48);
    expect(page.bounds.width).toBe(1440 - 48);
    expect(page.bounds.x + page.bounds.width).toBeLessThanOrEqual(0);
    manager.setForegroundHidden("cover", false);
    expect(page.bounds).toEqual({ x: 48, y: HEADER, width: 1440 - 48, height: 900 - HEADER });
  });

  it("keeps the page out of sight while the cover or a region pick still needs it, the session's next page included", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    const offWindow = () => viewOf("pool-a").bounds.x + viewOf("pool-a").bounds.width <= 0;
    manager.setForegroundHidden("cover", true);
    manager.setForegroundHidden("region", true);
    manager.setForegroundHidden("cover", false);
    expect(viewOf("pool-a").visible).toBe(false);
    expect(offWindow()).toBe(false);
    manager.setForegroundHidden("region", false);
    expect(viewOf("pool-a").visible).toBe(true);
    // 临时展开的列表里切到了另一页:那一页也先在窗口外(列表还盖在画面上),揭开时才回来。
    manager.setForegroundHidden("cover", true);
    openWindow(viewOf("pool-a"), "https://example.com/next");
    expect(viewOf("pool-a").webContents.getURL()).toBe("https://example.com/next");
    expect(offWindow()).toBe(true);
    manager.setForegroundHidden("cover", false);
    expect(offWindow()).toBe(false);
    expect(viewOf("pool-a").visible).toBe(true);
  });

  it("reports the page title and the partition with the toolbar state", () => {
    const states: Array<Record<string, unknown>> = [];
    const reporting = new AccountViewManager((state) => states.push(state as never));
    reporting.attachWindow(window as never, () => null);
    reporting.registerSession("pool-a", "persist:pool-a");
    reporting.show("pool-a");
    expect(states.at(-1)).toMatchObject({ visible: true, accountId: "pool-a", partition: "persist:pool-a", title: "" });
    reporting.destroyAll();
  });
});

describe("downloads in the embedded pages", () => {
  /** 一份刚开始的下载(和 Electron 的 DownloadItem 同样的几个方法)。 */
  function download(name: string) {
    return Object.assign(new EventEmitter(), {
      savePath: "",
      getFilename: () => name,
      getTotalBytes: () => 3,
      getReceivedBytes: () => 3,
      getURL: () => `https://example.com/${name}`,
      setSavePath(target: string) {
        this.savePath = target;
      },
      cancel() {},
    });
  }

  it("takes over every view's downloads (no save dialog), the session's other pages included", async () => {
    const notices: Array<{ state: string; name: string }> = [];
    const own = new AccountViewManager(() => undefined, () => undefined, (notice) => notices.push(notice));
    own.attachWindow(window as never, () => null);
    own.registerSession("rpa-a", "ephemeral-rpa-a");
    const view = (own as unknown as { views: Map<string, FakeView> }).views.get("rpa-a")!;
    const session = view.webContents.session;

    // 执行器在这个会话上跑一步:这期间页面里开始的下载归这一步。
    const step = own.downloads.collect("rpa-a");
    const item = download("report.pdf");
    session.emit("will-download", {}, item, view.webContents);
    expect(item.savePath.startsWith(path.join(fake.userData, "web-downloads"))).toBe(true);

    // 页面用 window.open 开了一页(进了这个会话的页面列表),那一页里点的下载也算在这个会话头上。
    const opened = openWindow(view, "https://example.com/gallery");
    const fromPopup = download("cover.png");
    session.emit("will-download", {}, fromPopup, opened);

    fs.writeFileSync(item.savePath, "pdf");
    item.emit("done", {}, "completed");
    fs.writeFileSync(fromPopup.savePath, "png");
    fromPopup.emit("done", {}, "completed");
    const collected = await step.settle({ graceMs: 0 });
    expect(collected.map((one) => one.ok && one.file.name)).toEqual(["report.pdf", "cover.png"]);
    expect(notices).toEqual([]); // 自动化的下载不打扰人
    own.destroyAll();
  });
});

describe("several pages in one session (the page list)", () => {
  const HEADER = 56;
  const pageIds = (id: string) => manager.pagesOf(id).map((one) => one.id);

  it("a new window (target=_blank / window.open) joins the list right after its opener and becomes the current page", () => {
    const states: Array<Record<string, unknown>> = [];
    const own = new AccountViewManager((state) => states.push(state as never));
    own.attachWindow(window as never, () => null);
    own.registerSession("pool-a", "persist:pool-a");
    own.show("pool-a");
    const first = (own as unknown as { views: Map<string, FakeView> }).views.get("pool-a")!;
    first.webContents.url = "https://example.com/";

    const opened = openWindow(first, "https://accounts.google.com/signin")!;
    expect(own.pagesOf("pool-a").map((one) => [one.url, one.current])).toEqual([
      ["https://example.com/", false],
      ["https://accounts.google.com/signin", true],
    ]);
    // 不再弹独立小窗:新页面挂在窗口里原来那一页的位置,原来那一页摘下来在后台活着、静音。
    expect(window.children.some((child) => child.webContents === opened)).toBe(true);
    expect(window.children.includes(first)).toBe(false);
    expect(first.webContents.destroyed).toBe(false);
    expect(first.webContents.isAudioMuted()).toBe(true);
    expect(own.foreground()?.webContents).toBe(opened); // 顶栏工具作用在当前页上
    expect(states.at(-1)).toMatchObject({ pages: [{ current: false }, { current: true }], pageLimit: 10 });
    own.destroyAll();
  });

  it("refuses dangerous schemes; a background-tab joins the list without switching", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    const first = viewOf("pool-a");
    expect(openWindow(first, "javascript:alert(1)")).toBeNull();
    expect(openWindow(first, "file:///etc/passwd")).toBeNull();
    expect(pageIds("pool-a")).toHaveLength(1);
    const background = openWindow(first, "https://example.com/later", "background-tab")!;
    expect(manager.pagesOf("pool-a").map((one) => one.current)).toEqual([true, false]);
    expect(manager.foreground()?.webContents).toBe(first.webContents);
    expect(window.children.some((child) => child.webContents === background)).toBe(false);
  });

  it("switches, closes and reorders pages; closing the current page lands on the one above; the last page stays", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    const first = viewOf("pool-a");
    const second = openWindow(first, "https://example.com/2")!;
    const third = openWindow(viewOf("pool-a"), "https://example.com/3")!;
    const [a, b, c] = pageIds("pool-a");
    expect(manager.foreground()?.webContents).toBe(third);

    expect(manager.switchVisiblePage(a)).toBe(true);
    expect(manager.foreground()?.webContents).toBe(first.webContents);
    expect(manager.reorderVisiblePages([c, a, b])).toBe(true);
    expect(pageIds("pool-a")).toEqual([c, a, b]);
    expect(manager.reorderVisiblePages([c, a])).toBe(false);

    // 关掉当前页(a):落到它上面那一页(c)。
    expect(manager.closeVisiblePage(a)).toBe(true);
    expect(first.webContents.destroyed).toBe(true);
    expect(manager.foreground()?.webContents).toBe(third);
    // 页面自己 window.close() 也一样从列表里拿掉。
    second.close();
    expect(pageIds("pool-a")).toEqual([c]);
    // 只剩一页:不关(关掉整个浏览器走「返回」/「关闭浏览器」)。
    expect(manager.closeVisiblePage(c)).toBe(false);
    expect(third.destroyed).toBe(false);
  });

  it("caps the pages of one session, and tells the toolbar when a new one was refused", () => {
    const states: Array<{ pageLimitHitAt?: number; pages?: unknown[] }> = [];
    const own = new AccountViewManager((state) => states.push(state as never));
    own.attachWindow(window as never, () => null);
    own.registerSession("pool-a", "persist:pool-a");
    own.show("pool-a");
    const current = () => (own as unknown as { views: Map<string, FakeView> }).views.get("pool-a")!;
    for (let i = 1; i < 10; i += 1) expect(openWindow(current(), `https://example.com/${i}`)).not.toBeNull();
    expect(own.pagesOf("pool-a")).toHaveLength(10);
    expect(states.at(-1)?.pageLimitHitAt).toBe(0);
    expect(openWindow(current(), "https://example.com/11")).toBeNull();
    expect(own.newPage("example.com/12")).toBe(false);
    expect(own.pagesOf("pool-a")).toHaveLength(10);
    expect(states.at(-1)?.pageLimitHitAt).toBeGreaterThan(0);
    own.destroyAll();
  });

  it("new page from the list opens the address (same normalisation as the address bar) and becomes current", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    expect(manager.newPage("example.com/new")).toBe(true);
    const pages = manager.pagesOf("pool-a");
    expect(pages).toHaveLength(2);
    expect(pages[1]).toMatchObject({ url: "https://example.com/new", current: true });
  });

  it("an automation session in a panel follows its new page: the driver, the panel card (2/2) and the stacking", () => {
    attach("rpa-a", "rpa-b");
    const before = manager.getDriver("rpa-a");
    const opened = openWindow(viewOf("rpa-a"), "https://example.com/next")!;
    // 下一步自动化拿到的是新页面的驱动。
    expect(manager.getDriver("rpa-a")).not.toBe(before);
    expect(manager.pagesOf("rpa-a").find((page) => page.current)?.id).toBe(String(opened.id));
    const card = cards.find((one) => one.id === "rpa-a")!;
    expect([card.page, card.pages]).toEqual([2, 2]);
    // rpa-b 是最上面那张卡片:rpa-a 换了页,它的网页也不能盖到 rpa-b 上面。
    expect(window.children.at(-1)).toBe(viewOf("rpa-b"));
    expect(viewOf("rpa-a").bounds).toEqual(viewOf("rpa-b").bounds);
    // 切回第一页、按标题 / 网址 / 第几个找页面(「切换页面」节点用)。
    viewOf("rpa-a").webContents.title = "下一页";
    expect(manager.findPage("rpa-a", { title: "下一" })).toBe(manager.currentPageId("rpa-a"));
    const first = manager.findPage("rpa-a", { index: 1 })!;
    expect(manager.switchPage("rpa-a", first)).toBe(true);
    expect(manager.pagesOf("rpa-a").find((page) => page.current)?.id).not.toBe(String(opened.id));
    expect(manager.findPage("rpa-a", { url: "example.com/next" })).not.toBeNull();
    expect(manager.findPage("rpa-a", { url: "nowhere" })).toBeNull();
  });

  it("closing the session reclaims every page it opened", () => {
    attach("rpa-a");
    const first = viewOf("rpa-a").webContents;
    const second = openWindow(viewOf("rpa-a"), "https://example.com/2")!;
    const third = openWindow(viewOf("rpa-a"), "https://example.com/3", "background-tab")!;
    manager.destroy("rpa-a");
    expect([first.destroyed, second.destroyed, third.destroyed]).toEqual([true, true, true]);
    expect(manager.pagesOf("rpa-a")).toEqual([]);
    expect(window.children).toEqual([]);
  });

  it("makes room on the left for the page list, never more than a third of the window", () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    manager.setPagesInset(232);
    expect(viewOf("pool-a").bounds).toEqual({ x: 232, y: HEADER, width: 1440 - 232, height: 900 - HEADER });
    manager.setShellInset(360);
    expect(viewOf("pool-a").bounds).toEqual({ x: 232, y: HEADER, width: 1440 - 232 - 360, height: 900 - HEADER });
    manager.setPagesInset(5000);
    expect(viewOf("pool-a").bounds.x).toBe(480);
  });
});

describe("capturing a page that isn't on the window (the 5th session, a page in the background)", () => {
  const views = () => (manager as unknown as { views: Map<string, FakeView> }).views;
  const onWindow = (view: FakeView) => window.children.includes(view);
  /** 窗口里用户看得见的那一块:内容区 1440×900。 */
  const visibleToUser = (bounds: Rect) => intersects(bounds, { x: 0, y: 0, width: 1440, height: 900 });

  it("mounts a never-shown session page outside the window at a desktop layout size for the capture, then puts it back", async () => {
    attach("rpa-a", "rpa-b", "rpa-c", "rpa-d");
    manager.registerSession("rpa-e", "ephemeral-rpa-e");
    expect(manager.panelAttach("rpa-e")).toBe(false); // 面板满了:第 5 个没挂上
    const fifth = views().get("rpa-e")!;
    expect(onWindow(fifth)).toBe(false);
    const before = { bounds: { ...fifth.bounds }, zoom: fifth.webContents.getZoomFactor(), children: [...window.children] };

    let during: { onWindow: boolean; bounds: Rect; zoom: number; top: FakeView | undefined } | null = null;
    const value = await manager.withPageOnSurface("rpa-e", null, async (wc) => {
      expect(wc).toBe(fifth.webContents);
      during = { onWindow: onWindow(fifth), bounds: { ...fifth.bounds }, zoom: fifth.webContents.getZoomFactor(), top: window.children.at(-1) };
      return "shot";
    });
    expect(value).toBe("shot");
    // 截的时候:挂在窗口上(Chromium 才肯排版出帧),但整块在窗口外面 —— 用户看不见、不闪;按面板那样的
    // 桌面版布局宽度(CSS 视口 = 面板网页区 / 面板缩放)、缩放 1 出原清晰度的图。
    expect(during!.onWindow).toBe(true);
    expect(visibleToUser(during!.bounds)).toBe(false);
    expect(during!.zoom).toBe(1);
    const panelPage = viewOf("rpa-a").bounds;
    const panelZoom = viewOf("rpa-a").webContents.getZoomFactor();
    expect(during!.bounds.width).toBeCloseTo(panelPage.width / panelZoom, 0);
    expect(during!.bounds.height).toBeCloseTo(panelPage.height / panelZoom, 0);
    // 截完:原样摘下,大小、缩放、窗口里的子视图都回到截之前。
    expect(onWindow(fifth)).toBe(false);
    expect(fifth.bounds).toEqual(before.bounds);
    expect(fifth.webContents.getZoomFactor()).toBe(before.zoom);
    expect(window.children).toEqual(before.children);
  });

  it("mounts a page that sits in the background of the shown session at that session's layout size", async () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    manager.setPagesInset(220);
    const first = viewOf("pool-a");
    openWindow(first, "https://example.com/next"); // 新页面切到前台,第一页退到后台
    const firstId = manager.pagesOf("pool-a")[0].id;
    expect(onWindow(first)).toBe(false);
    const shown = viewOf("pool-a");

    await manager.withPageOnSurface("pool-a", firstId, async (wc) => {
      expect(wc).toBe(first.webContents);
      expect(onWindow(first)).toBe(true);
      expect(visibleToUser(first.bounds)).toBe(false);
      expect([first.bounds.width, first.bounds.height]).toEqual([shown.bounds.width, shown.bounds.height]);
    });
    expect(onWindow(first)).toBe(false);
    expect(onWindow(shown)).toBe(true);
    expect(manager.foreground()?.webContents).toBe(shown.webContents);
  });

  it("captures a page that's already on the window in place (no remounting)", async () => {
    attach("rpa-a");
    const view = viewOf("rpa-a");
    const before = { ...view.bounds };
    await manager.withPageOnSurface("rpa-a", null, async () => {
      expect(view.bounds).toEqual(before);
    });
    expect(onWindow(view)).toBe(true);
    expect(view.bounds).toEqual(before);
  });

  it("leaves a page on the window if it was switched to while being captured", async () => {
    manager.registerSession("pool-a", "persist:pool-a");
    manager.show("pool-a");
    const first = viewOf("pool-a");
    openWindow(first, "https://example.com/next");
    const firstId = manager.pagesOf("pool-a")[0].id;
    await manager.withPageOnSurface("pool-a", firstId, async () => {
      manager.switchVisiblePage(firstId); // 用户正好在这时点了它
    });
    expect(onWindow(first)).toBe(true);
    expect(visibleToUser(first.bounds)).toBe(true);
    expect(first.webContents.getZoomFactor()).toBe(1);
  });

  it("says so when the page is gone", async () => {
    attach("rpa-a");
    await expect(manager.withPageOnSurface("rpa-a", "999999", async () => "x")).rejects.toThrow(/page/);
    await expect(manager.withPageOnSurface("nope", null, async () => "x")).rejects.toThrow(/page/);
  });
});
