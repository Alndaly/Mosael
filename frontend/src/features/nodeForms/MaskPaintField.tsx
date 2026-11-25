import React from "react";
import { Brush, X } from "lucide-react";

import { assetPreviewUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { MaskEditor } from "@/components/generation/MaskEditor";
import { Button } from "@/components/ui/button";
import { FallbackImage } from "@/components/ui/fallback-image";
import { IconButton } from "@/components/ui/icon-button";

/** 图下面还要留多高(那句「改成什么」、按钮、底栏):竖图按「视口高减去它」封顶,弹窗一屏放得下。 */
const BELOW_STAGE = "24rem";

/**
 * 重绘节点(`image_inpaint`,ADR 0110)的蒙版:**主控件**(后端声明 `editor: "mask_paint"`),画板上点「重绘」直接是一个弹窗,它在弹窗主体里。
 *
 * 一张原图,画过的地方压一层主色(蒙版按亮度当遮罩:白 = 要改的地方);右下角浮着一颗「画要重绘的地方」(画过了是「接着画」)。
 * 点开就是 ADR 0057 的那个编辑器,底图是这一张 —— 不另写编辑器(ADR 0107 的蒙版槽用的也是它);存下来是一份新的蒙版素材,
 * 这一格记它的 id。
 */
export function MaskPaintField({
  workspaceId,
  imageAssetId,
  imageName,
  maskAssetId,
  onChange,
}: {
  workspaceId: string;
  /** 要改的那张图(画蒙版时的底图);没有(工作流里接的是上游)就在黑画布上画。 */
  imageAssetId?: string;
  imageName: string;
  maskAssetId?: string;
  onChange: (maskAssetId: string) => void;
}) {
  const t = useI18n();
  const [editing, setEditing] = React.useState(false);
  const [aspect, setAspect] = React.useState<number | null>(null);

  const actions = (
    <>
      <Button variant="outline" size="sm" onClick={() => setEditing(true)} data-mask-paint-open="">
        <Brush size={14} />
        {t(maskAssetId ? "maskPaintContinue" : "maskPaintDraw")}
      </Button>
      {maskAssetId ? (
        <IconButton variant="ghost" size="icon-sm" label={t("maskPaintClear")} onClick={() => onChange("")}>
          <X size={14} />
        </IconButton>
      ) : null}
    </>
  );

  return (
    <div className="grid gap-2" data-mask-paint="">
      {imageAssetId ? (
        <div
          className="relative overflow-hidden rounded-md bg-secondary/40"
          style={aspect ? { width: `min(100%, calc((100dvh - ${BELOW_STAGE}) * ${aspect}))`, aspectRatio: aspect } : { width: "100%" }}
        >
          <FallbackImage
            src={assetPreviewUrl(imageAssetId)}
            alt=""
            draggable={false}
            onLoad={(event) => {
              const image = event.currentTarget;
              if (image.naturalWidth && image.naturalHeight) setAspect(image.naturalWidth / image.naturalHeight);
            }}
            className="block h-full w-full object-fill"
          />
          {maskAssetId ? (
            //: 蒙版按亮度当遮罩:白的地方透出主色,黑的地方什么都没有。
            <div
              data-mask-overlay=""
              aria-hidden
              className="pointer-events-none absolute inset-0 bg-primary/55"
              style={{
                maskImage: `url("${assetPreviewUrl(maskAssetId)}")`,
                maskMode: "luminance",
                maskSize: "100% 100%",
                WebkitMaskImage: `url("${assetPreviewUrl(maskAssetId)}")`,
                WebkitMaskSize: "100% 100%",
              }}
            />
          ) : null}
          {/* 画 / 清掉浮在图的右下角:按钮挨着它要改的那张图,不在图下面另占一行。 */}
          <div data-mask-paint-actions="" className="absolute bottom-2 right-2 flex items-center gap-1 rounded-lg bg-background/85 p-1 shadow-sm backdrop-blur">
            {actions}
          </div>
        </div>
      ) : null}
      {imageAssetId ? null : (
        //: 没有底图(工作流里接的是上游):按钮照常是一行,旁边一句说明。
        <div className="flex min-w-0 items-center gap-1">
          {actions}
          {maskAssetId ? null : <span className="min-w-0 text-ui-xs text-muted-foreground">{t("maskPaintHint")}</span>}
        </div>
      )}
      <MaskEditor
        open={editing}
        onOpenChange={setEditing}
        workspaceId={workspaceId}
        source={imageAssetId ? { assetId: imageAssetId, name: imageName } : null}
        initial={maskAssetId ? { assetId: maskAssetId, name: t("maskPaintLabel") } : null}
        onDone={(saved) => {
          onChange(saved.id);
          setEditing(false);
        }}
      />
    </div>
  );
}
