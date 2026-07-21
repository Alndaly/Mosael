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

  const openImagePreview = React.useCallback((next: ImagePreviewState) => setImage(next), []);
  const close = React.useCallback(() => setImage(null), []);

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
        visible={image !== null}
        onClose={close}
        className="mibu-photo-preview"
        maskClassName="mibu-photo-preview-mask"
        photoClassName="mibu-photo-preview-photo"
        maskOpacity={0.88}
        toolbarRender={({ images, index }) => {
          const src = images[index]?.src;
          if (!src) return null;
          return (
            <a
              href={src}
              target="_blank"
              rel="noreferrer noopener"
              className="mibu-photo-preview-open"
              onClick={(event) => event.stopPropagation()}
            >
              <ExternalLink size={14} /> {t("openOriginal")}
            </a>
          );
        }}
        overlayRender={({ overlay }) =>
          overlay ? <div className="mibu-photo-preview-caption">{overlay}</div> : null
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
