import React from "react";
import { Link2, Unlink } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
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
  aiGenerated = false,
  cut = false,
  linked = false,
  tabbable = false,
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
  onClipFocus,
}: {
  clipId?: string;
  trackId?: string;
  trackKind: string;
  name: string;
  /** 素材已被删除:片段留在原位,但没有画面可放。达芬奇的「媒体脱机」。 */
  offline?: boolean;
  /** 素材是 AI 生成的(见后端 assets/provenance):片段上标一个「AI」角标,一眼看出成片里哪几段要带标识。 */
  aiGenerated?: boolean;
  /** 剪切了、等着粘贴时搬走:变淡 + 虚线框。 */
  cut?: boolean;
  /** 在一个链接组里(画和它分离出去的声音):一起移动、修剪、切分、删除。片段上标一个链环。 */
  linked?: boolean;
  /** 时间线上只有一段在 Tab 序列里(选中的那段,没选中时第一段),其余靠 ⌥ + 方向键走过去。 */
  tabbable?: boolean;
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
  /** 片段拿到焦点时(键盘 Tab 过来)。鼠标按下引起的聚焦由时间线自己分辨、不当成选中。 */
  onClipFocus?: (clipId: string) => void;
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
    animate && "transition-[left,width,transform] duration-160 ease-enter motion-reduce:transition-none",
    selected && "z-[2] border-primary shadow-[0_0_0_1px_var(--primary)]",
    dragging && "z-[3] cursor-grabbing opacity-[0.92] duration-0",
    // 脱机:斜纹 + 警示色。**要一眼看出来**,而不是"这一段颜色好像浅一点" —— 它在成片里
    // 是一个洞,用户必须在时间线上就发现,而不是导出被拒时才知道。斜纹排在轨道底色之后,
    // 靠 tailwind-merge 的后者胜出盖掉 bg-*。
    cut && "border-dashed opacity-50",
    offline &&
      "border-destructive/70 bg-[repeating-linear-gradient(135deg,color-mix(in_srgb,var(--destructive)_26%,transparent)_0_6px,transparent_6px_12px)] text-foreground",
  );

  return (
    // 悬停说明是片段的全名(时间线上短片段的名字只露半截),脱机 / AI 生成的状态也写在里面。
    <Hint label={offline ? `${t("clipOffline")} · ${name}` : aiGenerated ? `${name} · ${t("clipAiGenerated")}` : name}>
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
        data-cut={cut || undefined}
        data-linked={linked || undefined}
        data-testid={clipId ? `clip-${clipId}` : undefined}
        role="button"
        tabIndex={clipId ? (tabbable ? 0 : -1) : undefined}
        onFocus={() => clipId && onClipFocus?.(clipId)}
      >
        {peaks && peaks.length > 0 && (
          <svg className="pointer-events-none absolute inset-x-px inset-y-0.5 h-[calc(100%-4px)] w-[calc(100%-2px)] [&_polygon]:fill-current [&_polygon]:opacity-30" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden>
            <polygon points={waveformPolygonPoints(peaks)} />
          </svg>
        )}
        <span
          className="absolute bottom-0 top-0 z-[2] w-2.5 cursor-ew-resize touch-none bg-[color-mix(in_srgb,currentColor_22%,transparent)] opacity-0 transition-opacity duration-100 after:absolute after:top-1/2 after:h-3 after:w-0.5 after:-translate-y-1/2 after:rounded-full after:bg-current after:opacity-75 after:content-[''] group-hover/clip:opacity-100 group-data-[selected]/clip:opacity-100 [[data-tool=blade]_&]:hidden left-0 rounded-l-md after:left-[3px]"
          data-testid={clipId ? `trim-start-${clipId}` : undefined}
          onPointerDown={(event) => {
            if (event.button === 0 && clipId) onClipTrimPointerDown?.(event, trackId, clipId, "start");
          }}
        />
        <span className="pointer-events-none relative z-[1] flex min-w-0 flex-1 items-center gap-1 px-1.5 text-ui-xs font-semibold">
          {offline && <Unlink size={11} className="shrink-0 text-destructive" aria-hidden />}
          {linked && <Link2 size={11} className="shrink-0 opacity-70" aria-label={t("clipLinked")} />}
          {aiGenerated && (
            <span
              data-ai-badge=""
              aria-hidden
              className="shrink-0 rounded-[3px] border border-current px-0.5 text-[9px] font-bold leading-[11px] opacity-80"
            >
              AI
            </span>
          )}
          <Truncate>{name}</Truncate>
        </span>
        <span
          className="absolute bottom-0 top-0 z-[2] w-2.5 cursor-ew-resize touch-none bg-[color-mix(in_srgb,currentColor_22%,transparent)] opacity-0 transition-opacity duration-100 after:absolute after:top-1/2 after:h-3 after:w-0.5 after:-translate-y-1/2 after:rounded-full after:bg-current after:opacity-75 after:content-[''] group-hover/clip:opacity-100 group-data-[selected]/clip:opacity-100 [[data-tool=blade]_&]:hidden right-0 rounded-r-md after:right-[3px]"
          data-testid={clipId ? `trim-end-${clipId}` : undefined}
          onPointerDown={(event) => {
            if (event.button === 0 && clipId) onClipTrimPointerDown?.(event, trackId, clipId, "end");
          }}
        />
      </div>
    </Hint>
  );
});
