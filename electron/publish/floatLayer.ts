import { WebContentsView, type BaseWindow, type BrowserWindow } from "electron";

/** 浮层四周留的余量(CSS 像素):说明的边框、出现时的那点缩放都不被视图的边裁掉。 */
const PAD = 6;
/** 收起时挪到窗口外多远。 */
const OFF_WINDOW_GAP = 64;

type Rect = { x: number; y: number; width: number; height: number };

/** 一条要画在原生网页视图上面的说明(渲染层量好、序列化好的,见 frontend/src/components/ui/floatLayer.ts)。 */
export interface FloatHint {
  /** 哪一条:收起时只收自己那一条,已经换成下一条了就不动。 */
  id: string;
  /** 说明浮层那一块的 HTML(应用自己渲染出来的,文字已转义)。 */
  html: string;
  /** 它在主窗口里的位置(CSS 像素)。 */
  rect: Rect;
  /** 主窗口根元素上和外观有关的那几样(主题、字体、语言),浮层页照着设。 */
  root: { className: string; style: string; attributes: Record<string, string> };
}

/**
 * **浮层视图**:一块透明的原生视图,专门把内嵌浏览器外壳(顶栏、页面列表、侧栏)里的悬停说明画在原生网页视图
 * 上面。原生视图盖在一切 DOM 上,渲染层的说明伸进网页那一块就被盖住 —— 顶栏的说明只能往左右挤,压住地址栏。
 *
 * 画法:加载应用自己的浮层页(frontend/float-layer.html,和主窗口同源、同一套样式),渲染层把量好的说明 HTML
 * 交过来,浮层页照原样画;这块视图只有说明那么大,挪到说明该在的位置,压在所有视图最上面。
 *
 * - 不留焦点:新视图里的页面加载完时 Chromium 会把焦点给它,点到它也会 —— 那样在地址栏、网页里打的字都进了
 *   这块看不见的视图。它一拿到焦点就还给最后拿着焦点的那个(网页或主窗口,由 `focusTarget` 说;问「此刻谁拿着
 *   焦点」不可靠:刚交给网页的焦点,这时候可能还没算上)。只有说明那么大,指针本来就在说明外面。
 * - 收起不是藏起来,是挪到窗口外、照常出帧:藏起来的视图下次亮出来,第一帧可能还是上一条说明。
 * - 提前建好(`warm`):内嵌浏览器一亮出来就加载浮层页,第一条说明不用等页面加载。
 */
export class FloatLayer {
  private view: WebContentsView | null = null;
  private ready: Promise<unknown> = Promise.resolve();
  /** 正在显示(或正要显示)的那一条。 */
  private current: string | null = null;
  private bounds: Rect = { x: 0, y: 0, width: 1, height: 1 };

  constructor(
    private readonly window: BaseWindow,
    /** 最后拿着焦点的那个(网页或主窗口):浮层视图拿到焦点时还给它。 */
    private readonly focusTarget: () => Electron.WebContents | null = () => null,
  ) {}

  warm(): void {
    this.ensure();
  }

  async show(hint: FloatHint): Promise<void> {
    const view = this.ensure();
    if (!view) return;
    this.current = hint.id;
    const zoom = this.host()?.getZoomFactor() ?? 1;
    view.webContents.setZoomFactor(zoom);
    const { x, y, width, height } = hint.rect;
    const target = {
      x: Math.floor((x - PAD) * zoom),
      y: Math.floor((y - PAD) * zoom),
      width: Math.ceil((width + PAD * 2) * zoom),
      height: Math.ceil((height + PAD * 2) * zoom),
    };
    await this.ready;
    if (this.current !== hint.id) return;
    // 先在窗口外画好(浮层页等一帧再回话),再挪进来 —— 挪进来那一帧就是这条说明。
    const payload = { html: hint.html, root: hint.root, pad: PAD, width };
    await view.webContents.executeJavaScript(`window.floatLayer?.show(${JSON.stringify(payload)})`).catch(() => undefined);
    if (this.current !== hint.id || this.window.isDestroyed()) return;
    this.bounds = target;
    view.setBounds(target);
    // 再加一次同一个视图 = 挪到最上面:网页视图、悬浮面板换过之后也压得住。
    this.window.contentView.addChildView(view);
  }

  /** 收起 `id` 那一条(不给就是不管哪条都收)。 */
  hide(id?: string): void {
    if (id !== undefined && id !== this.current) return;
    this.current = null;
    if (!this.view || this.window.isDestroyed()) return;
    this.view.setBounds({ ...this.bounds, x: -(this.bounds.width + OFF_WINDOW_GAP) });
  }

  destroy(): void {
    const view = this.view;
    this.view = null;
    this.current = null;
    if (!view) return;
    if (!this.window.isDestroyed()) {
      try {
        this.window.contentView.removeChildView(view);
      } catch {
        // 已经摘掉了
      }
    }
    if (!view.webContents.isDestroyed()) view.webContents.close();
  }

  private host(): Electron.WebContents | null {
    const contents = (this.window as BrowserWindow).webContents;
    return contents && !contents.isDestroyed() ? contents : null;
  }

  private returnFocus(): void {
    const target = this.focusTarget();
    (target && !target.isDestroyed() ? target : this.host())?.focus();
  }

  private ensure(): WebContentsView | null {
    if (this.view && !this.view.webContents.isDestroyed()) return this.view;
    const host = this.host();
    if (!host || this.window.isDestroyed()) return null;
    const view = new WebContentsView({
      webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, backgroundThrottling: false },
    });
    view.setBackgroundColor("#00000000");
    this.bounds = { x: 0, y: 0, width: 1, height: 1 };
    view.setBounds({ ...this.bounds, x: -(1 + OFF_WINDOW_GAP) });
    // 只画我们交过去的内容:不跳转、不开新窗口。
    view.webContents.on("will-navigate", (event) => event.preventDefault());
    view.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    view.webContents.on("focus", () => this.returnFocus());
    this.window.contentView.addChildView(view);
    this.view = view;
    // 和主窗口同源:开发时是 vite 的地址,打包后是 dist 里的文件。
    this.ready = view.webContents.loadURL(new URL("float-layer.html", host.getURL()).toString()).catch(() => undefined);
    return view;
  }
}
