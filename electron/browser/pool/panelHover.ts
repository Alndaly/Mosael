/**
 * 指针是否悬停在某块悬浮面板的**网页**上。
 *
 * 网页是原生视图,盖在渲染层之上,落在它上面的鼠标事件渲染层一个也收不到 —— 渲染层只看得见卡片
 * 那圈边和标题条。所以网页这一块由主进程看,来源是 webContents 的 `before-mouse-event`:页面收到
 * 的每一个鼠标事件(移动、按下、滚轮、离开)派发前都先经过它,我们只看不拦。除 `mouseLeave` 以外
 * 的任何事件都说明指针此刻在页面上;`mouseLeave` 说明它刚离开。
 *
 * 为什么不用别的:`cursor-changed` 只在光标**形状**变化时触发,从画布(箭头)移进一个同样是箭头的
 * 页面区域时什么也不发,也没有"离开"这回事;`input-event` 能看到同样的鼠标事件,但它是所有输入的
 * 总线(键盘、手势……),这里只关心鼠标;纯轮询系统指针则要在面板挂着的整个期间(RPA 会话可能
 * 跑几个小时)一直空转。
 *
 * **离开事件不是总会来。** 视图在静止的指针底下被挪走或缩小(拖动、缩放、叠放次序变化)、应用
 * 失去激活、指针从跨源 iframe 里直接离开 —— 这些路径上 Chromium 不一定补发 mouseLeave,漏一次
 * 手柄就一直亮着。所以**只在有面板处于悬停时**,再起一个低频的兜底检查:问系统指针此刻还在不在
 * 那块视图里。没有悬停时什么都不跑。
 */

/** 兜底检查的间隔。只在悬停期间跑;漏掉的离开最多晚这么久被纠正。 */
export const HOVER_RECHECK_MS = 250;

export class PanelHover {
  private hovered = new Set<string>();
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly opts: {
      /** 系统指针此刻是否在这块面板的网页区域里。 */
      pointerInside: (id: string) => boolean;
      /** 有面板的悬停状态变了(渲染层据此显示 / 淡出缩放手柄)。 */
      onChange: () => void;
    },
  ) {}

  /** 喂 `before-mouse-event` 的事件类型。 */
  observe(id: string, type: string): void {
    this.set(id, type !== "mouseLeave");
  }

  has(id: string): boolean {
    return this.hovered.has(id);
  }

  /** 面板撤下 / 亮到前台时忘掉它。**不通知** —— 调用方自己会重排并下发面板。 */
  drop(id: string): void {
    this.hovered.delete(id);
    this.syncRecheck();
  }

  dispose(): void {
    this.hovered.clear();
    this.syncRecheck();
  }

  private set(id: string, hovered: boolean): void {
    if (hovered === this.hovered.has(id)) return;
    if (hovered) this.hovered.add(id);
    else this.hovered.delete(id);
    this.syncRecheck();
    this.opts.onChange();
  }

  private syncRecheck(): void {
    if (this.hovered.size > 0 && !this.timer) {
      this.timer = setInterval(() => this.recheck(), HOVER_RECHECK_MS);
    } else if (this.hovered.size === 0 && this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private recheck(): void {
    for (const id of [...this.hovered]) {
      if (!this.opts.pointerInside(id)) this.set(id, false);
    }
  }
}
