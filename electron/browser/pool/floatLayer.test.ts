/**
 * 浮层视图:一块透明的原生视图,专门用来把内嵌浏览器顶栏、页面列表里的悬停说明画在**原生网页视图上面**
 * (DOM 画不上去 —— 原生视图盖在一切 DOM 上)。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => {
  class WebContents {
    url = "";
    zoom = 1;
    destroyed = false;
    scripts: string[] = [];
    handlers = new Map<string, (...args: unknown[]) => void>();
    openHandler: (() => unknown) | null = null;
    loadURL(url: string) {
      this.url = url;
      return Promise.resolve();
    }
    executeJavaScript(code: string) {
      this.scripts.push(code);
      return Promise.resolve(true);
    }
    setZoomFactor(zoom: number) {
      this.zoom = zoom;
    }
    on(event: string, handler: (...args: unknown[]) => void) {
      this.handlers.set(event, handler);
    }
    setWindowOpenHandler(handler: () => unknown) {
      this.openHandler = handler;
    }
    isDestroyed() {
      return this.destroyed;
    }
    close() {
      this.destroyed = true;
    }
    focus = vi.fn();
  }
  class WebContentsView {
    static created: WebContentsView[] = [];
    webContents = new WebContents();
    options: unknown;
    background = "";
    bounds = { x: 0, y: 0, width: 0, height: 0 };
    visible = true;
    constructor(options: unknown) {
      this.options = options;
      WebContentsView.created.push(this);
    }
    setBackgroundColor(color: string) {
      this.background = color;
    }
    setBounds(bounds: { x: number; y: number; width: number; height: number }) {
      this.bounds = bounds;
    }
    getBounds() {
      return this.bounds;
    }
    setVisible(visible: boolean) {
      this.visible = visible;
    }
  }
  return { WebContentsView };
});

vi.mock("electron", () => ({ WebContentsView: fake.WebContentsView }));

const { FloatLayer } = await import("./floatLayer");

type FakeView = InstanceType<typeof fake.WebContentsView>;

function makeWindow(url = "http://127.0.0.1:5173/#/plugins", zoom = 1) {
  const children: FakeView[] = [];
  const host = { getURL: () => url, getZoomFactor: () => zoom, isDestroyed: () => false };
  return {
    children,
    webContents: host,
    isDestroyed: () => false,
    getContentSize: () => [1440, 900],
    contentView: {
      get children() {
        return children;
      },
      addChildView(view: FakeView) {
        const index = children.indexOf(view);
        if (index >= 0) children.splice(index, 1);
        children.push(view);
      },
      removeChildView(view: FakeView) {
        const index = children.indexOf(view);
        if (index >= 0) children.splice(index, 1);
      },
    },
  };
}

const CONTENT = {
  id: "hint-1",
  html: '<div data-tooltip="">截屏</div>',
  rect: { x: 900, y: 60, width: 140, height: 40 },
  root: { className: "dark", style: "--font-sans: Inter", attributes: { "data-theme": "dark", lang: "zh-CN" } },
};

const onWindow = (view: FakeView) => view.bounds.x + view.bounds.width > 0 && view.bounds.y + view.bounds.height > 0;

beforeEach(() => {
  fake.WebContentsView.created.length = 0;
});

describe("浮层视图", () => {
  it("提前建好、加载应用自己的浮层页(和主窗口同源),透明、不出现在窗口里", () => {
    const win = makeWindow();
    const layer = new FloatLayer(win as never);
    layer.warm();
    const [view] = fake.WebContentsView.created;
    expect(view.webContents.url).toBe("http://127.0.0.1:5173/float-layer.html");
    expect(view.background).toBe("#00000000");
    expect(onWindow(view)).toBe(false);
    expect(view.options).toMatchObject({ webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
    // 只显示我们给的内容:不跳转、不开新窗口。
    const navigate = { preventDefault: vi.fn() };
    view.webContents.handlers.get("will-navigate")!(navigate);
    expect(navigate.preventDefault).toHaveBeenCalled();
    expect(view.webContents.openHandler!()).toEqual({ action: "deny" });
    layer.warm();
    expect(fake.WebContentsView.created).toHaveLength(1);
  });

  it("打包版从 dist 的文件加载同一张浮层页", () => {
    const layer = new FloatLayer(makeWindow("file:///Applications/Mosael.app/Contents/Resources/app.asar/frontend/dist/index.html") as never);
    layer.warm();
    expect(fake.WebContentsView.created[0].webContents.url).toBe(
      "file:///Applications/Mosael.app/Contents/Resources/app.asar/frontend/dist/float-layer.html",
    );
  });

  it("显示一条说明:先把内容交给浮层页画好,再挪到说明该在的位置(四周留一圈余量),压在所有视图上面", async () => {
    const win = makeWindow();
    const layer = new FloatLayer(win as never);
    const page = new fake.WebContentsView({});
    win.contentView.addChildView(page);
    await layer.show(CONTENT);
    const view = fake.WebContentsView.created.find((one) => one !== page)!;
    expect(view.webContents.scripts.at(-1)).toContain("window.floatLayer");
    expect(view.webContents.scripts.at(-1)).toContain(JSON.stringify(CONTENT.html));
    expect(view.bounds).toEqual({ x: 900 - 6, y: 60 - 6, width: 140 + 12, height: 40 + 12 });
    expect(win.children.at(-1)).toBe(view);
    // 不抢焦点。
    expect(view.webContents.focus).not.toHaveBeenCalled();
  });

  it("主窗口缩放过:位置、大小按缩放换算,浮层页也用同样的缩放", async () => {
    const win = makeWindow("http://127.0.0.1:5173/", 1.25);
    const layer = new FloatLayer(win as never);
    await layer.show(CONTENT);
    const [view] = fake.WebContentsView.created;
    expect(view.webContents.zoom).toBe(1.25);
    expect(view.bounds).toEqual({ x: Math.floor(894 * 1.25), y: Math.floor(54 * 1.25), width: Math.ceil(152 * 1.25), height: Math.ceil(52 * 1.25) });
  });

  it("收起:挪回窗口外(照常出帧,下次显示时第一帧就是新内容)", async () => {
    const win = makeWindow();
    const layer = new FloatLayer(win as never);
    await layer.show(CONTENT);
    const [view] = fake.WebContentsView.created;
    layer.hide("hint-1");
    expect(onWindow(view)).toBe(false);
    expect(view.visible).toBe(true);
  });

  it("要收起的是上一条(已经换成下一条了):不动现在这条", async () => {
    const win = makeWindow();
    const layer = new FloatLayer(win as never);
    await layer.show({ ...CONTENT, id: "hint-2" });
    layer.hide("hint-1");
    expect(onWindow(fake.WebContentsView.created[0])).toBe(true);
    layer.hide();
    expect(onWindow(fake.WebContentsView.created[0])).toBe(false);
  });

  it("内容交过去之前就收起了:不再挪到窗口里", async () => {
    const win = makeWindow();
    const layer = new FloatLayer(win as never);
    const showing = layer.show(CONTENT);
    layer.hide("hint-1");
    await showing;
    expect(onWindow(fake.WebContentsView.created[0])).toBe(false);
  });

  it("从不留着焦点:它的页面加载完、被点到而拿到焦点时,还给最后拿着焦点的那个(网页或主窗口)", async () => {
    const win = makeWindow();
    const page = { focus: vi.fn(), isDestroyed: () => false };
    const layer = new FloatLayer(win as never, () => page as never);
    await layer.show(CONTENT);
    const [view] = fake.WebContentsView.created;
    view.webContents.handlers.get("focus")!();
    expect(page.focus).toHaveBeenCalledTimes(1);
  });

  it("没人拿着焦点时还给主窗口", () => {
    const win = makeWindow();
    const hostFocus = vi.fn();
    (win.webContents as unknown as { focus: () => void }).focus = hostFocus;
    const layer = new FloatLayer(win as never);
    layer.warm();
    fake.WebContentsView.created[0].webContents.handlers.get("focus")!();
    expect(hostFocus).toHaveBeenCalled();
  });

  it("提示条那一块(ADR 0051):不留余量、右下角贴着窗口右下角;交给浮层页的是 showToasts", async () => {
    const win = makeWindow();
    const layer = new FloatLayer(win as never, () => null, { kind: "toasts" });
    const toasts = { id: "toasts", html: "<section><ol data-sonner-toaster></ol></section>", rect: { x: 1040, y: 760, width: 400, height: 140 }, root: CONTENT.root };
    await layer.show(toasts);
    const [view] = fake.WebContentsView.created;
    expect(view.webContents.scripts.at(-1)).toContain("window.floatLayer?.showToasts(");
    expect(view.webContents.scripts.at(-1)).toContain(JSON.stringify(toasts.html));
    expect(view.bounds).toEqual({ x: 1040, y: 760, width: 400, height: 140 });
  });

  it("提示条上的指针交回渲染层:换算成主窗口的 CSS 坐标(按主窗口的缩放),只认左键松开、移动、移出", async () => {
    const win = makeWindow("http://127.0.0.1:5173/", 1.25);
    const pointers: unknown[] = [];
    const layer = new FloatLayer(win as never, () => null, { kind: "toasts", onPointer: (pointer) => pointers.push(pointer) });
    await layer.show({ id: "toasts", html: "<section></section>", rect: { x: 1040, y: 760, width: 400, height: 140 }, root: CONTENT.root });
    const [view] = fake.WebContentsView.created;
    const mouse = view.webContents.handlers.get("before-mouse-event")!;
    mouse({}, { type: "mouseMove", x: 10, y: 20 });
    mouse({}, { type: "mouseDown", x: 10, y: 20, button: "left" });
    mouse({}, { type: "mouseUp", x: 10, y: 20, button: "right" });
    mouse({}, { type: "mouseUp", x: 10, y: 20, button: "left" });
    mouse({}, { type: "mouseLeave", x: -1, y: -1 });
    const at = { x: (1040 * 1.25 + 10) / 1.25, y: (760 * 1.25 + 20) / 1.25 };
    expect(pointers).toEqual([
      { type: "move", ...at },
      { type: "up", ...at },
      { type: "leave", x: (1040 * 1.25 - 1) / 1.25, y: (760 * 1.25 - 1) / 1.25 },
    ]);
  });

  it("说明那一种不接指针(它只有说明那么大,指针本来就在说明外面)", () => {
    const layer = new FloatLayer(makeWindow() as never);
    layer.warm();
    expect(fake.WebContentsView.created[0].webContents.handlers.has("before-mouse-event")).toBe(false);
  });

  it("销毁:摘下视图、关掉它的网页", () => {
    const win = makeWindow();
    const layer = new FloatLayer(win as never);
    layer.warm();
    const [view] = fake.WebContentsView.created;
    layer.destroy();
    expect(win.children).not.toContain(view);
    expect(view.webContents.destroyed).toBe(true);
  });
});
