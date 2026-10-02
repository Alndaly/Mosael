import React from "react";

import type { Sequence } from "@/api/client";
import { frameAt, frameTime, sequenceDuration, snapToFrame } from "@/domain/timeline/geometry";
import { adjacentEditPoint, editPoints } from "@/domain/timeline/editTargets";
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
  /** ⇧⌘K:播放头下所有未锁定轨各切一刀。 */
  splitAll: () => void;
  /** , / .:选中的片段左 / 右挪 frames 帧(⇧ 为 10 帧)。 */
  nudge: (frames: number) => void;
  /** Q(start)/ W(end):波纹修剪上一个 / 下一个编辑点到播放头。 */
  rippleTrim: (edge: "start" | "end") => void;
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
      } else if (mod && event.shiftKey && key === "k") {
        // ⇧⌘K(Premiere 的「所有轨道添加编辑点」)。⌘K 本身是全局命令面板,不抢。
        event.preventDefault();
        act.splitAll();
      } else if (mod && key === "a") {
        // ⌘A:选中所有未锁定轨上的片段(锁定的轨本来就选不中、拖不动)。
        event.preventDefault();
        store.selectClips(
          (current?.tracks ?? []).filter((track) => !track.locked).flatMap((track) => (track.clips ?? []).map((item) => item.id)),
        );
      } else if (mod && event.key === "]") {
        event.preventDefault();
        act.moveLayer(1);
      } else if (mod && event.key === "[") {
        event.preventDefault();
        act.moveLayer(-1);
      } else if (!mod && key === "s") {
        event.preventDefault();
        act.split();
      } else if (!mod && key === "n") {
        store.toggleSnap();
      } else if (!mod && key === "a") {
        store.setTool("select");
      } else if (!mod && key === "b") {
        store.setTool("blade");
      } else if (event.code === "Space") {
        event.preventDefault();
        // 停在结尾按空格:从头播。不然播放头原地一动不动,看着像空格失灵。
        const total = totalOf(current);
        if (!store.playing && total > 0 && store.playhead >= total - 1e-6) store.setPlayhead(0);
        store.togglePlaying();
      } else if (!mod && !event.altKey && (key === "i" || key === "o")) {
        // 入点 / 出点打在播放头所在的那一帧上。
        const at = snapToFrame(store.playhead, current?.fps ?? 30);
        if (key === "i") store.setMarkIn(at);
        else store.setMarkOut(at);
      } else if (!mod && event.altKey && event.code === "KeyX") {
        // ⌥X 清掉入出点(macOS 上 ⌥X 的 key 是 "≈",认物理键)。
        event.preventDefault();
        store.clearMarks();
      } else if (!mod && (event.key === "," || event.key === "." || event.key === "<" || event.key === ">")) {
        // ⇧ 时 key 变成 < / >(美式键盘),一并认。
        if (store.selectedClipIds.length === 0) return;
        event.preventDefault();
        const left = event.key === "," || event.key === "<";
        act.nudge((event.shiftKey ? 10 : 1) * (left ? -1 : 1));
      } else if (!mod && (key === "q" || key === "w")) {
        event.preventDefault();
        act.rippleTrim(key === "q" ? "start" : "end");
      } else if (!mod && (key === "j" || key === "k" || key === "l")) {
        event.preventDefault();
        store.shuttle(key === "j" ? -1 : key === "l" ? 1 : 0);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        // 按帧号加减,不把 1/fps 一次次浮点累加(累加会漂到两帧之间)。
        const fps = current?.fps ?? 30;
        const step = (event.shiftKey ? 10 : 1) * (event.key === "ArrowLeft" ? -1 : 1);
        store.setPlayhead(frameTime(frameAt(store.playhead, fps) + step, fps));
      } else if (!mod && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        // 上一个 / 下一个编辑点(任一轨上片段的头尾)。正停在某点上时跳过它:容差半帧。
        event.preventDefault();
        const fps = current?.fps ?? 30;
        const target = adjacentEditPoint(
          editPoints(current?.tracks ?? []),
          store.playhead,
          event.key === "ArrowUp" ? -1 : 1,
          0.5 / fps,
        );
        if (target !== null) store.setPlayhead(target);
      } else if (!mod && (event.key === "Home" || event.key === "End")) {
        event.preventDefault();
        store.setPlayhead(event.key === "Home" ? 0 : totalOf(current));
      } else if (event.key === "Escape") {
        // 拖动 / 修剪中的 Esc 由时间线在捕获阶段接走(取消那次拖动),到不了这里。
        // 这里的 Esc:先撤掉剪切标记(反悔了),再按一次清空选区。
        if (store.clipboard?.cut) store.setClipboard(null);
        else if (store.selectedClipIds.length > 0) store.selectClips([]);
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

function totalOf(sequence: Sequence | null): number {
  return sequenceDuration((sequence?.tracks ?? []).flatMap((track) => track.clips ?? []));
}
