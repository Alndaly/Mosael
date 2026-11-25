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

/** 还没有具体的图(工作流里接的是上游)时按这个宽高比画一块空的底。 */
const BLANK_ASPECT = 4 / 3;
/** 方向键一下挪多少(占原图的比例)。 */
const NUDGE = 0.01;

//: 把手画在框**里面**:框贴着图边时(整张图)画在外面的那一半会被底板裁掉,看着像图边缺了几个口。
//: 四角是 L 形的角标,四边是一小段粗线;能按住的范围比看得见的大一圈。
const HANDLES: { handle: Exclude<CropHandle, "move">; hit: string; mark: string }[] = [
  { handle: "nw", hit: "left-0 top-0 h-5 w-5 cursor-nwse-resize", mark: "left-0 top-0 h-4 w-4 border-l-[3px] border-t-[3px]" },
  { handle: "ne", hit: "right-0 top-0 h-5 w-5 cursor-nesw-resize", mark: "right-0 top-0 h-4 w-4 border-r-[3px] border-t-[3px]" },
  { handle: "sw", hit: "bottom-0 left-0 h-5 w-5 cursor-nesw-resize", mark: "bottom-0 left-0 h-4 w-4 border-b-[3px] border-l-[3px]" },
  { handle: "se", hit: "bottom-0 right-0 h-5 w-5 cursor-nwse-resize", mark: "bottom-0 right-0 h-4 w-4 border-b-[3px] border-r-[3px]" },
  { handle: "n", hit: "left-1/2 top-0 h-4 w-10 -translate-x-1/2 cursor-ns-resize", mark: "left-1 right-1 top-0 h-[3px] bg-white" },
  { handle: "s", hit: "bottom-0 left-1/2 h-4 w-10 -translate-x-1/2 cursor-ns-resize", mark: "bottom-0 left-1 right-1 h-[3px] bg-white" },
  { handle: "w", hit: "left-0 top-1/2 h-10 w-4 -translate-y-1/2 cursor-ew-resize", mark: "bottom-1 left-0 top-1 w-[3px] bg-white" },
  { handle: "e", hit: "right-0 top-1/2 h-10 w-4 -translate-y-1/2 cursor-ew-resize", mark: "bottom-1 right-0 top-1 w-[3px] bg-white" },
];

const ASPECT_LABELS: Partial<Record<CropAspectId, MessageKey>> = { free: "cropAspectFree", original: "cropAspectOriginal" };

type Size = { width: number; height: number };

/** 要裁的那张图有多大:素材的 media_info,读不到就等图加载完按它的像素认;都没有是 null。 */
function useImageSize(imageAssetId: string | undefined) {
  const asset = useQuery({
    queryKey: assetKeys.detail(imageAssetId ?? ""),
    queryFn: () => getAsset(imageAssetId ?? ""),
    enabled: Boolean(imageAssetId),
  });
  const [natural, setNatural] = React.useState<Size | null>(null);
  const info = (asset.data?.media_info ?? {}) as { width?: unknown; height?: unknown };
  const size =
    typeof info.width === "number" && typeof info.height === "number" && info.width > 0 && info.height > 0
      ? { width: info.width, height: info.height }
      : natural;
  return { size, setNatural };
}

function readout(t: ReturnType<typeof useI18n>, pixels: Size) {
  return t("cropReadout").replace("{width}", String(pixels.width)).replace("{height}", String(pixels.height));
}

/**
 * 裁切节点(`image_crop`,ADR 0110)的框:**一个控件改四格**(后端声明 `editor: "crop_frame"`,另外三格 `edited_by` 它)。
 * 画板上点操作条上的「裁切」直接是一个弹窗(见 stageEditors 的 `opens`),工作流检查器里是表单的一行 —— 同一个控件。
 *
 * 原图尽量大(宽铺满,竖图按视口高封顶),框外压暗;拖框里挪、拖四角四边改大小,方向键挪一点。下面一排比例:点一下摆好
 * 这个比例下最大的居中框,之后拖的时候保持它 —— 比例只是控件上的锁,不进数据。右边是切出来的像素尺寸。
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
  const { size, setNatural } = useImageSize(imageAssetId);
  const imageAspect = size ? size.width / size.height : BLANK_ASPECT;
  //: 锁着哪个比例:进来时照框此刻的样子认(上回锁 1:1 摆的框,回来还锁着 1:1);第一次拖的时候定下来 ——
  //: 拖着拖着恰好拖成 1:1,不该从此被锁住。
  const [aspect, setAspect] = React.useState<CropAspectId | null>(null);
  const locked = aspect ?? matchingAspect(box, imageAspect);
  const pixels = cropPixels(box, size);
  const pickAspect = (id: CropAspectId) => {
    setAspect(id);
    const next = fractionRatio(id, imageAspect);
    if (next !== null) onChange(fitAspect(next));
  };

  return (
    <div className="grid gap-2" data-crop-frame="">
      <div className="grid justify-items-center">
        <div className="w-full" style={{ maxWidth: `min(100%, calc((100dvh - 20rem) * ${imageAspect}))` }}>
          <CropStage
            imageAssetId={imageAssetId}
            size={size}
            onNatural={setNatural}
            box={box}
            ratio={fractionRatio(locked, imageAspect)}
            onGrab={() => {
              if (aspect === null) setAspect(locked);
            }}
            onChange={onChange}
          />
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-1" role="group" aria-label={t("cropAspects")}>
        {CROP_ASPECTS.map((one) => (
          <Chip key={one.id} selected={locked === one.id} onClick={() => pickAspect(one.id)}>
            {ASPECT_LABELS[one.id] ? t(ASPECT_LABELS[one.id]!) : one.id}
          </Chip>
        ))}
        {pixels ? (
          <span data-crop-readout="" className="ml-auto text-ui-xs tabular-nums text-muted-foreground">
            {readout(t, pixels)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/**
 * 一张图 + 框。给了 `onChange` 就能拖,没给就只是看:框外压暗、框照画,没有把手。
 * 图按原图的宽高比铺满它所在那一格的宽。
 */
function CropStage({
  imageAssetId,
  size,
  onNatural,
  box,
  ratio = null,
  onGrab,
  onChange,
}: {
  imageAssetId?: string;
  size: Size | null;
  onNatural: (size: Size) => void;
  box: CropBox;
  /** 锁着的比例(比例空间的宽 / 高);null 不锁。 */
  ratio?: number | null;
  onGrab?: () => void;
  onChange?: (box: CropBox) => void;
}) {
  const t = useI18n();
  const imageAspect = size ? size.width / size.height : BLANK_ASPECT;
  const stage = React.useRef<HTMLDivElement>(null);
  const held = React.useRef<{ handle: CropHandle; x: number; y: number; start: CropBox } | null>(null);
  const editable = Boolean(onChange);

  const grab = (handle: CropHandle) => (event: React.PointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    onGrab?.();
    held.current = { handle, x: event.clientX, y: event.clientY, start: box };
  };
  const move = (event: React.PointerEvent) => {
    const hold = held.current;
    const rect = stage.current?.getBoundingClientRect();
    if (!hold || !onChange || !rect?.width || !rect.height) return;
    onChange(dragCrop(hold.start, hold.handle, (event.clientX - hold.x) / rect.width, (event.clientY - hold.y) / rect.height, ratio));
  };
  const release = () => {
    held.current = null;
  };
  const nudge = (event: React.KeyboardEvent) => {
    const step = { ArrowLeft: [-NUDGE, 0], ArrowRight: [NUDGE, 0], ArrowUp: [0, -NUDGE], ArrowDown: [0, NUDGE] }[event.key];
    if (!step || !onChange) return;
    event.preventDefault();
    onChange(dragCrop(box, "move", step[0], step[1], ratio));
  };

  return (
    <div
      ref={stage}
      data-crop-stage=""
      className={cn("relative w-full overflow-hidden rounded-md bg-secondary/40", editable && "touch-none select-none")}
      style={{ aspectRatio: imageAspect }}
      onPointerMove={editable ? move : undefined}
      onPointerUp={editable ? release : undefined}
      onPointerCancel={editable ? release : undefined}
    >
      {imageAssetId ? (
        <FallbackImage
          src={assetPreviewUrl(imageAssetId)}
          alt=""
          draggable={false}
          onLoad={(event) => {
            const image = event.currentTarget;
            if (!size && image.naturalWidth && image.naturalHeight) onNatural({ width: image.naturalWidth, height: image.naturalHeight });
          }}
          className="pointer-events-none absolute inset-0 h-full w-full object-fill"
        />
      ) : null}
      <div
        {...(editable ? { role: "group", tabIndex: 0, "aria-label": t("cropFrameLabel"), onKeyDown: nudge } : { "aria-hidden": true })}
        data-crop-box=""
        onPointerDown={editable ? grab("move") : undefined}
        className={cn("absolute outline-none ring-1 ring-white/90", editable && "cursor-move focus-visible:ring-2 focus-visible:ring-primary")}
        style={{
          left: `${box.x * 100}%`,
          top: `${box.y * 100}%`,
          width: `${box.width * 100}%`,
          height: `${box.height * 100}%`,
          //: 框外压暗:一圈很大的阴影,被底板的 overflow-hidden 裁掉 —— 不另画四块遮罩。
          boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.5)",
        }}
      >
        {editable
          ? HANDLES.map(({ handle, hit, mark }) => (
              <span key={handle} data-crop-handle={handle} onPointerDown={grab(handle)} className={cn("absolute", hit)}>
                <span aria-hidden className={cn("absolute border-white", mark)} />
              </span>
            ))
          : null}
      </div>
    </div>
  );
}
