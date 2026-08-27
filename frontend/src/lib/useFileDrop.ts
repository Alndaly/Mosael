import React from "react";

/**
 * 往整块区域上拖文件。
 *
 * 整页拖放和「一个小方框收文件」不是一回事,坑也不同:
 *
 * - **dragleave 会在子元素边界上触发**。整页有几十个子元素,鼠标从卡片挪到卡片就会
 *   收到一串 enter/leave —— 只按事件计数的话,提示会疯狂闪。这里用 relatedTarget
 *   判断是不是真的离开了容器。
 * - **浏览器默认会打开被拖进来的文件**,把整个应用换成那个视频。必须在 dragover 上
 *   preventDefault,而且要在**容器**上拦,不能只在最里层。
 * - 拖的可能是一段文字或一个链接。只在**真的带文件**时才亮提示,否则拖选一段文字
 *   划过页面都会闪一下。
 */
export interface FileDrop {
  /** 正拖着文件悬在上面。用它渲染提示。 */
  active: boolean;
  /** 摊到容器上的事件处理。 */
  handlers: {
    onDragOver: (event: React.DragEvent) => void;
    onDragEnter: (event: React.DragEvent) => void;
    onDragLeave: (event: React.DragEvent) => void;
    onDrop: (event: React.DragEvent) => void;
  };
}

/** 这次拖拽里有没有文件(而不是文字/链接)。 */
function carriesFiles(event: React.DragEvent): boolean {
  const types = event.dataTransfer?.types;
  return types ? Array.from(types).includes("Files") : false;
}

export function useFileDrop(onFiles: (files: File[]) => void, accept?: (file: File) => boolean): FileDrop {
  const [active, setActive] = React.useState(false);

  return {
    active,
    handlers: {
      onDragOver: (event) => {
        if (!carriesFiles(event)) return;
        // 不拦的话浏览器会直接打开这个文件,把整个应用顶掉。
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      },
      onDragEnter: (event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        setActive(true);
      },
      onDragLeave: (event) => {
        // 只有**真的离开了容器**才熄灭。子元素之间移动时 relatedTarget 仍在容器内 ——
        // 不判这一下,鼠标扫过几十张卡片,提示就闪几十次。
        const next = event.relatedTarget as Node | null;
        if (next && event.currentTarget.contains(next)) return;
        setActive(false);
      },
      onDrop: (event) => {
        if (!carriesFiles(event)) return;
        event.preventDefault();
        setActive(false);
        const files = Array.from(event.dataTransfer.files ?? []);
        const kept = accept ? files.filter(accept) : files;
        if (kept.length > 0) onFiles(kept);
      },
    },
  };
}

/** 能进素材库的:视频、图片、音频。别的(比如一份 PDF)直接忽略,不弹错。 */
export function isMediaFile(file: File): boolean {
  return /^(video|image|audio)\//.test(file.type);
}
