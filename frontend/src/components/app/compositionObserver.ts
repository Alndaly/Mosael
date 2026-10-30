import type { EditorView } from "@tiptap/pm/view";

/**
 * 组词期间先停掉 ProseMirror 的 DOM 观察,compositionend 后一次性读最终 DOM。
 *
 * ProseMirror 会在组词过程中把候选字同步进文档。Chrome 里退格缩短候选(如 `ni` → `n`),
 * 它把缩短后的拼音当成一次普通替换保留下来;紧接着的候选更新又被追加上去,提交后就成了
 * `n你`。普通 contenteditable 不会这样 —— 这是编辑器层与中文 IME 的边界,不是受控值回灌。
 *
 * 停在 DOM 观察这一层,而不是改候选文本:组词期间 DOM 是输入法的,ProseMirror 不该逐拍读;
 * compositionend 后按最终 DOM 读一次,得到的才是用户确认的字。`domObserver` 没有公开类型,
 * 但它是编辑器自己的实例字段,停止/启动/冲刷都是稳定的内部操作。
 */
type ObservedView = EditorView & {
  domObserver: { stop(): void; start(): void; flush(): void };
};

const paused = new WeakSet<EditorView>();

export function pauseCompositionObserver(view: EditorView): boolean {
  paused.add(view);
  (view as ObservedView).domObserver.stop();
  return false;
}

export function resumeCompositionObserver(view: EditorView): boolean {
  //: 只有退格缩短候选时我们才停过观察。普通中文组词不停 —— 停了会丢 ProseMirror 的选区映射,
  //: 组词结束后光标会卡在第一段文字末尾。
  if (!paused.has(view)) return false;
  paused.delete(view);
  const observer = (view as ObservedView).domObserver;
  //: ProseMirror 的 compositionend 处理会先把 composing 置回 false;下一拍再恢复观察,
  //: 让最终 DOM(用户确认的字)作为一次变更被读入。
  window.setTimeout(() => {
    observer.start();
    observer.flush();
    //: 组词期间没有 transaction,placeholder 的空态类可能还粘在已经有字的段落上;
    //: 清掉它,下一次正常 transaction 会按真实文档重新算。
    if (view.dom.textContent?.trim()) {
      for (const element of view.dom.querySelectorAll(".is-empty, .is-editor-empty")) {
        element.classList.remove("is-empty", "is-editor-empty");
      }
    }
  }, 0);
  return false;
}
