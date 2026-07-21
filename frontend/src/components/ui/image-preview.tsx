import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ExternalLink, X } from "lucide-react";

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
      <DialogPrimitive.Root open={image !== null} onOpenChange={(open) => !open && close()}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="image-preview-overlay" />
          <DialogPrimitive.Content className="image-preview-dialog" aria-describedby={undefined}>
            {image && (
              <>
                <DialogPrimitive.Title className="image-preview-title">{image.title ?? t("imagePreviewTitle")}</DialogPrimitive.Title>
                <div
                  className="image-preview-stage"
                  onPointerDown={(event) => {
                    if (event.target === event.currentTarget) close();
                  }}
                >
                  <img src={image.src} alt={image.title ?? ""} onPointerDown={(event) => event.stopPropagation()} />
                </div>
                <div className="image-preview-actions">
                  <a href={image.src} target="_blank" rel="noreferrer noopener" className="image-preview-action">
                    <ExternalLink size={14} /> {t("openOriginal")}
                  </a>
                  <DialogPrimitive.Close className="image-preview-close" aria-label={t("close")}>
                    <X size={18} />
                  </DialogPrimitive.Close>
                </div>
              </>
            )}
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </ImagePreviewContext.Provider>
  );
}

export function useImagePreview() {
  const value = React.useContext(ImagePreviewContext);
  if (!value) throw new Error("useImagePreview must be used inside ImagePreviewProvider");
  return value;
}
