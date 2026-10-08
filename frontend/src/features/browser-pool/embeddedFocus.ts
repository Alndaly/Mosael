import { nativeViewAside } from "@/components/ui/nativeViewAside";
import { isCommandPaletteKey, listenKeys } from "@/lib/shortcuts";

/**
 * 键盘焦点在 Mosael 和内嵌网页之间怎么走。
 *
 * 原生网页视图和 Mosael 的界面是两个网页:系统焦点在谁那儿,键盘就给谁。进出内嵌浏览器时由主进程用
 * `webContents.focus()` 交接(进去交给网页、回来交给 Mosael,见 accountViews 的 show / hide),这里管渲染层这一半:
 *
 * - **回来时焦点落回打开之前的那个按钮**(比如工作流库详情里的「在工作台里打开」):网页亮出来那一刻记下它,
 *   收回去之后放回去。它已经不在了(弹窗关了)就不硬找。
 * - **网页亮着时,落在 Mosael 看不见的地方的按键不让它生效**:系统焦点回到 Mosael(点了顶栏的空白处)而 DOM
 *   焦点还停在底下那个按钮上时,回车会把它再点一次 —— 看不见地打开了别的东西。这一下吞掉,键盘交给网页。
 *   外壳(APP_CHROME)里的按键照常;⌘K 照常(命令面板开着时网页让开,见 components/app/overNativeView)。
 */
export function installEmbeddedFocus(): () => void {
  const bridge = window.mosaelPublish;
  if (!bridge?.onViewState) return () => undefined;
  let visible = false;
  let opener: HTMLElement | null = null;
  const stopView = bridge.onViewState((state) => {
    if (state.visible && !visible) {
      const active = document.activeElement;
      opener = active instanceof HTMLElement && active !== document.body && !inChrome(active) ? active : null;
    }
    if (!state.visible && visible) {
      const target = opener;
      opener = null;
      // 等这一轮渲染(顶栏卸掉、弹窗的焦点圈套收拾完)过去再放回去。
      window.setTimeout(() => {
        if (target?.isConnected) target.focus({ preventScroll: true });
      }, 0);
    }
    visible = state.visible;
  });
  const stopKeys = listenKeys(
    window,
    (event) => {
      // 大图这类整窗的浮层开着时网页挪到了窗口外:按键是给浮层的(Esc 关掉、左右翻页),不吞。
      // ⌘K 也不吞:网页在前台时命令面板照常开,开着时网页让开(ADR 0051 D36)。
      if (!visible || nativeViewAside() || inChrome(event.target) || isCommandPaletteKey(event)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void bridge.focusPage?.();
    },
    true,
  );
  return () => {
    stopView();
    stopKeys();
  };
}

/** 外壳里用鼠标点完,键盘交回网页;用键盘按的(Enter / 空格触发的 click,detail 是 0)焦点留在外壳里接着走。 */
export function pageAfterPointer(event: { detail: number }): void {
  if (event.detail > 0) void window.mosaelPublish?.focusPage?.();
}

function inChrome(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("[data-app-chrome]") !== null;
}
