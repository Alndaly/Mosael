import * as React from "react";
import { ExternalLink } from "lucide-react";
import { PhotoSlider } from "react-photo-view";
import "react-photo-view/dist/react-photo-view.css";

import { useI18n } from "@/app/preferences";

type ImagePreviewState = {
  src: string;
  title?: string;
};

type ImagePreviewContextValue = {
  openImagePreview: (image: ImagePreviewState) => void;
};

const ImagePreviewContext = React.createContext<ImagePreviewContextValue | null>(null);

export function ImagePreviewProvider({ children }: { children: React.ReactNode }) {
  const t = useI18n();
  const [image, setImage] = React.useState<ImagePreviewState | null>(null);
  const [visible, setVisible] = React.useState(false);

  const openImagePreview = React.useCallback((next: ImagePreviewState) => {
    setImage(next);
    setVisible(true);
  }, []);
  const close = React.useCallback(() => setVisible(false), []);
  const reset = React.useCallback(() => setImage(null), []);

  const value = React.useMemo<ImagePreviewContextValue>(() => ({ openImagePreview }), [openImagePreview]);

  return (
    <ImagePreviewContext.Provider value={value}>
      {children}
      <PhotoSlider
        images={
          image
            ? [
                {
                  key: image.src,
                  src: image.src,
                  overlay: image.title ?? t("imagePreviewTitle"),
                },
              ]
            : []
        }
        visible={visible && image !== null}
        onClose={close}
        afterClose={reset}
        // react-photo-view 自带样式不在 cascade layer 里,会压过 utilities layer——覆盖其内部结构一律加 `!`。
        className="z-[150]! [&_.PhotoView-Slider\_\_BannerWrap]:h-12! [&_.PhotoView-Slider\_\_BannerWrap]:bg-[linear-gradient(to_bottom,rgb(0_0_0/0.42),transparent)]! [&_.PhotoView-Slider\_\_Counter]:font-mono! [&_.PhotoView-Slider\_\_Counter]:text-[11px]! [&_.PhotoView-Slider\_\_Counter]:text-[rgb(255_255_255/0.68)]! [&_.PhotoView-Slider\_\_toolbarIcon]:h-9! [&_.PhotoView-Slider\_\_toolbarIcon]:w-9! [&_.PhotoView-Slider\_\_toolbarIcon]:text-[rgb(255_255_255/0.82)]! [&_:is(.PhotoView-Slider\_\_ArrowLeft,.PhotoView-Slider\_\_ArrowRight)]:text-[rgb(255_255_255/0.78)]!"
        maskClassName="will-change-[opacity]"
        photoClassName="rounded-[10px] will-change-[transform,opacity] [outline:1px_solid_rgb(255_255_255/0.12)]"
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
            <div className="fixed bottom-[22px] left-1/2 max-w-[min(760px,calc(100vw-64px))] -translate-x-1/2 truncate rounded-full border border-[rgb(255_255_255/0.14)] bg-[rgb(0_0_0/0.38)] px-[13px] py-[7px] text-[12.5px] font-semibold text-white backdrop-blur-[10px]">
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
