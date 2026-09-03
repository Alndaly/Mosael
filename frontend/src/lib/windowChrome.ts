/**
 * 无边框窗里,顶栏要给系统按钮让出来的位置 —— **只有这一份**。
 *
 * macOS 左上角是红绿灯,Windows 右上角是最小化/最大化/关闭。窗口无边框(titleBarStyle: hidden)
 * 时它们直接压在页面内容上,顶栏必须让开,否则按钮会盖住标题或工具条。
 *
 * ## 为什么把 `:not(.is-fullscreen)` 写进选择器
 *
 * 全屏时系统按钮不在那儿了,让出来的位置就成了一块凭空的空白。此前的写法是"先无条件让开,
 * 再用一条 `.is-fullscreen` 的规则把它改回去" —— 两条类要一起写,而应用里有三处顶栏,
 * 结果发布视图那条只写了前一半:非全屏正常,全屏左边空出 88px 没人认领(线上就是这么报出来的)。
 *
 * 写成一条带 `:not()` 的规则之后,不存在"要记得配对"这回事:全屏时它根本不生效,元素自己的
 * 水平内边距自然接管 —— 所以各处用什么 `px-*` 都行,这份常量不必知道。
 */
export const WINDOW_CHROME_INSET =
  "[.is-desktop.is-mac:not(.is-fullscreen)_&]:pl-[88px] [.is-desktop.is-win:not(.is-fullscreen)_&]:pr-[148px]";

type WindowChromeBridge = Pick<
  NonNullable<Window["mosaelDesktop"]>,
  "platform" | "onFullscreen" | "setTitleOverlay"
>;

/**
 * 安装无边框桌面窗口的根状态。
 *
 * 这必须在 React 首屏之前调用:安全区是窗口外壳的固有状态,不属于某个页面或组件。把它放进
 * App 的 effect 会让第一帧没有 `is-mac`,也会让 HMR/重挂载期间出现短暂的错误布局。
 */
export function installWindowChrome(
  desktop: WindowChromeBridge | undefined = window.mosaelDesktop,
  root: HTMLElement = document.documentElement,
): () => void {
  if (!desktop) return () => undefined;

  const usesTitleBarOverlay = desktop.platform !== "darwin";
  root.classList.add("is-desktop", usesTitleBarOverlay ? "is-win" : "is-mac");

  const removeFullscreenListener = desktop.onFullscreen?.((fullscreen) => {
    root.classList.toggle("is-fullscreen", fullscreen);
  });

  let observer: MutationObserver | undefined;
  if (usesTitleBarOverlay && desktop.setTitleOverlay) {
    const pushOverlay = () =>
      desktop.setTitleOverlay!(
        root.classList.contains("dark")
          ? { color: "#15181e", symbolColor: "#e7eaf0" }
          : { color: "#ffffff", symbolColor: "#656c78" },
      );
    pushOverlay();
    observer = new MutationObserver(pushOverlay);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
  }

  return () => {
    removeFullscreenListener?.();
    observer?.disconnect();
  };
}
