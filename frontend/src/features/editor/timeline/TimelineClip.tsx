import React from "react";
import { Unlink } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { waveformPolygonPoints } from "@/domain/timeline/waveform";
import { cn } from "@/lib/utils";

/**
 * 时间线上的一段。
 *
 * **memo + 只收稳定的回调**:拖一段时 Timeline 每个 pointermove 都重渲,此前每段都带着现捏的闭包
 * 和自己的一棵右键菜单,三千段的时间线拖一下要两百多毫秒。现在回调以 (trackId, clipId) 为参数、
 * 身份恒定,没变的片段整段跳过;右键菜单是 Timeline 里的**一个**单例,按 `data-clip-id` 认目标。
 *
 * 不传 clipId 的是「幽灵」(跨轨拖动的草稿本体、插入预览切出的尾段):只画,不接事件、不进菜单。
 */
export const TimelineClip = React.memo(function TimelineClip({
  clipId,
  trackId = "",
  trackKind,
  name,
  offline = false,
  left,
  width,
  shiftPx = 0,
  animate = false,
  selected,
  dragging,
  peaks,
  onClipPointerDown,
  onClipTrimPointerDown,
  onClipSelect,
}: {
  clipId?: string;
  trackId?: string;
  trackKind: string;
  name: string;
  /** 素材已被删除:片段留在原位,但没有画面可放。达芬奇的「媒体脱机」。 */
  offline?: boolean;
  left: number;
  width: number;
  /** 相对 left 的水平位移(px):拖拽中的本体与涟漪让位的邻居都走 transform。 */
  shiftPx?: number;
  /** 拖拽期间(含落位帧)开 200ms 过渡;平时关闭,缩放/刷新保持零动画。 */
  animate?: boolean;
  selected: boolean;
  dragging: boolean;
  peaks?: number[];
  onClipPointerDown?: (event: React.PointerEvent, trackId: string, clipId: string) => void;
  onClipTrimPointerDown?: (event: React.PointerEvent, trackId: string, clipId: string, edge: "start" | "end") => void;
  onClipSelect?: (clipId: string) => void;
}) {
  const t = useI18n();
  const className = cn(
    // 视频片段:音频波形只贴底部一条(PR/DaVinci 式),不铺满色块,标签保持可读。
    "group/clip absolute bottom-[5px] top-[5px] flex cursor-grab touch-none select-none items-center overflow-hidden rounded-md border border-[var(--track-video-border)] bg-[var(--track-video-bg)] text-[var(--track-video-text)] [[data-tool=blade]_&]:cursor-crosshair",
    trackKind === "video" && "[&_svg]:inset-auto [&_svg]:bottom-0.5 [&_svg]:left-px [&_svg]:right-px [&_svg]:h-[42%]",
    trackKind === "audio" && "border-[var(--track-audio-border)] bg-[var(--track-audio-bg)] text-[var(--track-audio-text)]",
    trackKind === "subtitle" &&
      "border-[color-mix(in_oklab,var(--track-subtitle-border)_45%,var(--border))] bg-[color-mix(in_oklab,var(--track-subtitle-border)_18%,var(--panel))] text-[var(--track-subtitle-text)]",
    // 松手落位/涟漪让位由这组过渡完成;拖拽本体靠下面的 duration-0 覆盖成 1:1 跟手
    // (依赖 cn/tailwind-merge 的后者胜出,dragging 分支必须排在 animate 之后)。
    animate && "transition-[left,width,transform] duration-200 ease-out motion-reduce:transition-none",
    selected && "z-[2] border-primary shadow-[0_0_0_1px_var(--primary)]",
    dragging && "z-[3] cursor-grabbing opacity-[0.92] duration-0",
    // 脱机:斜纹 + 警示色。**要一眼看出来**,而不是"这一段颜色好像浅一点" —— 它在成片里
    // 是一个洞,用户必须在时间线上就发现,而不是导出被拒时才知道。斜纹排在轨道底色之后,
    // 靠 tailwind-merge 的后者胜出盖掉 bg-*。
    offline &&
      "border-destructive/70 bg-[repeating-linear-gradient(135deg,color-mix(in_srgb,var(--destructive)_26%,transparent)_0_6px,transparent_6px_12px)] text-foreground",
  );

  return (
    <div
      className={className}
      data-clip-id={clipId}
      style={{
        left,
        width,
        // 位移归零时整个移除 transform(而不是写 translate3d(0)):过渡把 none 当
        // 恒等值照常插值,且静止片段不留下多余的合成层。
        transform: shiftPx !== 0 ? `translate3d(${shiftPx}px, 0, 0)` : undefined,
        // 只在拖拽中提示合成层 — 常驻 will-change 会让每个片段都吃一层显存。
        willChange: dragging ? "transform" : undefined,
      }}
      onPointerDown={(event) => {
        if (event.button !== 0 || !clipId) return;
        onClipSelect?.(clipId);
        onClipPointerDown?.(event, trackId, clipId);
      }}
      data-selected={selected || undefined}
      role="button"
      tabIndex={-1}
      title={offline ? `${t("clipOffline")} · ${name}` : name}
    >
      {peaks && peaks.length > 0 && (
        <svg className="pointer-events-none absolute inset-x-px inset-y-0.5 h-[calc(100%-4px)] w-[calc(100%-2px)] [&_polygon]:fill-current [&_polygon]:opacity-30" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden>
          <polygon points={waveformPolygonPoints(peaks)} />
        </svg>
      )}
      <span
        className="absolute bottom-0 top-0 z-[2] w-2.5 cursor-ew-resize touch-none bg-[color-mix(in_srgb,currentColor_22%,transparent)] opacity-0 transition-opacity duration-100 after:absolute after:top-1/2 after:h-3 after:w-0.5 after:-translate-y-1/2 after:rounded-full after:bg-current after:opacity-75 after:content-[''] group-hover/clip:opacity-100 group-data-[selected]/clip:opacity-100 [[data-tool=blade]_&]:hidden left-0 rounded-l-md after:left-[3px]"
        onPointerDown={(event) => {
          if (event.button === 0 && clipId) onClipTrimPointerDown?.(event, trackId, clipId, "start");
        }}
      />
      <span className="pointer-events-none relative z-[1] flex min-w-0 flex-1 items-center gap-1 px-1.5 text-ui-xs font-semibold">
        {offline && <Unlink size={11} className="shrink-0 text-destructive" aria-hidden />}
        <span className="truncate">{name}</span>
      </span>
      <span
        className="absolute bottom-0 top-0 z-[2] w-2.5 cursor-ew-resize touch-none bg-[color-mix(in_srgb,currentColor_22%,transparent)] opacity-0 transition-opacity duration-100 after:absolute after:top-1/2 after:h-3 after:w-0.5 after:-translate-y-1/2 after:rounded-full after:bg-current after:opacity-75 after:content-[''] group-hover/clip:opacity-100 group-data-[selected]/clip:opacity-100 [[data-tool=blade]_&]:hidden right-0 rounded-r-md after:right-[3px]"
        onPointerDown={(event) => {
          if (event.button === 0 && clipId) onClipTrimPointerDown?.(event, trackId, clipId, "end");
        }}
      />
    </div>
  );
});
