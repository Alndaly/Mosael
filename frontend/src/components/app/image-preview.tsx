import * as React from "react";
import { ExternalLink } from "lucide-react";
import { PhotoSlider } from "react-photo-view";
import "react-photo-view/dist/react-photo-view.css";

import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

type ImagePreviewImage = {
  src: string;
  title?: string;
};

type ImagePreviewState = ImagePreviewImage & {
  /** 画廊:同场景的全部图片(如生成会话里所有产出)。点开的 src 决定初始位置,
   *  PhotoSlider 自带左右翻页/计数。省略 = 单张预览,老调用方不变。 */
  gallery?: ImagePreviewImage[];
};

type ImagePreviewContextValue = {
  openImagePreview: (image: ImagePreviewState) => void;
};

const ImagePreviewContext = React.createContext<ImagePreviewContextValue | null>(null);

export function ImagePreviewProvider({ children }: { children: React.ReactNode }) {
  const t = useI18n();
  const [images, setImages] = React.useState<ImagePreviewImage[]>([]);
  const [index, setIndex] = React.useState(0);
  const [visible, setVisible] = React.useState(false);

  const openImagePreview = React.useCallback((next: ImagePreviewState) => {
    const list = next.gallery?.length ? next.gallery : [{ src: next.src, title: next.title }];
    const at = list.findIndex((item) => item.src === next.src);
    setImages(list);
    setIndex(at >= 0 ? at : 0);
    setVisible(true);
  }, []);
  const close = React.useCallback(() => setVisible(false), []);
  const reset = React.useCallback(() => setImages([]), []);

  const value = React.useMemo<ImagePreviewContextValue>(() => ({ openImagePreview }), [openImagePreview]);

  return (
    <ImagePreviewContext.Provider value={value}>
      {children}
      <PhotoSlider
        images={images.map((item) => ({
          key: item.src,
          src: item.src,
          overlay: item.title ?? t("imagePreviewTitle"),
        }))}
        index={index}
        onIndexChange={setIndex}
        visible={visible && images.length > 0}
        onClose={close}
        afterClose={reset}
        // react-photo-view 自带样式不在 cascade layer 里,会压过 utilities layer——覆盖其内部结构一律加 `!`。
        // 关闭后这层还会在 DOM 里留一会儿(等它自己的收尾动画),期间虽然看不见却仍然接管
        // 点击 —— 表现为「关掉大图后有一小段时间画布点不动、节点拖不了」。不可见就不该拦事件。
        className={cn(
          !visible && "pointer-events-none!",
          "z-[150]! [&_.PhotoView-Slider\_\_BannerWrap]:h-12! [&_.PhotoView-Slider\_\_BannerWrap]:bg-[linear-gradient(to_bottom,rgb(0_0_0/0.42),transparent)]! [&_.PhotoView-Slider\_\_Counter]:font-mono! [&_.PhotoView-Slider\_\_Counter]:text-ui-xs! [&_.PhotoView-Slider\_\_Counter]:text-[rgb(255_255_255/0.68)]! [&_.PhotoView-Slider\_\_toolbarIcon]:h-9! [&_.PhotoView-Slider\_\_toolbarIcon]:w-9! [&_.PhotoView-Slider\_\_toolbarIcon]:text-[rgb(255_255_255/0.82)]! [&_:is(.PhotoView-Slider\_\_ArrowLeft,.PhotoView-Slider\_\_ArrowRight)]:text-[rgb(255_255_255/0.78)]!",
        )}
        maskClassName="will-change-[opacity]"
        photoClassName="rounded-lg will-change-[transform,opacity] [outline:1px_solid_rgb(255_255_255/0.12)]"
        maskOpacity={0.88}
        toolbarRender={({ images, index }) => {
          const src = images[index]?.src;
          if (!src) return null;
          return (
            <a
              href={src}
              target="_blank"
              rel="noreferrer noopener"
              className="mr-2 inline-flex min-h-[30px] items-center gap-1.5 rounded-full border border-[rgb(255_255_255/0.18)] bg-[rgb(255_255_255/0.12)] px-[11px] text-xs text-white no-underline hover:bg-[rgb(255_255_255/0.2)]"
              onClick={(event) => event.stopPropagation()}
            >
              <ExternalLink size={14} /> {t("openOriginal")}
            </a>
          );
        }}
        overlayRender={({ overlay }) =>
          overlay ? (
            <div className="fixed bottom-[22px] left-1/2 max-w-[min(760px,calc(100vw-64px))] -translate-x-1/2 truncate rounded-full border border-[rgb(255_255_255/0.14)] bg-[rgb(0_0_0/0.38)] px-[13px] py-[7px] text-ui-sm font-semibold text-white backdrop-blur-[10px]">
              {overlay}
            </div>
          ) : null
        }
      />
    </ImagePreviewContext.Provider>
  );
}

export function useImagePreview() {
  const value = React.useContext(ImagePreviewContext);
  if (!value) throw new Error("useImagePreview must be used inside ImagePreviewProvider");
  return value;
}
