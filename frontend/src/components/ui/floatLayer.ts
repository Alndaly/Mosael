import * as React from "react";

type FloatHint = Parameters<NonNullable<Window["mosaelPublish"]>["showFloat"]>[0];

let nextId = 0;

const nextFrame = (callback: () => void): (() => void) => {
  if (typeof window.requestAnimationFrame === "function") {
    const frame = window.requestAnimationFrame(callback);
    return () => window.cancelAnimationFrame(frame);
  }
  const timer = window.setTimeout(callback, 16);
  return () => window.clearTimeout(timer);
};

/** 桌面版有浮层视图(能把说明画在原生网页视图上面)。网页版没有原生视图,也就用不着。 */
function floatBridge(): Pick<NonNullable<Window["mosaelPublish"]>, "showFloat" | "hideFloat"> | null {
  const bridge = typeof window === "undefined" ? undefined : window.mosaelPublish;
  return bridge && typeof bridge.showFloat === "function" && typeof bridge.hideFloat === "function" ? bridge : null;
}

/** 根元素上和外观有关的那几样:主题、字体、语言。浮层页照着设,画出来和应用里一模一样(提示条那一块也用,见 toastMirror)。 */
export function rootLook(): FloatHint["root"] {
  const root = document.documentElement;
  const attributes: Record<string, string> = {};
  for (const attribute of Array.from(root.attributes)) {
    if (attribute.name.startsWith("data-") || attribute.name === "lang" || attribute.name === "dir") {
      attributes[attribute.name] = attribute.value;
    }
  }
  return { className: root.className, style: root.getAttribute("style") ?? "", attributes };
}

/**
 * 把一块浮层(说明)交给**浮层视图**画到原生网页视图上面(见 electron/publish/floatLayer.ts)。内嵌浏览器的
 * 外壳(顶栏、页面列表、侧栏)旁边就是原生网页视图,盖在一切 DOM 上 —— DOM 里的说明伸进去就看不见。
 *
 * DOM 里那份照常渲染、照常由 Radix 摆位置:它用来量位置、给读屏念(`role="tooltip"` 还在),只是透明。
 * 摆好位置以后每一帧看一眼位置和内容,变了才交过去;收起(或卸掉)时让浮层视图收起同一条。
 */
export function useFloatMirror(element: HTMLElement | null, enabled: boolean): boolean {
  const active = enabled && floatBridge() !== null;
  React.useLayoutEffect(() => {
    const bridge = active ? floatBridge() : null;
    if (!bridge || !element) return;
    const id = `float-${++nextId}`;
    const wrapper = element.parentElement;
    let last = "";
    let shown = false;
    let cancel = () => undefined as void;
    const tick = () => {
      cancel = nextFrame(tick);
      if (!element.isConnected || !wrapper) return;
      if (element.dataset.state === "closed") {
        if (shown) bridge.hideFloat(id);
        shown = false;
        return;
      }
      // Radix 还没摆好位置时把它放在视口外面(translate(0, -200%)),这时量出来的不是它该在的地方。
      if (wrapper.style.transform.includes("-200%")) return;
      wrapper.style.opacity = "0";
      const box = wrapper.getBoundingClientRect();
      const hint: FloatHint = {
        id,
        html: element.outerHTML,
        rect: { x: box.left, y: box.top, width: box.width, height: box.height },
        root: rootLook(),
      };
      const key = JSON.stringify(hint);
      if (key === last) return;
      last = key;
      shown = true;
      bridge.showFloat(hint);
    };
    tick();
    return () => {
      cancel();
      if (shown) bridge.hideFloat(id);
    };
  }, [active, element]);
  return active;
}
