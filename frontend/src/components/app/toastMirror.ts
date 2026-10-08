import React from "react";

import { rootLook } from "@/components/ui/floatLayer";
import { useNativeViewSteppedAside } from "@/components/ui/nativeViewAside";
import { useNativeViewInFront } from "@/lib/nativeView";

/**
 * 原生视图(内嵌浏览器、ComfyUI 工作台的画布)在前台时,右下角的提示条**画进浮层视图**(ADR 0051 D33)。
 *
 * 原生视图盖在一切 DOM 上:写请求失败、拖到 Dock 上的文件导入失败、更新提示……这些提示条在 DOM 里照常弹,屏幕上看不见,
 * 内嵌浏览器亮着时一条都不剩。所以这段时间里,提示条那一整块(Sonner 的 `<section>`)原样交给主进程的提示条浮层视图
 * (electron/publish/floatLayer.ts 的 `toasts` 那一种),压在网页上面画;DOM 里那份照常渲染、照常计时、照常给读屏念,只是透明
 * (styles.css 的 `[data-toasts-mirrored]`)。
 *
 * - **位置**:浮层视图的右下角就是窗口的右下角,浮层页照主窗口的样子把提示条贴着右下角摆(Sonner 的 `--offset-*` 在 HTML 里带着,
 *   让开贴底输入区的那一截 —— useToastClearance —— 也就跟着过去了)。左上角按提示条摆满时的样子量(展开时每条的 `--offset`、
 *   收着时露出来的那几道边),不按此刻动画走到哪儿量:刚弹出来的那条还在往上滑,按它量就小了一截。
 * - **按钮点得到**:浮层视图上的那一份只是照着画的样子。主进程把它上面的指针换算成主窗口的坐标交回来(`onToastsPointer`):
 *   移进来 → 在 DOM 里那份上发 mousemove,Sonner 照常展开、停住计时;移出去 → mouseout,收回去;松开 → 落在哪条提示的哪个
 *   按钮上就点 DOM 里那一个(「查看」「撤销」「×」)。按位置找,不用 elementFromPoint:DOM 里那份透明着,上面可能还压着弹窗的遮罩。
 * - 原生视图**让开着**的时候(看大图、命令面板、任务中心开着,见 nativeViewAside)窗口里看得见的全是 DOM,提示条照常画在 DOM 里。
 *
 * 只在桌面版有这座桥时生效。返回此刻是不是交给浮层视图画着。
 */

type ToastsBridge = Pick<NonNullable<Window["mosaelPublish"]>, "showToasts" | "hideToasts" | "onToastsPointer">;
type ToastsPointer = Parameters<Parameters<ToastsBridge["onToastsPointer"]>[0]>[0];

/** 提示条那一块四周多留的一圈(CSS 像素):关闭键伸出卡片左上角的那一截、投影。 */
const MARGIN = 16;

function toastsBridge(): ToastsBridge | null {
  const bridge = typeof window === "undefined" ? undefined : window.mosaelPublish;
  return bridge &&
    typeof bridge.showToasts === "function" &&
    typeof bridge.hideToasts === "function" &&
    typeof bridge.onToastsPointer === "function"
    ? bridge
    : null;
}

const px = (element: HTMLElement, name: string) => Number.parseFloat(element.style.getPropertyValue(name)) || 0;

/** 一条提示此刻露不露在外面:展开着的、最前面那条,或者收着时在它后面露出一道边的那两条。 */
const shownToasts = (list: HTMLElement) =>
  Array.from(list.querySelectorAll<HTMLElement>("[data-sonner-toast]")).filter(
    (toast) => toast.dataset.visible !== "false" && toast.dataset.removed !== "true",
  );

/**
 * 提示条摆满时从列表底边往上占多高:展开着是每条的 `--offset` 加它自己的高;收着是最前那条的高,后面每多一条往上露一道 `--gap`。
 * 量的是 Sonner 写在 style 上的数(布局的结果),不是此刻的 transform(动画的中间态)。
 */
export function toastsExtent(list: HTMLElement): number {
  const front = px(list, "--front-toast-height");
  const gap = px(list, "--gap");
  let extent = 0;
  for (const toast of shownToasts(list)) {
    const index = Number(toast.dataset.index ?? 0);
    const height = px(toast, "--initial-height") || toast.offsetHeight;
    extent = Math.max(extent, toast.dataset.expanded === "true" ? px(toast, "--offset") + height : (index === 0 ? height : front) + gap * index);
  }
  return extent;
}

/** 落在哪条提示的哪个按钮上(露在外面的那几条里,前面的盖住后面的)。 */
function buttonAt(list: HTMLElement, x: number, y: number): HTMLElement | null {
  const toasts = shownToasts(list)
    .filter((toast) => toast.dataset.expanded === "true" || toast.dataset.front === "true")
    .sort((a, b) => Number(a.dataset.index ?? 0) - Number(b.dataset.index ?? 0));
  for (const toast of toasts) {
    for (const button of Array.from(toast.querySelectorAll<HTMLElement>("button"))) {
      const box = button.getBoundingClientRect();
      if (x >= box.left && x <= box.right && y >= box.top && y <= box.bottom) return button;
    }
    const box = toast.getBoundingClientRect();
    if (x >= box.left && x <= box.right && y >= box.top && y <= box.bottom) return null; // 点在这条的空白处:后面的被它盖着
  }
  return null;
}

/** 浮层视图上的指针,落到 DOM 里那份提示条上。 */
export function forwardToastsPointer(host: HTMLElement, pointer: ToastsPointer): void {
  const list = host.querySelector<HTMLElement>("[data-sonner-toaster]");
  if (!list) return;
  const at = { clientX: pointer.x, clientY: pointer.y, bubbles: true, cancelable: true };
  if (pointer.type === "move") list.dispatchEvent(new MouseEvent("mousemove", at));
  else if (pointer.type === "leave") list.dispatchEvent(new MouseEvent("mouseout", { ...at, relatedTarget: null }));
  else buttonAt(list, pointer.x, pointer.y)?.click();
}

export function useToastMirror(host: HTMLElement | null): boolean {
  const inFront = useNativeViewInFront();
  const aside = useNativeViewSteppedAside();
  const active = inFront && !aside && toastsBridge() !== null;
  React.useLayoutEffect(() => {
    const bridge = active ? toastsBridge() : null;
    if (!bridge || !host) return;
    let frame = 0;
    let last = "";
    const hide = () => {
      if (last) bridge.hideToasts();
      last = "";
    };
    const measure = () => {
      frame = 0;
      const list = host.querySelector<HTMLElement>("[data-sonner-toaster]");
      const section = list?.closest("section");
      if (!list || !section || shownToasts(list).length === 0) return hide();
      const box = list.getBoundingClientRect();
      const x = Math.max(0, Math.floor(box.left - MARGIN));
      const y = Math.max(0, Math.floor(box.bottom - toastsExtent(list) - MARGIN));
      const toasts = {
        html: section.outerHTML,
        rect: { x, y, width: window.innerWidth - x, height: window.innerHeight - y },
        root: rootLook(),
      };
      const key = JSON.stringify(toasts);
      if (key === last) return;
      last = key;
      bridge.showToasts(toasts);
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(measure);
    };
    const observer = new MutationObserver(schedule);
    observer.observe(host, { subtree: true, childList: true, attributes: true, characterData: true });
    window.addEventListener("resize", schedule);
    const stopPointer = bridge.onToastsPointer((pointer) => forwardToastsPointer(host, pointer));
    schedule();
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      stopPointer();
      hide();
    };
  }, [active, host]);
  return active;
}
