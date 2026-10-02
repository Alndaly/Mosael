import { isCanvasKeyTarget, isTypingTarget } from "@/lib/shortcuts";

/**
 * 剪辑页的全局快捷键该不该接这一下按键。
 *
 * 剪辑页的快捷键挂在 window 上,此前只让开输入框 —— 于是焦点停在检查器的滑杆上按 →,滑杆和播放头
 * 一起动;在 Portal 出去的下拉 / 右键菜单里按 Delete,删掉的是时间线上选中的片段。判据分两层:
 *
 *  · 一切按键:只接**冲着剪辑页来的**(焦点在 body,或在剪辑页这块里面),而且不在能打字的地方。
 *    Portal 出去的菜单、弹窗、别的页面区域一律不接。
 *  · 控件自己也要用的键(方向键、Home/End、翻页、空格、回车、Delete/Backspace、Esc):焦点在控件上
 *    (按钮、滑杆、页签、下拉……)时让给控件,判据就是画布通用的 isCanvasKeyTarget。
 *
 * ⌘Z、S、B 这类控件不用的键,焦点在按钮上时照常生效:点过工具栏的「撤销」再按 ⌘Z,焦点正停在那颗
 * 按钮上,不能因此失灵。
 *
 * 时间线上的片段是可聚焦的(键盘可达),它们带 role="button" 却不是控件 —— 是画布上的元素,
 * 焦点停在片段上时一切快捷键照常(和 React Flow 的节点同理)。
 */
const CONTROL_KEYS = new Set([
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "ArrowDown",
  "Home",
  "End",
  "PageUp",
  "PageDown",
  " ",
  "Enter",
  "Delete",
  "Backspace",
  "Escape",
]);

export function isEditorKeyTarget(event: Pick<KeyboardEvent, "key" | "target">, root: Element | null): boolean {
  const element = event.target as Element | null;
  if (!element || !root || typeof element.closest !== "function") return false;
  if (element === element.ownerDocument?.body) return true;
  if (!root.contains(element) || isTypingTarget(element)) return false;
  if (element.closest("[data-clip-id]")) return true;
  if (!CONTROL_KEYS.has(event.key)) return true;
  return isCanvasKeyTarget(element, root);
}
