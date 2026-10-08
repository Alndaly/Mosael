/** 主进程交过来的一条说明(electron/publish/floatLayer.ts 的 show)。 */
export type FloatPayload = {
  html: string;
  root: { className: string; style: string; attributes: Record<string, string> };
  /** 说明离视图边多远(CSS 像素)。 */
  pad: number;
  /** 说明在主窗口里量出来的宽度:照这个宽度画,折行和主窗口里一样,不跟视图大小走。 */
  width: number;
};

const nextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

/** 主进程交过来的提示条那一块(electron/publish/floatLayer.ts 的 `toasts` 那一种,渲染层见 components/app/toastMirror)。 */
export type ToastsPayload = Pick<FloatPayload, "html" | "root">;

/** 根元素换成主窗口的主题、字体、语言。 */
function applyRootLook(doc: Document, look: FloatPayload["root"]): void {
  const root = doc.documentElement;
  root.className = look.className;
  if (look.style) root.setAttribute("style", look.style);
  else root.removeAttribute("style");
  for (const attribute of Array.from(root.attributes)) {
    if ((attribute.name.startsWith("data-") || attribute.name === "dir") && !(attribute.name in look.attributes)) {
      root.removeAttribute(attribute.name);
    }
  }
  for (const [name, value] of Object.entries(look.attributes)) root.setAttribute(name, value);
}

/**
 * 照主窗口的样子画一条说明:根元素换成主窗口的主题、字体、语言,再把说明那一块原样放进来。等画出一帧再回话 ——
 * 主进程拿到回话才把视图挪进窗口,挪进来那一帧就是这条说明。
 */
export async function showFloat(doc: Document, container: HTMLElement, payload: FloatPayload): Promise<boolean> {
  applyRootLook(doc, payload.root);
  container.style.padding = `${payload.pad}px`;
  container.style.width = `${payload.width + payload.pad * 2}px`;
  container.innerHTML = payload.html;
  await nextFrame();
  return true;
}

/**
 * 照主窗口的样子画右下角那一整块提示条。Sonner 的列表是 `position: fixed` 贴着右下角的(离边多远在它的 style 里带着),
 * 而这块视图的右下角就是窗口的右下角 —— 原样放进来,位置就对上了。等画出一帧再回话(同 showFloat)。
 */
export async function showToasts(doc: Document, container: HTMLElement, payload: ToastsPayload): Promise<boolean> {
  applyRootLook(doc, payload.root);
  container.innerHTML = payload.html;
  await nextFrame();
  return true;
}

export function clearFloat(container: HTMLElement): void {
  container.innerHTML = "";
}
