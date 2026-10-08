import type { ImagePreviewItem } from "@/components/app/imagePreviewContext";

/**
 * 不在 React 树里的界面也要开同一个灯箱。
 *
 * 编辑器的节点视图(笔记里的图片)是手写的 DOM,够不着 `useImagePreview` 那份上下文;为它另开一个弹层,
 * 关闭、Esc、层级、焦点回来这几件事又得各写一遍。所以从自己身上派发一个会冒泡的事件,
 * 由 ImagePreviewProvider 在 document 上接住 —— 和 React 里点开走的是同一条路。
 *
 * 单独成一个文件:很多测试把 image-preview 整个替换成桩,这里不该跟着变成空的。
 */
export const IMAGE_PREVIEW_EVENT = "mosael:image-preview";

export type ImagePreviewRequest = ImagePreviewItem & { gallery?: ImagePreviewItem[] };

/** 从 `from` 这个元素请求打开灯箱(它就是关掉之后焦点回去的地方)。 */
export function requestImagePreview(from: EventTarget, image: ImagePreviewRequest): void {
  from.dispatchEvent(new CustomEvent<ImagePreviewRequest>(IMAGE_PREVIEW_EVENT, { bubbles: true, detail: image }));
}
