import React from "react";

import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";
import {
  IDENTITY_CURVE,
  IDENTITY_CURVES,
  evalCurve,
  type ColorCurves,
  type CurvePoint,
} from "@/features/editor/colorCurves";

type Channel = "luma" | "r" | "g" | "b";
const CHANNELS: { key: Channel; label: string; stroke: string }[] = [
  { key: "luma", label: "Luma", stroke: "var(--foreground)" },
  { key: "r", label: "R", stroke: "#e5484d" },
  { key: "g", label: "G", stroke: "#30a46c" },
  { key: "b", label: "B", stroke: "#3e63dd" },
];

// 固定比例画布 + 内边距(与前身项目一致):控制点是正圆、端点不贴边被裁。
const W = 224;
const H = 160;
const PAD = 8;
// 相邻点最小间距:既是拖动手感,也防止近邻 x 让 ffmpeg curves 拒掉整条 vf 链。
const MIN_GAP = 0.02;

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const sx = (x: number) => PAD + x * (W - 2 * PAD);
const sy = (y: number) => H - PAD - y * (H - 2 * PAD);

/** 指针捕获尽力而为:失效的 pointerId(合成事件/已离场的触点)会抛错,不能中断手势。 */
function capturePointer(event: React.PointerEvent): void {
  try {
    (event.target as Element).setPointerCapture(event.pointerId);
  } catch {
    /* keep the gesture going without capture */
  }
}

/** 采样 evalCurve 描出路径:画的就是实际应用的那条单调三次曲线(identity 精确压在对角线上)。 */
function pathFor(points: CurvePoint[]): string {
  const N = 64;
  const cmds: string[] = [];
  for (let i = 0; i <= N; i++) {
    const x = i / N;
    const y = evalCurve(points, x);
    cmds.push(`${i === 0 ? "M" : "L"} ${sx(x).toFixed(1)} ${sy(y).toFixed(1)}`);
  }
  return cmds.join(" ");
}

/** 达芬奇式色调曲线编辑器,交互移植自前身项目:
 *  曲线/空白处按下 = 原地加点并立刻拖动;点上按下 = 精确抓取;双击/右键删点(端点保留)。 */
export function CurveEditor({
  curves,
  onChange,
  onCommitStart,
}: {
  curves: ColorCurves | undefined;
  onChange: (next: ColorCurves) => void;
  /** 拖动/加点/删点开始前调用一次(调色撤销栈记一步)。 */
  onCommitStart?: () => void;
}) {
  const t = useI18n();
  const [channel, setChannel] = React.useState<Channel>("luma");
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const dragRef = React.useRef<number | null>(null);

  // 本地草稿:拖动期间逐帧更新草稿(即时),松手才把整条曲线写给 onChange(一次
  // 服务端往返)。onChange 直连服务端 mutation,若每帧都发,渲染会一直落后于手,
  // 拖动直接失灵 —— 前身项目原版写的是同步本地 store,这里用草稿层等价还原手感。
  const [draft, setDraft] = React.useState<ColorCurves | null>(null);
  const base = draft ?? curves ?? IDENTITY_CURVES;
  const points = base[channel] ?? IDENTITY_CURVE;

  // 服务端状态变化(提交后的回读、预设/撤销改曲线)且不在拖动中 → 放下草稿跟随外部。
  React.useEffect(() => {
    if (dragRef.current == null) setDraft(null);
  }, [curves]);

  const withChannel = (pts: CurvePoint[]): ColorCurves => ({ ...base, [channel]: pts });
  /** 拖动中:只改草稿。 */
  const previewPoints = (pts: CurvePoint[]) => setDraft(withChannel(pts));
  /** 离散操作(删点/重置)或松手:草稿 + 提交一并完成。 */
  const commitPoints = (pts: CurvePoint[]) => {
    const next = withChannel(pts);
    setDraft(next);
    onChange(next);
  };

  const toUnit = (clientX: number, clientY: number): CurvePoint => {
    const r = svgRef.current!.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * W;
    const py = ((clientY - r.top) / r.height) * H;
    return [clamp01((px - PAD) / (W - 2 * PAD)), clamp01((H - PAD - py) / (H - 2 * PAD))];
  };

  // 已有点上按下:精确抓这个点(stopPropagation 挡住背景的加点逻辑)。
  const onPointDown = (event: React.PointerEvent, index: number) => {
    event.stopPropagation();
    capturePointer(event);
    onCommitStart?.();
    dragRef.current = index;
  };

  const onMove = (event: React.PointerEvent) => {
    if (dragRef.current == null) return;
    const i = dragRef.current;
    const [ux, uy] = toUnit(event.clientX, event.clientY);
    const next = [...points];
    // 端点 x 锁死 0/1;内部点夹在左右邻点之间 —— 顺序永不改变,索引全程稳定。
    const isFirst = i === 0;
    const isLast = i === next.length - 1;
    const x = isFirst
      ? 0
      : isLast
        ? 1
        : clamp01(Math.min(Math.max(ux, next[i - 1][0] + MIN_GAP), next[i + 1][0] - MIN_GAP));
    next[i] = [x, uy];
    previewPoints(next);
  };

  const onUp = () => {
    if (dragRef.current == null) return;
    dragRef.current = null;
    // 松手提交草稿里的当前曲线(dragRef 先清,让 props 回读能正常接管)。
    commitPoints(points);
  };

  // 曲线/空白处按下 → 原地加点并立刻开始拖它:一次手势完成「加点 + 调整」,
  // 而不是先点一下、再去找那颗新点重新拖。
  const addPointAndDrag = (event: React.PointerEvent) => {
    const [ux, uy] = toUnit(event.clientX, event.clientY);
    let left = 0;
    let right = 1;
    for (const [x] of points) {
      if (x <= ux) left = Math.max(left, x);
      if (x >= ux) right = Math.min(right, x);
    }
    if (left + MIN_GAP > right - MIN_GAP) return; // 这里塞不下新点,忽略这次按下
    const x = clamp01(Math.min(Math.max(ux, left + MIN_GAP), right - MIN_GAP));
    onCommitStart?.();
    const newPoint: CurvePoint = [x, uy];
    const pts = [...points, newPoint].sort((a, b) => a[0] - b[0]);
    const index = pts.indexOf(newPoint); // 按引用定位,避免浮点相等误抓到别的点
    previewPoints(pts);
    capturePointer(event);
    dragRef.current = index;
  };

  const removePoint = (event: React.MouseEvent, index: number) => {
    event.preventDefault();
    event.stopPropagation();
    if (index === 0 || index === points.length - 1) return; // 端点不可删
    onCommitStart?.();
    commitPoints(points.filter((_, i) => i !== index));
  };

  const resetChannel = () => {
    onCommitStart?.();
    commitPoints(IDENTITY_CURVE.map((p) => [...p] as CurvePoint));
  };

  const active = CHANNELS.find((c) => c.key === channel)!;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1">
        {CHANNELS.map((c) => (
          <button
            key={c.key}
            type="button"
            className={cn(
            "flex-1 cursor-pointer rounded-md border border-border bg-panel py-0.5 text-[11px] font-semibold text-muted-foreground transition-[border-color,color] duration-100",
            channel === c.key && "bg-[color-mix(in_srgb,currentColor_8%,transparent)]",
          )}
            style={channel === c.key ? { color: c.stroke, borderColor: c.stroke } : undefined}
            onClick={() => setChannel(c.key)}
          >
            {c.label}
          </button>
        ))}
        <button type="button" className="cursor-pointer border-0 bg-transparent px-1 py-0 text-[10.5px] text-muted-foreground hover:text-foreground" onClick={resetChannel} title={t("curveResetChannel")}>
          {t("gradeReset")}
        </button>
      </div>
      <svg
        ref={svgRef}
        className="block h-auto w-full cursor-crosshair touch-none rounded-md border border-border bg-panel-inset"
        viewBox={`0 0 ${W} ${H}`}
        onPointerDown={addPointAndDrag}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
      >
        {/* 网格 + identity 参考对角线 */}
        {[0.25, 0.5, 0.75].map((g) => (
          <React.Fragment key={g}>
            <line x1={sx(g)} y1={sy(0)} x2={sx(g)} y2={sy(1)} className="stroke-border [stroke-width:0.4] [vector-effect:non-scaling-stroke]" />
            <line x1={sx(0)} y1={sy(g)} x2={sx(1)} y2={sy(g)} className="stroke-border [stroke-width:0.4] [vector-effect:non-scaling-stroke]" />
          </React.Fragment>
        ))}
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} className="stroke-border-strong [stroke-dasharray:2_2] [stroke-width:0.5] [vector-effect:non-scaling-stroke]" />
        <path d={pathFor(points)} className="fill-none [stroke-width:1.5] [vector-effect:non-scaling-stroke]" style={{ stroke: active.stroke }} />
        {points.map(([px, py], i) => (
          <circle
            key={i}
            cx={sx(px)}
            cy={sy(py)}
            r={4}
            className="cursor-grab stroke-panel [stroke-width:1] [vector-effect:non-scaling-stroke] active:cursor-grabbing"
            style={{ fill: active.stroke }}
            onPointerDown={(event) => onPointDown(event, i)}
            onContextMenu={(event) => removePoint(event, i)}
            onDoubleClick={(event) => removePoint(event, i)}
          />
        ))}
      </svg>
      <p className="m-0 text-[10.5px] leading-normal text-muted-foreground">{t("curveHint")}</p>
    </div>
  );
}
