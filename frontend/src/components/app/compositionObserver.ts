import type { EditorView } from "@tiptap/pm/view";

/**
 * 组词期间把 ProseMirror 的 DOM 观察整个停掉，compositionend 后一次性读最终 DOM。
 *
 * 只挡住某一下退格不够：中文输入法的 preedit 会在 `compositionupdate` 里连续改短，而 Chrome
 * 在这条路上不一定发 keydown。ProseMirror 一旦逐拍读这些中间 DOM，就会把 preedit 当正文；
 * `prosemirror-view@1.42.7` 还会从删除里补发一次合成 Backspace，Tiptap 的快捷键再 dispatch
 * 一个空事务，把旧 preedit 重画回来，组词当场丢失 —— 之后选词 / 空格留下的就是裸拼音。
 *
 * 所以这里守的是**组词整段**：输入法在 DOM 里怎么写都不读，`compositionend` 后按最终 DOM
 * 读一次。ProseMirror 自己也会在 compositionend 处理收尾；我们放到下一拍再 start + flush，
 * 让用户确认的字作为一次普通变更进入文档。
 *
 * `domObserver` 没有公开类型，但 stop / start / flush 是编辑器自己的实例字段，行为稳定。
 */
type ObservedView = EditorView & {
  domObserver: { stop(): void; start(): void; flush(): void; forceFlush(): void };
};

const held = new WeakSet<EditorView>();

export function holdComposition(view: EditorView): void {
  if (held.has(view)) return;
  held.add(view);
  const observer = (view as ObservedView).domObserver;
  //: 先把组词开始前已经排队的变更读完，再停观察。`stop()` 自己会把 takeRecords 塞回队列并
  //: 排一个 20ms 后的 flush；那个定时器会在组词中途把 preedit 当成正文读走。
  observer.flush();
  observer.forceFlush();
  observer.stop();
}

export function releaseComposition(view: EditorView): void {
  if (!held.has(view)) return;
  held.delete(view);
  const observer = (view as ObservedView).domObserver;
  //: ProseMirror 的 compositionend 处理会先把 composing 置回 false；下一拍再恢复观察，
  //: 读到的才是用户最终确认的 DOM（不是 preedit）。
  window.setTimeout(() => {
    observer.start();
    observer.flush();
    //: 组词期间没有 transaction，placeholder 的空态类可能还粘在已经有字的段落上；
    //: 清掉它，下一次正常 transaction 会按真实文档重新算。
    if (view.dom.textContent?.trim()) {
      for (const element of view.dom.querySelectorAll(".is-empty, .is-editor-empty")) {
        element.classList.remove("is-empty", "is-editor-empty");
      }
    }
  }, 0);
}
