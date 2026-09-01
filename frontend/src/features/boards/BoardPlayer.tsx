import React from "react";
import { Maximize2, Pause, Play, Volume2, VolumeX } from "lucide-react";

import { assetFileUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AudioPlayerBar, mediaClock as clock, Scrubber, usePlayback } from "@/components/app/media-playback";
import { cn } from "@/lib/utils";

/**
 * 画板上的播放器 —— 视频和音频各一副面孔,**共用同一套机件**。
 *
 * 机件(usePlayback / Scrubber / clock)与音频条的面孔住在 components/app/media-playback,
 * 智能体工具结果和素材预览用的是同一副 —— 播放手感全站只有一份,改一处处处生效。
 * 「不用原生 controls」「nodrag 只能挂在进度条上」的完整推理也在那里。
 */

export function BoardVideo({
  assetId,
  assetSrc,
  autoPlay,
  className,
  onNaturalSize,
}: {
  /** 画布节点用它:按 id 取带令牌的地址。 */
  assetId?: string;
  /** 大图预览用它:手上已经是一个地址了。**两者给一个就行。** */
  assetSrc?: string;
  autoPlay?: boolean;
  className?: string;
  /** 画面的自然尺寸 —— 节点拿它把自己的宽高比校正成片子的比例。 */
  onNaturalSize?: (width: number, height: number) => void;
}) {
  const t = useI18n();
  const ref = React.useRef<HTMLVideoElement | null>(null);
  const { playing, muted, at, total, setTotal, toggle, toggleMute, bind } = usePlayback(ref);

  return (
    <div className={cn("group/player relative h-full w-full overflow-hidden bg-black", className)}>
      <video
        ref={ref}
        src={assetSrc ?? assetFileUrl(assetId ?? "")}
        preload="metadata"
        autoPlay={autoPlay}
        playsInline
        //: **这里不挂 nodrag** —— 视频铺满整个节点,挂上去就等于整块都拖不动。
        className="h-full w-full object-contain"
        onClick={toggle}
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
          setTotal(video.duration);
          if (video.videoWidth && video.videoHeight) onNaturalSize?.(video.videoWidth, video.videoHeight);
        }}
        {...bind}
      />

      {/* 没在播时压一个大的播放键 —— 一块静止的画面本身看不出它是段视频。 */}
      {!playing && (
        <button
          type="button"
          aria-label={t("boardPlay")}
          onClick={toggle}
          //: **不带 nodrag** —— 它铺满整个节点,带上就等于整块拖不动;点一下不是拖动,onClick 照发。
          className="absolute inset-0 grid cursor-pointer place-items-center bg-black/10 transition-colors hover:bg-black/20"
        >
          <span className="grid h-9 w-9 place-items-center rounded-full bg-black/55 text-white backdrop-blur">
            <Play size={15} className="translate-x-px" fill="currentColor" />
          </span>
        </button>
      )}

      {/* 控件条:**只有它**吃掉指针事件,画布的拖动和缩放在别处照常。 */}
      {/* **不挂 nowheel/nopan。** 挂上去的话,滚轮划到这条带子上画布就停住 —— 而它有 40px
          高、横跨整个节点,还因为 translate-y-full 悬在节点**下方**:没悬浮时也一直挡着。
          藏起来时连指针事件一起收掉,别只靠 opacity(透明不等于不吃事件)。 */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 translate-y-full bg-gradient-to-t from-black/80 to-transparent px-2 pb-1.5 pt-4 text-white opacity-0 transition-all group-hover/player:pointer-events-auto group-hover/player:translate-y-0 group-hover/player:opacity-100">
        <Scrubber media={ref} at={at} total={total} className="mb-0.5" trackClassName="bg-white/30" />
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label={t(playing ? "boardPause" : "boardPlay")} onClick={toggle} className="cursor-pointer opacity-90 hover:opacity-100">
            {playing ? <Pause size={13} fill="currentColor" /> : <Play size={13} fill="currentColor" />}
          </button>
          <span className="text-ui-2xs tabular-nums opacity-90">
            {clock(at)} / {clock(total)}
          </span>
          <button type="button" aria-label={t(muted ? "boardUnmute" : "boardMute")} onClick={toggleMute} className="ml-auto cursor-pointer opacity-90 hover:opacity-100">
            {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
          </button>
          <button type="button" aria-label={t("boardFullscreen")} onClick={() => void ref.current?.requestFullscreen?.()} className="cursor-pointer opacity-90 hover:opacity-100">
            <Maximize2 size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

/** 画板上的音频节点 —— 面孔是全站共享的 AudioPlayerBar,这里只负责按 id 取带令牌的地址。 */
export function BoardAudio({ assetId, className }: { assetId: string; className?: string }) {
  return <AudioPlayerBar src={assetFileUrl(assetId)} className={className} />;
}
