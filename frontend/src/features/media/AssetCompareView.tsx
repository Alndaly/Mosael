import React from "react";
import { Columns2, FlipHorizontal, Grid2x2, Link2, Link2Off, Maximize2, X } from "lucide-react";

import { assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * 素材对比(Lightroom 的 Compare / Survey)。
 *
 * **联动缩放平移是这个功能的灵魂**:不联动的并排就是两个缩略图,用户自己开两个窗口也一样,
 * 不值得做。两张图共享同一个 {scale, x, y},放大到 300% 看细节时两边看的是同一处。
 *
 * 刻意**没做**滑动分割(before/after 那种拉滑杆的):它只在同构图时成立(放大、修复、图生图),
 * 而素材库里任意两张的构图通常不同,拉滑杆只会看到两个不相干的半张图,反而误导。等真有
 * source→result 的成对关系时再单独开放。
 */

/** 并排 / 滑动分割 / 多图筛选。 */
type CompareMode = "two" | "split" | "grid";

interface Transform {
  scale: number;
  x: number;
  y: number;
}

const IDENTITY: Transform = { scale: 1, x: 0, y: 0 };
const MIN_SCALE = 0.2;
const MAX_SCALE = 12;

function dimensionsOf(asset: Asset): { w: number; h: number } | null {
  const info = (asset.media_info ?? {}) as Record<string, unknown>;
  const w = Number(info.width);
  const h = Number(info.height);
  return Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0 ? { w, h } : null;
}

/** 一个对比窗格。变换由外部给,自己只负责渲染与手势上报。 */
function Pane({
  asset,
  transform,
  onTransform,
  onFocus,
  active,
  label,
  compact = false,
}: {
  asset: Asset;
  transform: Transform;
  onTransform: (next: Transform) => void;
  onFocus: () => void;
  active: boolean;
  label?: string;
  /** 网格(多图筛选)模式。图片区要给确定高度 —— 自动行高下 minmax(0,1fr) 算成 0,
   *  而 img 是绝对定位撑不起父容器,窗格会塌成只剩页脚那一条。 */
  compact?: boolean;
}) {
  const t = useI18n();
  const ref = React.useRef<HTMLDivElement | null>(null);
  const dim = dimensionsOf(asset);

  // 以光标为锚点缩放:否则放大后要重新找回刚才在看的地方。
  const onWheel = (event: React.WheelEvent) => {
    if (!ref.current) return;
    event.preventDefault();
    const rect = ref.current.getBoundingClientRect();
    const cx = event.clientX - rect.left - rect.width / 2;
    const cy = event.clientY - rect.top - rect.height / 2;
    const factor = Math.exp(-event.deltaY / 320);
    const scale = Math.min(Math.max(transform.scale * factor, MIN_SCALE), MAX_SCALE);
    const k = scale / transform.scale;
    onTransform({ scale, x: cx - (cx - transform.x) * k, y: cy - (cy - transform.y) * k });
  };

  const onPointerDown = (event: React.PointerEvent) => {
    onFocus();
    if (event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...transform };
    const move = (e: PointerEvent) =>
      onTransform({ ...origin, x: origin.x + (e.clientX - startX), y: origin.y + (e.clientY - startY) });
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div
      className={cn(
        "relative grid min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden rounded-lg border bg-black",
        active ? "border-primary" : "border-border",
      )}
    >
      <div
        ref={ref}
        className={cn(
          "relative cursor-grab overflow-hidden active:cursor-grabbing",
          compact ? "aspect-square" : "min-h-0",
        )}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
      >
        <img
          src={assetFileUrl(asset.id)}
          alt={asset.name || asset.original_filename}
          draggable={false}
          className="pointer-events-none absolute left-1/2 top-1/2 max-h-full max-w-full select-none object-contain"
          style={{
            transform: `translate(-50%, -50%) translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
            transformOrigin: "center",
          }}
        />
        {label && (
          <span className="absolute left-2 top-2 rounded-full bg-[rgb(0_0_0/0.55)] px-2 py-0.5 text-[10.5px] font-semibold text-white backdrop-blur-[6px]">
            {label}
          </span>
        )}
      </div>
      {/* 元信息贴在窗格里而不是侧栏:挑图时视线在图上,把名字和尺寸放远了等于没有。 */}
      <div className="grid gap-px border-t border-border bg-panel px-2.5 py-1.5">
        <span className="truncate text-[12px] font-semibold text-foreground" title={asset.name || asset.original_filename}>
          {asset.name || asset.original_filename}
        </span>
        <span className="timecode text-[10.5px] text-muted-foreground">
          {dim ? `${dim.w}×${dim.h}` : t("mediaCompareNoSize")}
          {asset.tags?.length ? ` · ${asset.tags.slice(0, 3).join(" ")}` : ""}
        </span>
      </div>
    </div>
  );
}

/**
 * 滑动分割:两张图叠在**同一个画面**里,拖分割线左右擦除。
 *
 * 它们共享同一个变换 —— 缩放平移时两层一起动,分割线才始终比的是同一处。构图不同的两张也能用,
 * 只是这时它更像"擦除对照"而不是严格的 before/after。
 */
function SplitPane({
  a,
  b,
  split,
  onSplit,
  transform,
  onTransform,
}: {
  a: Asset;
  b: Asset;
  split: number;
  onSplit: (next: number) => void;
  transform: Transform;
  onTransform: (next: Transform) => void;
}) {
  const ref = React.useRef<HTMLDivElement | null>(null);

  const onWheel = (event: React.WheelEvent) => {
    if (!ref.current) return;
    event.preventDefault();
    const rect = ref.current.getBoundingClientRect();
    const cx = event.clientX - rect.left - rect.width / 2;
    const cy = event.clientY - rect.top - rect.height / 2;
    const scale = Math.min(Math.max(transform.scale * Math.exp(-event.deltaY / 320), MIN_SCALE), MAX_SCALE);
    const k = scale / transform.scale;
    onTransform({ scale, x: cx - (cx - transform.x) * k, y: cy - (cy - transform.y) * k });
  };

  const startPan = (event: React.PointerEvent) => {
    if (event.button !== 0) return;
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = { ...transform };
    const move = (e: PointerEvent) =>
      onTransform({ ...origin, x: origin.x + (e.clientX - startX), y: origin.y + (e.clientY - startY) });
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const startDivider = (event: React.PointerEvent) => {
    event.preventDefault();
    event.stopPropagation(); // 拖分割线不该同时平移画面
    const move = (e: PointerEvent) => {
      const rect = ref.current?.getBoundingClientRect();
      if (!rect) return;
      onSplit(Math.min(98, Math.max(2, ((e.clientX - rect.left) / rect.width) * 100)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const style: React.CSSProperties = {
    transform: `translate(-50%, -50%) translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
    transformOrigin: "center",
  };

  return (
    <div
      ref={ref}
      className="relative h-full w-full cursor-grab overflow-hidden rounded-lg border border-border bg-black active:cursor-grabbing"
      onWheel={onWheel}
      onPointerDown={startPan}
    >
      <img src={assetFileUrl(a.id)} alt="" draggable={false} className="pointer-events-none absolute left-1/2 top-1/2 max-h-full max-w-full select-none object-contain" style={style} />
      {/* B 层只露出分割线右侧。clip-path 而不是 width:两张图的定位必须完全一致,
          否则擦除时画面会横向跳一下。 */}
      <div className="pointer-events-none absolute inset-0" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
        <img src={assetFileUrl(b.id)} alt="" draggable={false} className="absolute left-1/2 top-1/2 max-h-full max-w-full select-none object-contain" style={style} />
      </div>

      <div
        className="absolute inset-y-0 z-[2] w-1 -translate-x-1/2 cursor-ew-resize bg-white/85"
        style={{ left: `${split}%` }}
        onPointerDown={startDivider}
      >
        <span className="absolute left-1/2 top-1/2 grid h-7 w-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/70 bg-black/55 text-white backdrop-blur-[6px]">
          <FlipHorizontal size={13} />
        </span>
      </div>
      <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-[rgb(0_0_0/0.55)] px-2 py-0.5 text-[10.5px] font-semibold text-white">A</span>
      <span className="pointer-events-none absolute right-2 top-2 rounded-full bg-[rgb(0_0_0/0.55)] px-2 py-0.5 text-[10.5px] font-semibold text-white">B</span>
    </div>
  );
}

export function AssetCompareView({ assets, onClose }: { assets: Asset[]; onClose: () => void }) {
  const t = useI18n();
  // 只比图片:视频要同步播放/逐帧,是另一套设计,不硬塞进来。
  const images = React.useMemo(() => assets.filter((asset) => asset.kind === "image"), [assets]);
  const [pair, setPair] = React.useState<[number, number]>([0, 1]);
  const [mode, setMode] = React.useState<CompareMode>(() => (images.length > 2 ? "grid" : "two"));
  const grid = mode === "grid";
  /** 滑动分割的分割线位置(百分比)。 */
  const [split, setSplit] = React.useState(50);
  const [synced, setSynced] = React.useState(true);
  const [transforms, setTransforms] = React.useState<Record<string, Transform>>({});
  const [active, setActive] = React.useState(0);

  const reset = React.useCallback(() => setTransforms({}), []);
  const transformOf = (id: string) => transforms[id] ?? IDENTITY;
  const applyTransform = (id: string, next: Transform) =>
    setTransforms((current) =>
      // 联动时一次写所有窗格:分开写会让两边在快速滚轮下错位一帧。
      synced ? Object.fromEntries(images.map((asset) => [asset.id, next])) : { ...current, [id]: next },
    );

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "0") reset();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, reset]);

  if (images.length < 2) {
    return null;
  }

  const shown = grid ? images : [images[pair[0]], images[pair[1]]].filter(Boolean);

  return (
    <div className="fixed inset-0 z-[140] grid grid-rows-[auto_minmax(0,1fr)] bg-[rgb(10_10_12)]">
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
        <span className="mr-auto text-[12.5px] font-semibold text-white">
          {t("mediaCompare")}
          <span className="ml-1.5 font-normal text-white/55">{images.length}</span>
        </span>
        {/* 三种形态平铺,不做成"切换"按钮:用户要的是随时跳到某一种,而不是猜下一次点会变成什么。 */}
        {(["two", "split", "grid"] as const).map((item) => (
          <Button
            key={item}
            variant={mode === item ? "default" : "outline"}
            size="sm"
            disabled={item === "grid" && images.length < 3}
            onClick={() => setMode(item)}
          >
            {item === "two" ? <Columns2 size={13} /> : item === "split" ? <FlipHorizontal size={13} /> : <Grid2x2 size={13} />}
            {t(item === "two" ? "mediaCompareTwoUp" : item === "split" ? "mediaCompareSplit" : "mediaCompareGrid")}
          </Button>
        ))}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setSynced((v) => !v)}
          title={t(synced ? "mediaCompareUnsync" : "mediaCompareSync")}
        >
          {synced ? <Link2 size={13} /> : <Link2Off size={13} />}
          {t(synced ? "mediaCompareSynced" : "mediaCompareIndependent")}
        </Button>
        <Button variant="outline" size="sm" onClick={reset} title={t("mediaCompareFit")}>
          <Maximize2 size={13} /> {t("mediaCompareFit")}
        </Button>
        <Button variant="outline" size="sm" onClick={onClose} aria-label={t("close")}>
          <X size={13} />
        </Button>
      </div>

      {mode === "split" ? (
        <div className="min-h-0 p-2">
          <SplitPane
            a={images[pair[0]]}
            b={images[pair[1]] ?? images[0]}
            split={split}
            onSplit={setSplit}
            transform={transformOf(images[pair[0]].id)}
            onTransform={(next) => applyTransform(images[pair[0]].id, next)}
          />
        </div>
      ) : (
      <div
        className={cn(
          "grid min-h-0 gap-2 p-2",
          grid ? "grid-cols-[repeat(auto-fit,minmax(220px,1fr))] content-start overflow-y-auto" : "grid-cols-2",
        )}
      >
        {shown.map((asset, index) => (
          <Pane
            key={asset.id}
            asset={asset}
            active={!grid && active === index}
            compact={grid}
            transform={transformOf(asset.id)}
            onTransform={(next) => applyTransform(asset.id, next)}
            onFocus={() => {
              setActive(index);
              // 网格里点一张 = 把它放进并排的左位,接着挑下一张 —— Lightroom 的收敛节奏。
              if (grid) {
                const at = images.findIndex((item) => item.id === asset.id);
                setPair(([, right]) => [at, at === right ? (at + 1) % images.length : right]);
                setMode("two");
              }
            }}
            label={grid ? undefined : index === 0 ? "A" : "B"}
          />
        ))}
      </div>
      )}

      {/* 并排模式下的候选条:换掉右边那张,继续和左边比 —— 这是 Compare 的核心节奏。 */}
      {mode !== "grid" && images.length > 2 && (
        <div className="flex gap-1.5 overflow-x-auto border-t border-border px-2 py-1.5">
          {images.map((asset, index) => (
            <button
              key={asset.id}
              type="button"
              title={asset.name || asset.original_filename}
              className={cn(
                "h-12 w-16 shrink-0 cursor-pointer overflow-hidden rounded border bg-black p-0",
                pair.includes(index) ? "border-primary" : "border-border opacity-60 hover:opacity-100",
              )}
              onClick={() => setPair(([left]) => (index === left ? [left, index] : [left, index]))}
            >
              <img
                src={assetFileUrl(asset.id)}
                alt=""
                className="h-full w-full object-cover"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
