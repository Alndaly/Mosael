import React from "react";
import { cn } from "@/lib/utils";
import type { Keyframe } from "@/features/editor/keyframes";

export type Transform = {
  scale: number;
  x: number;
  y: number;
  rotation: number;
  opacity: number;
  // 关键帧轨(可选):存在且激活时,位置/缩放/透明度随片段进度插值。见 keyframes.ts。
  keyframes?: Keyframe[];
};

/** 变换的默认值与合法范围 —— **和后端是同一份**,由 contracts/transform-cases.json 钉住
 *  (后端在 domain/sequences/operations.TRANSFORM_BOUNDS)。
 *
 *  此前这里一处都不钳,而后端钳:同一个 clip,预览按 scale=20 放大、导出钳到 4 —— 预览和
 *  成片是两个画面。没发作只因为唯一的写入路径先钳过一道,那是上游挡住,不是两侧一致。 */
export const TRANSFORM_DEFAULTS = { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 } as const;
export const TRANSFORM_BOUNDS: Record<keyof typeof TRANSFORM_DEFAULTS, [number, number]> = {
  scale: [0.1, 4],
  x: [-2, 2],
  y: [-2, 2],
  rotation: [-180, 180],
  opacity: [0, 1],
};

export function readTransform(raw: Record<string, unknown> | undefined | null): Transform {
  const tf = raw ?? {};
  // API dicts arrive untyped ({[key]: unknown}); coerce defensively while preserving a real 0
  // (e.g. opacity: 0 is a legitimately hidden clip, so we can't use `Number(v) || fallback`).
  const num = (key: keyof typeof TRANSFORM_DEFAULTS) => {
    const fallback = TRANSFORM_DEFAULTS[key];
    const got = tf[key];
    // 数字字符串按数字读(写入路径存 float,出现字符串说明是别处写进来的 —— 能读回来就别丢);
    // **布尔不是数字**:`Number(true) === 1` 会把片段挪到画面外。
    const value =
      typeof got === "number" ? got : typeof got === "string" && got.trim() !== "" ? Number(got) : NaN;
    if (!Number.isFinite(value)) return fallback;
    const [lo, hi] = TRANSFORM_BOUNDS[key];
    return Math.max(lo, Math.min(hi, value));
  };
  const keyframes = Array.isArray(tf.keyframes) ? (tf.keyframes as Keyframe[]) : undefined;
  return {
    scale: num("scale"),
    x: num("x"),
    y: num("y"),
    rotation: num("rotation"),
    opacity: num("opacity"),
    ...(keyframes ? { keyframes } : {}),
  };
}

/** CSS the preview media uses — kept identical here and in Monitor so the box tracks the media. */
export function transformCss(tf: Transform): React.CSSProperties {
  if (tf.scale === 1 && tf.rotation === 0 && tf.opacity === 1 && tf.x === 0 && tf.y === 0) return {};
  return {
    transform: `translate(${tf.x * 50}%, ${tf.y * 50}%) scale(${tf.scale}) rotate(${tf.rotation}deg)`,
    opacity: tf.opacity,
  };
}

const HANDLES = [
  ["nw", 0, 0],
  ["ne", 1, 0],
  ["se", 1, 1],
  ["sw", 0, 1],
] as const;

/**
 * Direct-manipulation box over the preview frame for the selected clip: drag the body to move,
 * a corner to resize (uniform, aspect-locked), the top stem to rotate. Emits a live transform
 * during the gesture and a committed one on release. Geometry mirrors Monitor's CSS:
 * center = frameCenter + (x·0.5·frame), size = scale·frame, rotate(rotation).
 */
export function TransformOverlay({
  frameRef,
  transform,
  onChange,
  onCommit,
}: {
  frameRef: React.RefObject<HTMLElement | null>;
  transform: Transform;
  onChange: (next: Transform) => void;
  onCommit: (next: Transform) => void;
}) {
  const tf = transform;
  // Box in % of the frame (so it stays glued to the media as the preview resizes).
  const widthPct = tf.scale * 100;
  const leftPct = 50 + tf.x * 50 - widthPct / 2;
  const topPct = 50 + tf.y * 50 - widthPct / 2;

  const startDrag = (
    event: React.PointerEvent,
    mode: "move" | "resize" | "rotate",
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return;
    const start = { ...tf };
    const cx = rect.left + rect.width / 2 + (start.x * 0.5 * rect.width);
    const cy = rect.top + rect.height / 2 + (start.y * 0.5 * rect.height);
    const startAngle = Math.atan2(event.clientY - cy, event.clientX - cx);
    const startX = event.clientX;
    const startY = event.clientY;
    let latest = start;

    const onMove = (e: PointerEvent) => {
      if (mode === "move") {
        // Δpx → Δx where x·0.5·frame = px offset ⇒ Δx = 2·Δpx/frame.
        latest = {
          ...start,
          x: start.x + (2 * (e.clientX - startX)) / rect.width,
          y: start.y + (2 * (e.clientY - startY)) / rect.height,
        };
      } else if (mode === "resize") {
        // Uniform, center-anchored: half-width in px = scale·frame/2; match the pointer's x-distance.
        const half = Math.abs(e.clientX - cx);
        latest = { ...start, scale: Math.max(0.05, Math.min(4, half / (rect.width / 2))) };
      } else {
        const deg = ((Math.atan2(e.clientY - cy, e.clientX - cx) - startAngle) * 180) / Math.PI;
        let rotation = start.rotation + deg;
        if (e.shiftKey) rotation = Math.round(rotation / 15) * 15; // shift = snap to 15°
        latest = { ...start, rotation: Math.round(rotation) };
      }
      onChange(latest);
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      onCommit(latest);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return (
    <div
      className="absolute box-border cursor-move touch-none border-[1.5px] border-primary shadow-[0_0_0_1px_rgb(0_0_0/0.35)] [pointer-events:auto]"
      style={{
        left: `${leftPct}%`,
        top: `${topPct}%`,
        width: `${widthPct}%`,
        height: `${widthPct}%`,
        transform: `rotate(${tf.rotation}deg)`,
      }}
      onPointerDown={(event) => event.button === 0 && startDrag(event, "move")}
    >
      <div className="pointer-events-none absolute left-1/2 top-0 h-5 w-[1.5px] -translate-x-1/2 -translate-y-full bg-primary" />
      <div className="absolute left-1/2 top-[-20px] h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none rounded-full border-[1.5px] border-primary bg-white [pointer-events:auto]" onPointerDown={(event) => event.button === 0 && startDrag(event, "rotate")} />
      {HANDLES.map(([id, hx, hy]) => (
        <div
          key={id}
          className={cn(
            "absolute h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 cursor-nwse-resize touch-none rounded-sm border-[1.5px] border-primary bg-white [pointer-events:auto]",
            (id === "ne" || id === "sw") && "cursor-nesw-resize",
          )}
          style={{ left: `${hx * 100}%`, top: `${hy * 100}%` }}
          onPointerDown={(event) => event.button === 0 && startDrag(event, "resize")}
        />
      ))}
    </div>
  );
}
