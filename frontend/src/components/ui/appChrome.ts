/**
 * **窗口外壳**:内嵌网页视图亮着时盖在应用最上层的浏览器顶栏和页面列表(App 的 PublishViewBar、BrowserPageList)。
 *
 * 它们和底下开着的弹窗没有关系,却在弹窗外面 —— Radix 会把点在它们上面的那一下当成「点了弹窗外面」,把弹窗关掉。
 * 真机上就是这样:工作流库「在编辑器里打开」之后点「返回 Mosael」,回来工作流库没了,得重新打开、重新找到那一张。
 * 所以外壳挂上 `APP_CHROME`,弹窗和抽屉的「点了外面」碰到它就当没发生。
 */
export const APP_CHROME = { "data-app-chrome": "" } as const;

type OutsideEvent = Event & { detail?: { originalEvent?: Event } };

/** 包一层弹窗的 onInteractOutside:点在窗口外壳上就拦下,别的照旧交给调用方给的那个。 */
export function keepOpenOnAppChrome<E extends OutsideEvent>(handler?: (event: E) => void) {
  return (event: E) => {
    const target = event.detail?.originalEvent?.target ?? event.target;
    if (target instanceof Element && target.closest("[data-app-chrome]")) {
      event.preventDefault();
      return;
    }
    handler?.(event);
  };
}
