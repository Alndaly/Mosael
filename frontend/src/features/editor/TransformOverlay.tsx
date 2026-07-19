import React from "react";

export type Transform = { scale: number; x: number; y: number; rotation: number; opacity: number };

export function readTransform(raw: Record<string, number> | undefined | null): Transform {
  const tf = raw ?? {};
  return {
    scale: tf.scale ?? 1,
    x: tf.x ?? 0,
    y: tf.y ?? 0,
    rotation: tf.rotation ?? 0,
    opacity: tf.opacity ?? 1,
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
      className="tf-box"
      style={{
        left: `${leftPct}%`,
        top: `${topPct}%`,
        width: `${widthPct}%`,
        height: `${widthPct}%`,
        transform: `rotate(${tf.rotation}deg)`,
      }}
      onPointerDown={(event) => event.button === 0 && startDrag(event, "move")}
    >
      <div className="tf-rotate-stem" />
      <div className="tf-handle tf-rotate" onPointerDown={(event) => event.button === 0 && startDrag(event, "rotate")} />
      {HANDLES.map(([id, hx, hy]) => (
        <div
          key={id}
          className={`tf-handle tf-corner tf-${id}`}
          style={{ left: `${hx * 100}%`, top: `${hy * 100}%` }}
          onPointerDown={(event) => event.button === 0 && startDrag(event, "resize")}
        />
      ))}
    </div>
  );
}
