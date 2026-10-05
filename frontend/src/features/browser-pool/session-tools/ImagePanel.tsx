import { Check, Loader2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { ViewFullSizeButton } from "@/components/app/view-full-size";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export interface PageImageItem {
  url: string;
  width: number;
  height: number;
  alt: string;
  /** 取图的结果:还在取 / 取到了(缩略图用本地的 object URL)/ 取不到。 */
  state: "loading" | "ready" | "failed";
  preview?: string;
}

/**
 * 侧栏「页面图片」:缩略图网格,点一下勾选 / 取消;角上的「看大图」(悬停 / 键盘走到时露出来)开大图,取到了的这几张成组翻。缩略图和大图都用主进程
 * 取来的字节(带这个档案的登录态和来源页 Referer)—— 直接拿地址给 `<img>` 的话,防盗链的站点只回一张「禁止外链」。
 * 取不到的那几张不能勾、也没有大图。大图开着时网页让到窗口外(见 components/ui/nativeViewAside),不被它盖住。
 */
export function ImagePanel({
  images,
  loading,
  selected,
  onToggle,
}: {
  images: PageImageItem[];
  loading: boolean;
  selected: ReadonlySet<string>;
  onToggle: (url: string) => void;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  if (loading && images.length === 0) {
    return (
      <p className="m-0 flex items-center gap-2 text-ui-sm text-muted-foreground">
        <Loader2 size={14} className="animate-mosael-spin" /> {t("browserToolsLoading")}
      </p>
    );
  }
  if (images.length === 0) {
    return <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground" data-images-empty="">{t("browserToolsImagesEmpty")}</p>;
  }
  const gallery = images.flatMap((one) => (one.state === "ready" && one.preview ? [{ src: one.preview, title: one.alt || one.url }] : []));
  return (
    <ul className="m-0 grid list-none grid-cols-3 gap-2 p-0" data-image-grid="">
      {images.map((image) => {
        const picked = selected.has(image.url);
        const viewable = image.state === "ready" && Boolean(image.preview);
        return (
          <li key={image.url} className="group/preview relative">
            {/* 悬停:图的说明(没有就是地址)和原始尺寸。 */}
            <Hint label={image.alt || image.url} hint={`${image.width}×${image.height}`}>
            <button
              type="button"
              disabled={image.state !== "ready"}
              aria-pressed={picked}
              onClick={() => onToggle(image.url)}
              data-page-image={image.state}
              className={cn(
                "relative grid aspect-square w-full cursor-pointer place-items-center overflow-hidden rounded-md border bg-panel-inset p-0 disabled:cursor-default",
                picked ? "border-primary ring-2 ring-primary" : "border-border",
              )}
            >
              {image.state === "ready" && image.preview ? (
                <img src={image.preview} alt={image.alt} className="h-full w-full object-cover" draggable={false} />
              ) : image.state === "loading" ? (
                <Loader2 size={14} className="animate-mosael-spin text-muted-foreground" />
              ) : (
                <span className="px-1 text-center text-ui-xs text-muted-foreground">{t("browserToolsImageUnavailable")}</span>
              )}
              {picked && (
                <span className="absolute right-1 top-1 grid h-4 w-4 place-items-center rounded-full bg-primary text-primary-foreground">
                  <Check size={11} />
                </span>
              )}
            </button>
            </Hint>
            {viewable && (
              <ViewFullSizeButton
                name={image.alt || image.url}
                className="bottom-1 right-1"
                onOpen={() => openImagePreview({ src: image.preview!, title: image.alt || image.url, gallery })}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}
