import React from "react";
import { useQuery } from "@tanstack/react-query";

import { assetPreviewUrl, getAsset } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Chip } from "@/components/ui/chip";
import { FallbackImage } from "@/components/ui/fallback-image";
import { cn } from "@/lib/utils";
import {
  CROP_ASPECTS,
  cropPixels,
  dragCrop,
  fitAspect,
  fractionRatio,
  matchingAspect,
  type CropAspectId,
  type CropBox,
  type CropHandle,
} from "@/features/nodeForms/cropFrame";

/** 图最高摆多高(像素):竖图铺满卡片宽会把面板撑得老长。 */
const STAGE_MAX_HEIGHT = 240;
/** 还没有具体的图(工作流里接的是上游)时按这个宽高比画一块空的底。 */
const BLANK_ASPECT = 4 / 3;
/** 方向键一下挪多少(占原图的比例)。 */
const NUDGE = 0.01;

//: 把手画在框**里面**:框贴着图边时(整张图)画在外面的那一半会被底板裁掉,看着像图边缺了几个口。
//: 四角是 L 形的角标,四边是一小段粗线;能按住的范围比看得见的大一圈。
const HANDLES: { handle: Exclude<CropHandle, "move">; hit: string; mark: string }[] = [
  { handle: "nw", hit: "left-0 top-0 h-4 w-4 cursor-nwse-resize", mark: "left-0 top-0 h-3 w-3 border-l-[3px] border-t-[3px]" },
  { handle: "ne", hit: "right-0 top-0 h-4 w-4 cursor-nesw-resize", mark: "right-0 top-0 h-3 w-3 border-r-[3px] border-t-[3px]" },
  { handle: "sw", hit: "bottom-0 left-0 h-4 w-4 cursor-nesw-resize", mark: "bottom-0 left-0 h-3 w-3 border-b-[3px] border-l-[3px]" },
  { handle: "se", hit: "bottom-0 right-0 h-4 w-4 cursor-nwse-resize", mark: "bottom-0 right-0 h-3 w-3 border-b-[3px] border-r-[3px]" },
  { handle: "n", hit: "left-1/2 top-0 h-3 w-8 -translate-x-1/2 cursor-ns-resize", mark: "left-1 right-1 top-0 h-[3px] bg-white" },
  { handle: "s", hit: "bottom-0 left-1/2 h-3 w-8 -translate-x-1/2 cursor-ns-resize", mark: "bottom-0 left-1 right-1 h-[3px] bg-white" },
  { handle: "w", hit: "left-0 top-1/2 h-8 w-3 -translate-y-1/2 cursor-ew-resize", mark: "bottom-1 left-0 top-1 w-[3px] bg-white" },
  { handle: "e", hit: "right-0 top-1/2 h-8 w-3 -translate-y-1/2 cursor-ew-resize", mark: "bottom-1 right-0 top-1 w-[3px] bg-white" },
];

const ASPECT_LABELS: Partial<Record<CropAspectId, MessageKey>> = { free: "cropAspectFree", original: "cropAspectOriginal" };

/**
 * 裁切节点(`image_crop`,ADR 0110)的框:**一个控件改四格**(后端声明 `editor: "crop_frame"`,另外三格 `edited_by` 它)。
 * 工作流检查器、画板的能力面板(摆在面板主体里,见 stageEditors)用的是同一个控件。
 *
 * 原图铺满卡片的宽(竖图封顶 STAGE_MAX_HEIGHT),框外压暗;拖框里挪、拖四角四边改大小,方向键挪一点。左下角的读数是
 * 切出来的像素尺寸。下面一排比例:点一下摆好这个比例下最大的居中框,之后拖的时候保持它 —— 比例只是控件上的锁,不进数据。
 */
export function CropFrameField({
  imageAssetId,
  box,
  onChange,
}: {
  /** 要裁的那张图;没有(工作流里接的是上游)就画一块空的底,框照样能摆。 */
  imageAssetId?: string;
  box: CropBox;
  onChange: (box: CropBox) => void;
}) {
  const t = useI18n();
  const asset = useQuery({
    queryKey: assetKeys.detail(imageAssetId ?? ""),
    queryFn: () => getAsset(imageAssetId ?? ""),
    enabled: Boolean(imageAssetId),
  });
  const [natural, setNatural] = React.useState<{ width: number; height: number } | null>(null);
  const info = (asset.data?.media_info ?? {}) as { width?: unknown; height?: unknown };
  const size =
    typeof info.width === "number" && typeof info.height === "number" && info.width > 0 && info.height > 0
      ? { width: info.width, height: info.height }
      : natural;
  const imageAspect = size ? size.width / size.height : BLANK_ASPECT;
  //: 锁着哪个比例:进来时照框此刻的样子认(上回锁 1:1 摆的框,回来还锁着 1:1)。
  const [aspect, setAspect] = React.useState<CropAspectId | null>(null);
  const locked = aspect ?? matchingAspect(box, imageAspect);
  const ratio = fractionRatio(locked, imageAspect);
  const pixels = cropPixels(box, size);

  const stage = React.useRef<HTMLDivElement>(null);
  const held = React.useRef<{ handle: CropHandle; x: number; y: number; start: CropBox } | null>(null);

  const grab = (handle: CropHandle) => (event: React.PointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    //: 认出来的比例到这里定下:拖着拖着恰好拖成 1:1,不该从此被锁住。
    if (aspect === null) setAspect(locked);
    held.current = { handle, x: event.clientX, y: event.clientY, start: box };
  };
  const move = (event: React.PointerEvent) => {
    const hold = held.current;
    const rect = stage.current?.getBoundingClientRect();
    if (!hold || !rect?.width || !rect.height) return;
    onChange(dragCrop(hold.start, hold.handle, (event.clientX - hold.x) / rect.width, (event.clientY - hold.y) / rect.height, ratio));
  };
  const release = () => {
    held.current = null;
  };
  const nudge = (event: React.KeyboardEvent) => {
    const step = { ArrowLeft: [-NUDGE, 0], ArrowRight: [NUDGE, 0], ArrowUp: [0, -NUDGE], ArrowDown: [0, NUDGE] }[event.key];
    if (!step) return;
    event.preventDefault();
    onChange(dragCrop(box, "move", step[0], step[1], ratio));
  };
  const pickAspect = (id: CropAspectId) => {
    setAspect(id);
    const next = fractionRatio(id, imageAspect);
    if (next !== null) onChange(fitAspect(next));
  };

  return (
    <div className="grid gap-2" data-crop-frame="">
      <div
        ref={stage}
        className="relative touch-none select-none overflow-hidden rounded-md bg-secondary/40"
        style={{ width: `min(100%, ${Math.round(STAGE_MAX_HEIGHT * imageAspect)}px)`, aspectRatio: imageAspect }}
        onPointerMove={move}
        onPointerUp={release}
        onPointerCancel={release}
      >
        {imageAssetId ? (
          <FallbackImage
            src={assetPreviewUrl(imageAssetId)}
            alt=""
            draggable={false}
            onLoad={(event) => {
              const image = event.currentTarget;
              if (image.naturalWidth && image.naturalHeight) setNatural({ width: image.naturalWidth, height: image.naturalHeight });
            }}
            className="pointer-events-none absolute inset-0 h-full w-full object-fill"
          />
        ) : null}
        <div
          role="group"
          tabIndex={0}
          aria-label={t("cropFrameLabel")}
          data-crop-box=""
          onPointerDown={grab("move")}
          onKeyDown={nudge}
          className="absolute cursor-move outline-none ring-1 ring-white/90 focus-visible:ring-2 focus-visible:ring-primary"
          style={{
            left: `${box.x * 100}%`,
            top: `${box.y * 100}%`,
            width: `${box.width * 100}%`,
            height: `${box.height * 100}%`,
            //: 框外压暗:一圈很大的阴影,被底板的 overflow-hidden 裁掉 —— 不另画四块遮罩。
            boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.5)",
          }}
        >
          {HANDLES.map(({ handle, hit, mark }) => (
            <span key={handle} data-crop-handle={handle} onPointerDown={grab(handle)} className={cn("absolute", hit)}>
              <span aria-hidden className={cn("absolute border-white", mark)} />
            </span>
          ))}
        </div>
        {pixels ? (
          //: 读数压在图的左下角(和打光方向球的读数同一个位置):放在比例那一排后面会折到下一行,被面板底栏压住。
          <span
            data-crop-readout=""
            className="pointer-events-none absolute bottom-1 left-1 z-10 rounded bg-black/55 px-1 text-ui-xs tabular-nums text-white"
          >
            {t("cropReadout").replace("{width}", String(pixels.width)).replace("{height}", String(pixels.height))}
          </span>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-1" role="group" aria-label={t("cropAspects")}>
        {CROP_ASPECTS.map((one) => (
          <Chip key={one.id} selected={locked === one.id} onClick={() => pickAspect(one.id)}>
            {ASPECT_LABELS[one.id] ? t(ASPECT_LABELS[one.id]!) : one.id}
          </Chip>
        ))}
      </div>
    </div>
  );
}
