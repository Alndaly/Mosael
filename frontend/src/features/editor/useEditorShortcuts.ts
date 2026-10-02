import React from "react";

import type { Sequence } from "@/api/client";
import { frameAt, frameTime, sequenceDuration } from "@/domain/timeline/geometry";
import { isEditorKeyTarget } from "@/features/editor/editorKeys";
import { useEditorStore } from "@/features/editor/editorStore";
import { leaveClipboardToSystem, listenKeys } from "@/lib/shortcuts";

/**
 * 剪辑页的全局快捷键。
 *
 * 只改编辑器自身状态的(播放头、工具、选区……)直接在这里对 store 下手;要发请求改时间线的交给
 * EditorView 传进来的 actions —— mutation 都在那边。按键是否冲着剪辑页来,统一由
 * isEditorKeyTarget 判(见 editorKeys)。
 *
 * 监听只挂一次:actions 与 sequence 每次渲染都换新,经 ref 读最新的,不跟着重挂。
 */
export interface EditorShortcutActions {
  undo: () => void;
  redo: () => void;
  duplicate: () => void;
  copy: () => void;
  cut: () => void;
  paste: () => void;
  moveLayer: (direction: -1 | 1) => void;
  split: () => void;
  deleteSelection: (ripple: boolean) => void;
}

export function useEditorShortcuts(
  root: React.RefObject<Element | null>,
  sequence: Sequence | null,
  actions: EditorShortcutActions,
): void {
  const latest = React.useRef({ sequence, actions });
  latest.current = { sequence, actions };

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isEditorKeyTarget(event, root.current)) return;
      const { sequence: current, actions: act } = latest.current;
      const mod = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();
      const store = useEditorStore.getState();
      if (mod && key === "z") {
        event.preventDefault();
        if (event.shiftKey) act.redo();
        else act.undo();
      } else if (mod && key === "d") {
        event.preventDefault();
        act.duplicate();
      } else if (mod && key === "c") {
        if (leaveClipboardToSystem(event)) return;
        event.preventDefault();
        act.copy();
      } else if (mod && key === "x") {
        if (leaveClipboardToSystem(event)) return;
        event.preventDefault();
        act.cut();
      } else if (mod && key === "v") {
        event.preventDefault();
        act.paste();
      } else if (mod && event.key === "]") {
        event.preventDefault();
        act.moveLayer(1);
      } else if (mod && event.key === "[") {
        event.preventDefault();
        act.moveLayer(-1);
      } else if (!mod && key === "s") {
        event.preventDefault();
        act.split();
      } else if (!mod && key === "a") {
        store.setTool("select");
      } else if (!mod && key === "b") {
        store.setTool("blade");
      } else if (event.code === "Space") {
        event.preventDefault();
        // 停在结尾按空格:从头播。不然播放头原地一动不动,看着像空格失灵。
        const total = current ? sequenceDuration((current.tracks ?? []).flatMap((track) => track.clips ?? [])) : 0;
        if (!store.playing && total > 0 && store.playhead >= total - 1e-6) store.setPlayhead(0);
        store.togglePlaying();
      } else if (!mod && (key === "j" || key === "k" || key === "l")) {
        event.preventDefault();
        store.shuttle(key === "j" ? -1 : key === "l" ? 1 : 0);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        // 按帧号加减,不把 1/fps 一次次浮点累加(累加会漂到两帧之间)。
        const fps = current?.fps ?? 30;
        const step = (event.shiftKey ? 10 : 1) * (event.key === "ArrowLeft" ? -1 : 1);
        store.setPlayhead(frameTime(frameAt(store.playhead, fps) + step, fps));
      } else if (event.key === "Delete" || event.key === "Backspace") {
        if (store.selectedClipIds.length > 0 && current) {
          event.preventDefault();
          act.deleteSelection(event.shiftKey);
        }
      }
    };
    return listenKeys(window, onKeyDown);
  }, [root]);
}
