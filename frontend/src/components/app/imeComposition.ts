import { Extension } from "@tiptap/react";
import { Plugin, type Transaction } from "@tiptap/pm/state";

import { COMPOSE_SETTLE_MS } from "@/components/app/useExternalContent";

/**
 * 输入法组词期间的两条规矩，所有可编辑的 Tiptap 共用一份（编辑器棘轮见 design/editorNames.test.ts）。
 *
 * **一、组词中不派发空事务。** 中文 preedit 被删短（`ce shi` → `ce sh`）时，`prosemirror-view` 会把这次
 * DOM 删除补发成一次 `handleKeyDown(Backspace)`；Tiptap 的 Backspace 处理器（`undoInputRule`、`first`）
 * 即使什么也没做也会 `view.dispatch(tr)` 一个空事务。这一下在组词中途更新视图，浏览器的组词随即中断，
 * 之后选词 / 空格留下的就是裸拼音（`首先ce shce测试`）。空事务——不改文档、不改选区、不带 meta——
 * 本来就没有东西要交给谁，组词时直接不派发。
 *
 * ProseMirror 自己的组词读取一律照常：组词的字随 DOM 变更一拍一拍进文档，光标也由它自己按 DOM 定位。
 * （此前的做法是组词整段断开 DOM 观察，结果真实浏览器里组出来的字根本没被观察到，光标被重绘回字前，
 * 连续组词还会丢字。）
 *
 * **二、组词结束补发一次 update。** 各编辑器的 `onUpdate` 在 `view.composing` 时跳过（组词中的文档只是
 * 候选，交给父层再回灌就会把拼音当正文），而组词的最后一拍常常就发生在 composing 还为真的时候 ——
 * 没有这一下，父层要等下一次按键才拿到组出来的字（点「生成」时提示词里少最后一个词）。
 * 等 ProseMirror 收尾（`COMPOSE_SETTLE_MS` 晚于它的 20ms）之后，若组词期间文档变过而此后还没有过
 * 正常的 update，就把组词里最后那个改了文档的事务重放成一次 update。
 */
export const ImeComposition = Extension.create<object, { pending: Transaction | null; timer: number | undefined }>({
  name: "imeComposition",

  addStorage() {
    return { pending: null, timer: undefined };
  },

  dispatchTransaction({ transaction, next }) {
    if (this.editor.view.composing && isEmpty(transaction)) return;
    next(transaction);
  },

  onTransaction({ transaction }) {
    if (!transaction.docChanged) return;
    //: 组词中改了文档的那一下留着，等组词结束重放；组词外的改动照常走 update，补发就不必了。
    this.storage.pending = this.editor.view.composing ? transaction : null;
  },

  addProseMirrorPlugins() {
    const settle = () => {
      window.clearTimeout(this.storage.timer);
      this.storage.timer = window.setTimeout(() => {
        const transaction = this.storage.pending;
        if (!transaction || this.editor.isDestroyed || this.editor.view.composing) return;
        this.storage.pending = null;
        this.editor.emit("update", { editor: this.editor, transaction, appendedTransactions: [] });
      }, COMPOSE_SETTLE_MS);
    };
    return [new Plugin({ props: { handleDOMEvents: { compositionend: () => { settle(); return false; } } } })];
  },

  onDestroy() {
    window.clearTimeout(this.storage.timer);
  },
});

/** 没有任何内容的事务：不改文档、不改选区、不改存储的标记，也没有任何插件挂 meta。 */
function isEmpty(transaction: Transaction): boolean {
  return !transaction.docChanged && !transaction.selectionSet && !transaction.storedMarksSet && transaction.isGeneric;
}
