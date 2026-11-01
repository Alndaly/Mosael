import type { EditorView } from "@tiptap/pm/view";

/**
 * 组词中的退格。
 *
 * ProseMirror 1.42.7 起会在组词期间「DOM 里的 preedit 被删短」时合成一次 `handleKeyDown(Backspace)`。
 * Tiptap 的 Backspace 快捷键即使什么都不做也会 dispatch 一个空事务；那个事务把旧的 preedit 重画回
 * DOM，浏览器当场丢掉组词，之后选词（空格）就把裸拼音留在正文。这是编辑器库的边界，不是输入法的
 * 候选文本问题。
 *
 * 真实键盘事件是 `KeyboardEvent`；ProseMirror 合成的那一个是 `document.createEvent("Event")`。
 * 两者要分开处理：
 * - 真实的退格交给浏览器 / 输入法自己走，不让 Tiptap 的空事务插进来；
 * - 合成的退格直接认领掉，否则 Tiptap 照样会 dispatch。
 */
export function isImeBackspace(view: Pick<EditorView, "composing">, event: Event & { key?: string }): boolean {
  return view.composing && event.key === "Backspace";
}

/** ProseMirror 从 DOM 变更里补发的那一下退格（不是用户按的键）。 */
export function isSyntheticImeBackspace(view: Pick<EditorView, "composing">, event: Event & { key?: string }): boolean {
  return isImeBackspace(view, event) && !(event instanceof KeyboardEvent);
}
