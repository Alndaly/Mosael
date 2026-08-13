import React from "react";
import { Columns2, FlipHorizontal, Grid2x2, Link2, Link2Off, Maximize2, X } from "lucide-react";

import { assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { WINDOW_CHROME_INSET } from "@/lib/windowChrome";

/**
 * 素材对比(Lightroom 的 Compare / Survey)。
 *
 * **联动缩放平移是这个功能的灵魂**:不联动的并排就是两个缩略图,用户自己开两个窗口也一样,
 * 不值得做。两张图共享同一个 {scale, x, y},放大到 300% 看细节时两边看的是同一处。
 *
 * 三种模式:并排(两张各自一屏一半)、滑动分割(两张叠在同一画面里擦除)、多图对比
 * (全部铺开,底部候选条指派 A/B)。分割在构图不同的两张上更像"擦除对照"而非严格的
 * before/after,但仍比并排更容易看出同一处的差异。
 */

/** 并排 / 滑动分割 / 多图对比。 */
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

/** 网格里单元格的最小可用高度。低于这个值就不再硬塞进一屏,改为滚动。 */
const MIN_CELL = 150;
const GRID_GAP = 8;

/**
 * 多图网格的铺排:在容器里挑一个**让单张图最大**的列数。
 *
 * `auto-fit + minmax` 做不到这件事 —— 它只按宽度切列,不知道容器有多高。4 张图在宽屏上
 * 会被摊成一行,每张宽 1/4、下面留一大片空白;而 2×2 时每张能大得多(格子从 496×1080
 * 变成 992×540,等比塞进去的边长 496 → 540)。所以列数必须同时看高度。
 *
 * 评分用「等比缩放后的渲染高度」而不是格子面积:图是 object-contain,格子再宽也只是给它
 * 加黑边,真正决定"看得清不清"的是短边。
 *
 * 张数多到单元格低于 MIN_CELL 时放弃铺满,退回定高滚动 —— 硬塞一屏的结果是每张都小到
 * 分辨不出差异,而这个视图存在的意义就是分辨差异。
 */
function useBestFit(count: number, aspect: number) {
  // 回调 ref 而不是 useRef:切到滑动分割再切回来,这个 div 是重新挂载的新节点,
  // 空依赖的 effect 不会重新观察它,尺寸会永远停在切走前的那一份。
  const [node, setNode] = React.useState<HTMLDivElement | null>(null);
  const [box, setBox] = React.useState({ w: 0, h: 0 });

  React.useLayoutEffect(() => {
    if (!node) return;
    // 尺寸没变就返回原对象。少了这道判等,每次观察器回调都是一次新 {w,h} → 一次重渲染,
    // 而重渲染改栅格、改栅格又触发观察器 —— 自激的循环。它不表现为卡死而是"一直在闪":
    // 组件每帧重渲染,悬浮态的过渡和原生 title 气泡被反复打断重放。
    const measure = () => {
      const w = node.clientWidth;
      const h = node.clientHeight;
      setBox((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);

  const layout = React.useMemo(() => {
    if (count <= 0 || box.w <= 0 || box.h <= 0) return null;
    let best = { cols: 1, rows: count, score: -1 };
    for (let cols = 1; cols <= count; cols += 1) {
      const rows = Math.ceil(count / cols);
      const cellW = (box.w - GRID_GAP * (cols - 1)) / cols;
      const cellH = (box.h - GRID_GAP * (rows - 1)) / rows;
      if (cellW <= 0 || cellH <= 0) continue;
      const score = Math.min(cellW / aspect, cellH);
      if (score > best.score) best = { cols, rows, score };
    }
    const cellH = (box.h - GRID_GAP * (best.rows - 1)) / best.rows;
    return { ...best, scroll: cellH < MIN_CELL };
  }, [count, box, aspect]);

  return { ref: setNode, layout };
}

/** 一个对比窗格。变换由外部给,自己只负责渲染与手势上报。 */
function Pane({
  asset,
  transform,
  onTransform,
  onFocus,
  active,
  label,
}: {
  asset: Asset;
  transform: Transform;
  onTransform: (next: Transform) => void;
  onFocus: () => void;
  active: boolean;
  label?: string;
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
        "relative grid min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden rounded-lg border border-border bg-panel-subtle",
        active ? "border-primary" : "border-border",
      )}
    >
      <div
        ref={ref}
        className="relative min-h-0 cursor-grab overflow-hidden active:cursor-grabbing"
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
          <span className="absolute left-2 top-2 rounded-full bg-[rgb(0_0_0/0.55)] px-2 py-0.5 text-ui-2xs font-semibold text-white backdrop-blur-[6px]">
            {label}
          </span>
        )}
      </div>
      {/* 元信息贴在窗格里而不是侧栏:挑图时视线在图上,把名字和尺寸放远了等于没有。 */}
      <div className="grid gap-px border-t border-border bg-panel px-2.5 py-1.5">
        <span className="truncate text-ui-sm font-semibold text-foreground" title={asset.name || asset.original_filename}>
          {asset.name || asset.original_filename}
        </span>
        <span className="timecode text-ui-2xs text-muted-foreground">
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
      className="relative h-full w-full cursor-grab overflow-hidden rounded-lg border border-border bg-panel-subtle active:cursor-grabbing"
      onWheel={onWheel}
      onPointerDown={startPan}
    >
      <img src={assetFileUrl(a.id)} alt="" draggable={false} className="pointer-events-none absolute left-1/2 top-1/2 max-h-full max-w-full select-none object-contain" style={style} />
      {/* B 层只露出分割线右侧。clip-path 而不是 width:两张图的定位必须完全一致,
          否则擦除时画面会横向跳一下。 */}
      <div className="pointer-events-none absolute inset-0" style={{ clipPath: `inset(0 0 0 ${split}%)` }}>
        <img src={assetFileUrl(b.id)} alt="" draggable={false} className="absolute left-1/2 top-1/2 max-h-full max-w-full select-none object-contain" style={style} />
      </div>

      {/* 命中区 12px、可见线 1px:分割线越细,两侧的差异越是紧挨着可比;而 1px 宽的东西
          用鼠标是抓不住的,所以把"看得见的"和"抓得住的"分成两层。 */}
      <div
        className="absolute inset-y-0 z-[2] w-3 -translate-x-1/2 cursor-ew-resize"
        style={{ left: `${split}%` }}
        onPointerDown={startDivider}
      >
        <span className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-white/80" />
        <span className="absolute left-1/2 top-1/2 grid h-7 w-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/60 bg-black/50 text-white backdrop-blur-[6px]">
          <FlipHorizontal size={13} />
        </span>
      </div>
      <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-[rgb(0_0_0/0.55)] px-2 py-0.5 text-ui-2xs font-semibold text-white">A</span>
      <span className="pointer-events-none absolute right-2 top-2 rounded-full bg-[rgb(0_0_0/0.55)] px-2 py-0.5 text-ui-2xs font-semibold text-white">B</span>
    </div>
  );
}

export function AssetCompareView({ assets, onClose }: { assets: Asset[]; onClose: () => void }) {
  const t = useI18n();
  // 只比图片:视频要同步播放/逐帧,是另一套设计,不硬塞进来。
  const images = React.useMemo(() => assets.filter((asset) => asset.kind === "image"), [assets]);
  const [pair, setPair] = React.useState<[number, number]>([0, 1]);

  /** 把第 index 张放进 A(side=0)或 B(side=1)。
   *
   * 目标图正占着**另一侧**时改为对调,而不是让两侧变成同一张 —— 同一张自己跟自己比,
   * 并排是两块一样的画面、分割是一条擦不出差异的线,都是纯粹的死状态。而"点了对面那张"
   * 恰恰几乎总是"想把左右调个个儿"。 */
  const assignSlot = React.useCallback((side: 0 | 1, index: number) => {
    setPair((current) => {
      const other = current[side === 0 ? 1 : 0];
      const next: [number, number] = [...current];
      if (other === index) next[side === 0 ? 1 : 0] = current[side];
      next[side] = index;
      return next;
    });
  }, []);
  const [mode, setMode] = React.useState<CompareMode>(() => (images.length > 2 ? "grid" : "two"));
  const grid = mode === "grid";
  /** 铺排用的代表性宽高比:取中位数,一两张异形图不该带偏整屏的列数。 */
  const aspect = React.useMemo(() => {
    const ratios = images
      .map(dimensionsOf)
      .filter((dim): dim is { w: number; h: number } => dim !== null)
      .map((dim) => dim.w / dim.h)
      .sort((a, b) => a - b);
    return ratios.length ? ratios[Math.floor(ratios.length / 2)] : 1;
  }, [images]);
  const { ref: gridRef, layout: fit } = useBestFit(grid ? images.length : 0, aspect);
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
    // no-drag 是必需的,不是保险:左侧栏整块声明了 -webkit-app-region: drag 且纵向贯穿整窗,
    // 而拖拽区是 Blink 算好交给系统、由系统在页面之前截走输入的 —— 用 fixed inset-0 盖在上面
    // 不管用,z-index 与绘制顺序对它无效,只有显式 no-drag 能把这块减掉。不加的话这一层
    // 最左 56px 是一条纵贯的死区:候选条第一张的左半边点不动、悬浮态也出不来。
    // 顶栏自己再声明回 drag(它在 DOM 里更靠后,后者生效),盖住标题栏后窗口才还能拖。
    // 配色**跟随主题**。此前这一层混着两种来源:底色写死成近黑(bg-[rgb(10_10_12)])、
    // 图片台面写死 bg-black,而边框用 border-border、按钮用 outline 变体 —— 后者是跟着
    // 主题走的。深色下碰巧一致,浅色下就打架:每张图外面套一圈刺眼的白框,工具栏按钮
    // 也和黑底对不上。一块表面只能有一个色源,这里统一交给令牌。
    <div className="fixed inset-0 z-[140] grid grid-rows-[auto_minmax(0,1fr)] bg-background text-foreground [.is-desktop_&]:[-webkit-app-region:no-drag]">
      {/* 系统窗口控件避让:沿用 AppShell 顶栏的同一套约定 —— macOS 红绿灯在左上、Windows 控件在
          右上,全屏时都收回。这层是全屏覆盖,顶到了标题栏位置,不让位就会压在系统按钮上。
          顺带让它可拖窗(按钮自身 no-drag),否则盖住标题栏后窗口就挪不动了。 */}
      <div className={cn(
        "flex items-center gap-1.5 border-b border-border px-3 py-2 [.is-desktop_&]:[-webkit-app-region:drag] [.is-desktop_&_:is(button,a,input,[role=button])]:[-webkit-app-region:no-drag]",
        WINDOW_CHROME_INSET,
      )}>
        <span className="mr-auto text-ui-sm font-semibold text-foreground">
          {t("mediaCompare")}
          <span className="ml-1.5 font-normal text-muted-foreground">{images.length}</span>
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
        ref={gridRef}
        className={cn(
          "grid min-h-0 gap-2 p-2",
          !grid
            ? "grid-cols-2"
            : // 还没量到尺寸时的兜底:按宽度铺,至少不会塌成单列一张张往下排。
              fit
              ? fit.scroll && "content-start overflow-y-auto"
              : "grid-cols-[repeat(auto-fit,minmax(220px,1fr))] content-start overflow-y-auto",
        )}
        style={
          grid && fit
            ? fit.scroll
              ? { gridTemplateColumns: `repeat(${fit.cols}, minmax(0,1fr))`, gridAutoRows: `${MIN_CELL}px` }
              : {
                  gridTemplateColumns: `repeat(${fit.cols}, minmax(0,1fr))`,
                  gridTemplateRows: `repeat(${fit.rows}, minmax(0,1fr))`,
                }
            : undefined
        }
      >
        {shown.map((asset, index) => (
          <Pane
            key={asset.id}
            asset={asset}
            active={active === index}
            transform={transformOf(asset.id)}
            onTransform={(next) => applyTransform(asset.id, next)}
            // 网格里点一张只是选中它(可以接着滚轮放大细看),不跳走。此前点一下会直接切到
            // 并排模式,而多图对比里点图的意图通常就是"看这张",跳模式等于把整屏换掉。
            onFocus={() => setActive(index)}
            label={grid ? undefined : index === 0 ? "A" : "B"}
          />
        ))}
      </div>
      )}

      {/* 候选条:一张缩略图分左右两个命中区,左半边送进 A、右半边送进 B。
       *
       * 之前不管点哪张都只替换 B,想换左边那张就没有任何入口;而且 A、B 两张顶着同一种高亮,
       * 光看条子也分不出哪张正在左边。命中区按左右分,是因为它和画面里的位置一一对应 ——
       * 并排时 A 在左 B 在右,分割时 A 在分割线左侧 —— 不用再记住哪个字母是哪边。
       *
       * 角标常驻而不是只在 hover 时出现:它回答的是"现在比的是哪两张",这个问题在鼠标
       * 不在条子上的时候同样要能回答。左右两半的 A/B 提示才是 hover 才给的。 */}
      {mode !== "grid" && images.length > 2 && (
        <div className="flex gap-1.5 overflow-x-auto border-t border-border px-2 py-1.5">
          {images.map((asset, index) => {
            const slot = pair[0] === index ? 0 : pair[1] === index ? 1 : null;
            return (
              <div
                key={asset.id}
                title={asset.name || asset.original_filename}
                className={cn(
                  "group relative h-12 w-16 shrink-0 overflow-hidden rounded border border-border bg-panel-subtle",
                  slot === null ? "border-border opacity-60 hover:opacity-100" : "border-primary",
                )}
              >
                <img src={assetFileUrl(asset.id)} alt="" className="h-full w-full object-cover" />
                {slot !== null && (
                  <span className="pointer-events-none absolute left-0.5 top-0.5 rounded bg-primary px-1 text-[9.5px] font-bold leading-[14px] text-primary-foreground">
                    {slot === 0 ? "A" : "B"}
                  </span>
                )}
                <div className="absolute inset-0 flex opacity-0 transition-opacity group-hover:opacity-100">
                  {([0, 1] as const).map((side) => (
                    <button
                      key={side}
                      type="button"
                      aria-label={`${side === 0 ? "A" : "B"} · ${asset.name || asset.original_filename}`}
                      className={cn(
                        "grid flex-1 cursor-pointer place-items-center bg-[rgb(0_0_0/0.55)] text-ui-xs font-bold text-white hover:bg-[rgb(0_0_0/0.75)]",
                        side === 0 ? "border-r border-white/25" : "",
                      )}
                      onClick={() => assignSlot(side, index)}
                    >
                      {side === 0 ? "A" : "B"}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
