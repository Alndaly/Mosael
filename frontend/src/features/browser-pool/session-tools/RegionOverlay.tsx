import React from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/app/preferences";
import { APP_CHROME } from "@/components/ui/appChrome";
import { listenKeys } from "@/lib/shortcuts";

import { frameDisplaySize, selectionFraction, type Point } from "./pageActions";

/**
 * 框选截图:原生网页上画不了框,所以主进程先冻结一帧、把网页藏起来,这里在原处铺这一帧让人拖。
 * 松手就截(和系统截图一样),Esc 取消。交出去的是画面上的比例 —— 原图多少像素只有主进程知道。
 *
 * 挂到 body 上(portal):顶栏带 backdrop-filter,留在顶栏里的话 fixed 遮罩只有顶栏那么高,拖框的指针根本落不到它上面。
 */
export function RegionOverlay({
  top,
  frame,
  onDone,
}: {
  /** 顶栏多高:冻结画面从顶栏下沿铺,和网页原来的位置对齐。 */
  top: number;
  frame: { src: string; width: number; height: number };
  onDone: (selection: { x: number; y: number; width: number; height: number } | null) => void;
}) {
  const t = useI18n();
  const imageRef = React.useRef<HTMLImageElement>(null);
  const [start, setStart] = React.useState<Point | null>(null);
  const [end, setEnd] = React.useState<Point | null>(null);
  const [area, setArea] = React.useState(() => ({ width: window.innerWidth, height: Math.max(1, window.innerHeight - top) }));

  React.useEffect(() => {
    const stopKeys = listenKeys(window, (event) => {
      if (event.key === "Escape") onDone(null);
    });
    const onResize = () => setArea({ width: window.innerWidth, height: Math.max(1, window.innerHeight - top) });
    window.addEventListener("resize", onResize);
    return () => {
      stopKeys();
      window.removeEventListener("resize", onResize);
    };
  }, [onDone, top]);

  const size = frameDisplaySize(frame, area);
  const box = () => {
    const rect = imageRef.current?.getBoundingClientRect();
    return { left: rect?.left ?? 0, top: rect?.top ?? top, width: rect?.width || size.width, height: rect?.height || size.height };
  };
  const rect = start && end
    ? { left: Math.min(start.x, end.x), top: Math.min(start.y, end.y), width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y) }
    : null;

  return createPortal(
    <div
      {...APP_CHROME}
      data-region-overlay=""
      role="dialog"
      aria-label={t("browserToolsShotRegion")}
      style={{ top }}
      className="fixed inset-x-0 bottom-0 z-[200] cursor-crosshair select-none bg-panel"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture?.(event.pointerId);
        setStart({ x: event.clientX, y: event.clientY });
        setEnd({ x: event.clientX, y: event.clientY });
      }}
      onPointerMove={(event) => {
        if (start) setEnd({ x: event.clientX, y: event.clientY });
      }}
      onPointerUp={(event) => {
        if (!start) return;
        const selection = selectionFraction(start, { x: event.clientX, y: event.clientY }, box());
        setStart(null);
        setEnd(null);
        onDone(selection);
      }}
    >
      <img
        ref={imageRef}
        src={frame.src}
        alt=""
        draggable={false}
        style={{ width: size.width, height: size.height }}
        className="pointer-events-none block"
      />
      {/* 框外压暗:框本身用一圈很宽的阴影把外面盖住,框里是原样的画面。 */}
      {rect && (
        <div
          data-region-selection=""
          className="pointer-events-none fixed border-2 border-primary shadow-[0_0_0_9999px_rgb(0_0_0/0.35)]"
          style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
        />
      )}
      <p className="pointer-events-none fixed left-1/2 m-0 -translate-x-1/2 rounded-md bg-popover px-3 py-1.5 text-ui-sm text-foreground" style={{ top: top + 12 }}>
        {t("browserToolsRegionHint")}
      </p>
    </div>,
    document.body,
  );
}
