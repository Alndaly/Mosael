import React from "react";
import type { Editor } from "@tiptap/react";

/**
 * 可编辑的 TipTap 编辑器**从外面接内容**(清空、切换、恢复版本、别处改了)的唯一做法。
 *
 * `sync` 自己判「外面那份和编辑器里的是不是一回事」、不是才 setContent;这里只管**什么时候
 * 能动**:输入法正在组词(`editor.view.composing`)时一律不动。组词中的字还只在 DOM 里、
 * 没进 ProseMirror 的文档 —— 这时拿外面那份一比必然「不一样」,setContent 一下,组词被打断,
 * 拼音字母当正文上屏,光标还跳走(便签那次是同一个道理,见 components/ui/draft-text)。
 *
 * 组词结束后再补判一次:ProseMirror 在 compositionend 之后 20ms 才把组词收尾
 * (prosemirror-view 的 scheduleComposeEnd),补判放在那之后,拿到的是上屏之后的文档和
 * 调用方最新的那份。
 *
 * 可编辑编辑器里的 `setContent(` 只许出现在这个钩子的 `sync` 里(见 useExternalContent.ratchet.test)。
 */
export function useExternalContent(editor: Editor | null, sync: (editor: Editor) => void, deps: React.DependencyList): void {
  const latest = React.useRef(sync);
  latest.current = sync;
  React.useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const run = () => {
      if (!editor.isDestroyed && !editor.view.composing) latest.current(editor);
    };
    if (!editor.view.composing) {
      run();
      return;
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const dom = editor.view.dom;
    const ended = () => {
      clearTimeout(timer);
      timer = setTimeout(run, COMPOSE_SETTLE_MS);
    };
    dom.addEventListener("compositionend", ended);
    return () => {
      dom.removeEventListener("compositionend", ended);
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps 由调用方给(它们就是 sync 读的那几样)
  }, [editor, ...deps]);
}

/** 比 ProseMirror 收尾组词的 20ms 多等一点。 */
export const COMPOSE_SETTLE_MS = 30;
