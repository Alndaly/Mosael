import React from "react";
import { GripHorizontal, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Scopes } from "@/features/editor/Scopes";

const POS_KEY = "mibu.scopes.pos";
const MIN_W = 220;
const MAX_W = 560;
const MIN_H = 150;
const MAX_H = 520;

type Placement = { x: number; y: number; w: number; h: number };

function readPlacement(): Placement {
  try {
    const raw = JSON.parse(localStorage.getItem(POS_KEY) ?? "null");
    if (raw && typeof raw.x === "number" && typeof raw.y === "number") {
      return {
        x: raw.x,
        y: raw.y,
        w: typeof raw.w === "number" ? raw.w : 268,
        h: typeof raw.h === "number" ? raw.h : 214,
      };
    }
  } catch {
    /* ignore */
  }
  return { x: window.innerWidth - 300, y: 120, w: 268, h: 214 };
}

const clampSize = (w: number, h: number) => ({
  w: Math.min(Math.max(MIN_W, w), MAX_W),
  h: Math.min(Math.max(MIN_H, h), MAX_H),
});

/**
 * The scopes as a free, draggable + resizable floating window (position: fixed) instead of an
 * overlay pinned inside the preview frame — so it never covers the picture. Drag by the header,
 * resize from the bottom-right grip; both persist per device.
 */
export function ScopesFloat({
  videoRef,
  filter,
  imageSrc,
  canvasRef,
  onClose,
}: {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  filter: string;
  imageSrc?: string | null;
  canvasRef?: React.RefObject<HTMLCanvasElement | null>;
  onClose: () => void;
}) {
  const t = useI18n();
  const [place, setPlace] = React.useState(readPlacement);
  const placeRef = React.useRef(place);
  placeRef.current = place;
  // 拖动(移动)与缩放共用一套指针会话;kind 区分,起点存下用于增量。
  const dragRef = React.useRef<{ kind: "move" | "resize"; px: number; py: number; base: Placement } | null>(null);

  const persist = React.useCallback(() => {
    try {
      localStorage.setItem(POS_KEY, JSON.stringify(placeRef.current));
    } catch {
      /* ignore */
    }
  }, []);

  const clampPos = React.useCallback((x: number, y: number, w: number) => {
    return {
      x: Math.min(Math.max(8, x), Math.max(8, window.innerWidth - w - 8)),
      y: Math.min(Math.max(8, y), Math.max(8, window.innerHeight - 80)),
    };
  }, []);

  // 视口收缩时把窗口夹回屏内,避免存的旧位置把窗口(和它的把手)甩到屏外够不着。
  React.useEffect(() => {
    const reclamp = () => setPlace((p) => ({ ...p, ...clampPos(p.x, p.y, p.w) }));
    reclamp();
    window.addEventListener("resize", reclamp);
    return () => window.removeEventListener("resize", reclamp);
  }, [clampPos]);

  const startMove = (event: React.PointerEvent) => {
    // 关键:点到子按钮(关闭)不进入拖动 —— 否则 setPointerCapture 会吞掉按钮的 click,X 关不掉。
    if ((event.target as HTMLElement).closest("button")) return;
    dragRef.current = { kind: "move", px: event.clientX, py: event.clientY, base: placeRef.current };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const startResize = (event: React.PointerEvent) => {
    event.stopPropagation();
    dragRef.current = { kind: "resize", px: event.clientX, py: event.clientY, base: placeRef.current };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.px;
    const dy = event.clientY - drag.py;
    if (drag.kind === "move") {
      const next = { ...drag.base, ...clampPos(drag.base.x + dx, drag.base.y + dy, drag.base.w) };
      placeRef.current = next;
      setPlace(next);
    } else {
      const size = clampSize(drag.base.w + dx, drag.base.h + dy);
      const next = { ...drag.base, ...size, ...clampPos(drag.base.x, drag.base.y, size.w) };
      placeRef.current = next;
      setPlace(next);
    }
  };
  const onPointerUp = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    persist();
  };

  return (
    <div
      className="fixed z-[80] flex select-none flex-col overflow-hidden rounded-lg border border-[rgb(255_255_255/0.14)] bg-[rgb(8_8_10/0.9)] backdrop-blur-[10px]"
      style={{ left: place.x, top: place.y, width: place.w, height: place.h }}
    >
      <div
        className="flex h-[26px] flex-none cursor-grab touch-none items-center gap-1.5 border-b border-[rgb(255_255_255/0.08)] bg-[rgb(255_255_255/0.05)] pl-2 pr-1.5 active:cursor-grabbing"
        onPointerDown={startMove}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <GripHorizontal size={13} className="text-muted-foreground" />
        <span className="flex-1 text-[11px] font-medium text-foreground">{t("scopes")}</span>
        <button type="button" className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-md text-muted-foreground hover:bg-[rgb(255_255_255/0.1)] hover:text-foreground" onClick={onClose} aria-label={t("close")}>
          <X size={13} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden p-1.5">
        <Scopes videoRef={videoRef} filter={filter} imageSrc={imageSrc} canvasRef={canvasRef} fill />
      </div>
      {/* 右下角缩放把手 */}
      <div
        className="absolute bottom-0 right-0 h-3.5 w-3.5 cursor-nwse-resize touch-none"
        onPointerDown={startResize}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        aria-hidden
      >
        <span className="pointer-events-none absolute bottom-[3px] right-[3px] h-1.5 w-1.5 border-b border-r border-[rgb(255_255_255/0.35)]" />
      </div>
    </div>
  );
}
