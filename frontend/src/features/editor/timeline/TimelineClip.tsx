import React from "react";
import { AudioLines, AudioWaveform, Copy, Mic, Scissors, Trash2, Unlink, Waves } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { waveformPolygonPoints } from "@/domain/timeline/waveform";
import { cn } from "@/lib/utils";

export function TimelineClip({
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
  onPointerDown,
  onTrimPointerDown,
  onSelect,
  onDelete,
  onRippleDelete,
  onSplit,
  onDuplicate,
  onDetachAudio,
  onSeparateAudio,
  onDenoise,
}: {
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
  onPointerDown: (event: React.PointerEvent) => void;
  onTrimPointerDown: (event: React.PointerEvent, edge: "start" | "end") => void;
  onSelect: () => void;
  onDelete?: () => void;
  onRippleDelete?: () => void;
  onSplit?: () => void;
  onDuplicate?: () => void;
  onDetachAudio?: () => void;
  onSeparateAudio?: () => void;
  onDenoise?: () => void;
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

  const clip = (
    <div
      className={className}
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
        if (event.button !== 0) return;
        onSelect();
        onPointerDown(event);
      }}
      onContextMenu={onSelect}
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
          if (event.button === 0) onTrimPointerDown(event, "start");
        }}
      />
      <span className="pointer-events-none relative z-[1] flex min-w-0 flex-1 items-center gap-1 px-1.5 text-ui-xs font-semibold">
        {offline && <Unlink size={11} className="shrink-0 text-destructive" aria-hidden />}
        <span className="truncate">{name}</span>
      </span>
      <span
        className="absolute bottom-0 top-0 z-[2] w-2.5 cursor-ew-resize touch-none bg-[color-mix(in_srgb,currentColor_22%,transparent)] opacity-0 transition-opacity duration-100 after:absolute after:top-1/2 after:h-3 after:w-0.5 after:-translate-y-1/2 after:rounded-full after:bg-current after:opacity-75 after:content-[''] group-hover/clip:opacity-100 group-data-[selected]/clip:opacity-100 [[data-tool=blade]_&]:hidden right-0 rounded-r-md after:right-[3px]"
        onPointerDown={(event) => {
          if (event.button === 0) onTrimPointerDown(event, "end");
        }}
      />
    </div>
  );

  if (!onDelete) return clip;
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{clip}</ContextMenuTrigger>
      <ContextMenuContent>
        {onSplit && (
          <ContextMenuItem onSelect={onSplit}>
            <Scissors /> {t("splitAtPlayhead")}
          </ContextMenuItem>
        )}
        {onDuplicate && (
          <ContextMenuItem onSelect={onDuplicate}>
            <Copy /> {t("duplicateClip")}
          </ContextMenuItem>
        )}
        {onDetachAudio && (
          <ContextMenuItem onSelect={onDetachAudio}>
            <AudioLines /> {t("detachAudio")}
          </ContextMenuItem>
        )}
        {/* 「分离音频」是把视频里的声音摘到单独一条轨(不动内容);这一条是把**声音本身**
            拆成人声和伴奏两份新素材。名字像,做的事是两回事,所以挨着放并各自说清楚。 */}
        {onSeparateAudio && (
          <ContextMenuItem onSelect={onSeparateAudio}>
            <Mic /> {t("separateAudio")}
          </ContextMenuItem>
        )}
        {onDenoise && (
          <ContextMenuItem onSelect={onDenoise}>
            <AudioWaveform /> {t("denoiseAction")}
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
          <Trash2 /> {t("deleteClip")}
        </ContextMenuItem>
        {onRippleDelete && (
          <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={onRippleDelete}>
            <Waves /> {t("rippleDelete")}
          </ContextMenuItem>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}
