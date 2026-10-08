/**
 * 全局灯箱的 context 和取它的 hook。
 *
 * **单独一个模块、只依赖 React**(app/contextIdentity.test.ts):context 的身份就是那一次 `createContext` 返回的对象,
 * 它所在的模块被热更新重跑一次就换出一个新的 —— 外层的 ImagePreviewProvider 还是旧的,页面里的 `useImagePreview`
 * 读到新的、是 null,整页报「must be used inside ImagePreviewProvider」。此前它住在 image-preview.tsx 里,而那里引着播放器、
 * 图标按钮、文案表:改一下播放器(media-playback.tsx)素材库就整页挂掉(在开发服务器上实测过)。
 */
import * as React from "react";

export type ImagePreviewItem = {
  src: string;
  title?: string;
  /** 这一项是视频 —— **同一个灯箱,换一种渲染**。另开一个视频弹层的话,关闭、遮罩、
   *  Esc、层级这几件事就要各写一遍,而它们已经在这儿处理过了(包括那条「关掉之后
   *  还接管一会儿点击」的坑)。 */
  video?: boolean;
};

export type ImagePreviewState = ImagePreviewItem & {
  /** 画廊:同场景的全部图片(如生成会话里所有产出)。点开的 src 决定初始位置,
   *  PhotoSlider 自带左右翻页/计数。省略 = 单张预览,老调用方不变。 */
  gallery?: ImagePreviewItem[];
};

export type ImagePreviewContextValue = {
  openImagePreview: (image: ImagePreviewState) => void;
  /** 顶层灯箱是否正在显示。下层 Dialog 用它避免响应同一次 Esc / 外部点击。 */
  isImagePreviewOpen: boolean;
};

export const ImagePreviewContext = React.createContext<ImagePreviewContextValue | null>(null);

export function useImagePreview() {
  const value = React.useContext(ImagePreviewContext);
  if (!value) throw new Error("useImagePreview must be used inside ImagePreviewProvider");
  return value;
}
