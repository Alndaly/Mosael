/**
 * 往画布上放文件和文字:从系统里拖进来、粘贴进来。从 BoardCanvas 拆出来的钩子。
 */
import React from "react";
import type { Node, ReactFlowInstance } from "@xyflow/react";

import type { BoardItem } from "@/api/client";
import { isCanvasKeyTarget } from "@/lib/shortcuts";
import { isImportableFile, useFileDrop } from "@/lib/useFileDrop";
import { toNodes } from "@/features/boards/boardCanvasModel";
import { assetItem, clipboardContent, type PlacedAsset } from "@/features/boards/boardPlacement";

export function useBoardFileImport({
  onDropFiles,
  setNodes,
  annotating,
  add,
  rf,
  surface,
  pasteCells,
}: {
  onDropFiles?: (files: File[]) => Promise<PlacedAsset[]>;
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  /** 评论 / 标记模式:画布只收批注,不收东西。 */
  annotating: boolean;
  add: (kind: BoardItem["kind"], extra?: Partial<BoardItem>) => BoardItem;
  rf: React.RefObject<ReactFlowInstance | null>;
  surface: React.RefObject<HTMLDivElement | null>;
  /** 剪贴板里是画板上的几格(⌘C 复制的格子):贴格子,回 true;不是回 false,照旧贴文件 / 文字。 */
  pasteCells?: (clipboard: DataTransfer | null) => boolean;
}) {
  /**
   * 从系统里拖文件进来 —— 传进素材库,再就地摆到落点上。
   *
   * 用仓库现成的 useFileDrop:整块区域拖放的三个坑(子元素边界上的 dragleave 抖动、
   * 浏览器默认打开文件、拖文字也亮提示)它已经处理过了,自己写要再踩一遍。
   *
   * **落点要在 drop 那一刻算**(那时才有鼠标位置),而 useFileDrop 的回调拿不到事件 ——
   * 和工作流那边一样,用一个 ref 把坐标从事件里带出来。
   */
  const dropAt = React.useRef<{ x: number; y: number } | null>(null);
  /** 文件进素材库,回来的每一份按种类各放一格(见 boardPlacement.assetItem)。拖进来和粘贴进来走这同一条。 */
  const importAndPlace = React.useCallback(
    (files: File[], at: { x: number; y: number }) => {
      void onDropFiles?.(files).then((assets) => {
        if (!assets?.length) return;
        setNodes((current) => [
          ...current.map((node) => ({ ...node, selected: false })),
          ...toNodes(assets.map((asset, index) => assetItem(asset, at, index))),
        ]);
      });
    },
    [onDropFiles, setNodes],
  );
  //: 评论 / 标记模式下画布只收批注,不收东西:拖文件进来和粘贴(下面)一样拦住,连「松手放在这里」的提示也不亮。
  const drop = useFileDrop(
    (files) => {
      if (!annotating) importAndPlace(files, dropAt.current ?? { x: 0, y: 0 });
    },
    isImportableFile,
    () => !annotating,
  );

  /**
   * 粘贴到画布上:截图 / 复制的媒体文件先进素材库再各放一格,一段文字落成一张便签,摆在视野中心。
   *
   * **冲着画布来的才接**(isCanvasKeyTarget):在便签里、提示词框里、任何输入框或编辑器里粘贴,是往那里
   * 贴字,不是往画布上放东西;经 Portal 弹出去的菜单、对话框也不算。评论 / 标记模式下不接(拖放同一条)。
   */
  React.useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (event.defaultPrevented || annotating) return;
      if (!isCanvasKeyTarget(event.target, surface.current)) return;
      if (pasteCells?.(event.clipboardData)) {
        event.preventDefault();
        return;
      }
      const content = clipboardContent(event.clipboardData);
      if (!content) return;
      event.preventDefault();
      //: 便签走「添加」那一条(摆在视野中心、加完就选中);素材也摆在视野中心。
      if ("text" in content) {
        add("note", { text: content.text });
        return;
      }
      const instance = rf.current;
      const box = surface.current?.getBoundingClientRect();
      const center = instance && box
        ? instance.screenToFlowPosition({ x: box.left + box.width / 2, y: box.top + box.height / 2 })
        : { x: 0, y: 0 };
      importAndPlace(content.files, center);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [add, importAndPlace, annotating, pasteCells]);

  return { drop, dropAt };
}
