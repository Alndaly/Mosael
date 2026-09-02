import React from "react";
import { Maximize2, Music, Pause, Play, Volume2, VolumeX } from "lucide-react";

import { assetFileUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/**
 * 媒体播放的共用机件与音频条 —— 画板、智能体工具结果、素材预览共用一份。
 *
 * **不用原生 controls。** 浏览器自带的那条控件是各家各的样子(Chrome 一套、Safari 又一套),
 * 配色和圆角都不吃主题,深色界面里会突然压进来一条亮条;而且它占掉的高度是浏览器说了算的,
 * 调用方算好的布局会被它挤变形。
 *
 * 视频和音频要的是同一件事(播/停、走到哪儿、多长、静音),所以播放状态和进度条只写一遍:
 * 抄成两份的话,改一处进度条的手感只会改好其中一个。
 *
 * 交互上只有一条规矩,而且它比看起来容易犯错(这条在画板播放器上连着犯过三次):
 *
 * **nodrag 只能挂在真的要吞掉拖动的控件上 —— 也就是进度条(Scrubber 自己内部写死)。**
 * 按钮不需要 nodrag(点一下不是拖动,React Flow 要有位移才开始拖);铺满节点的容器更不要,
 * 挂上就等于整块拖不动。
 */
export function mediaClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** 播放状态。视频和音频都是 HTMLMediaElement —— 这一层不关心它有没有画面。 */
export function usePlayback(ref: React.RefObject<HTMLMediaElement | null>) {
  const [playing, setPlaying] = React.useState(false);
  const [muted, setMuted] = React.useState(false);
  const [at, setAt] = React.useState(0);
  const [total, setTotal] = React.useState(0);

  const toggle = React.useCallback(() => {
    const media = ref.current;
    if (!media) return;
    if (media.paused) void media.play();
    else media.pause();
  }, [ref]);

  const toggleMute = React.useCallback(() => {
    const media = ref.current;
    if (!media) return;
    media.muted = !media.muted;
    setMuted(media.muted);
  }, [ref]);

  //: 绑在元素上的那几个回调 —— 一起交出去,免得两处各绑一半。
  const bind = {
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onTimeUpdate: (event: React.SyntheticEvent<HTMLMediaElement>) => setAt(event.currentTarget.currentTime),
  };

  return { playing, muted, at, total, setTotal, toggle, toggleMute, bind };
}

/**
 * 进度条。按下就跟手,松开才停。
 *
 * **用指针捕获而不是只听 pointerdown** —— 不捕获的话,拖着拖着划出条外就断了,而进度条
 * 只有几个像素高,划出去是常态。
 */
export function Scrubber({
  //: 叫 media 不叫 ref:React 19 里 ref 是函数组件的**保留 prop**(指向这个组件),
  //: 而这里传的是「被控制的那个媒体元素」—— 同名会把两件事混成一件。
  media,
  at,
  total,
  className,
  trackClassName,
}: {
  media: React.RefObject<HTMLMediaElement | null>;
  at: number;
  total: number;
  className?: string;
  trackClassName?: string;
}) {
  const seek = (event: React.PointerEvent<HTMLDivElement>) => {
    const element = media.current;
    const box = event.currentTarget.getBoundingClientRect();
    if (!element || box.width <= 0 || !Number.isFinite(element.duration)) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    element.currentTime = ratio * element.duration;
  };

  return (
    <div
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        seek(event);
      }}
      onPointerMove={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) seek(event);
      }}
      onPointerUp={(event) => event.currentTarget.releasePointerCapture(event.pointerId)}
      className={cn("nodrag nopan group/bar cursor-pointer py-1.5", className)}
    >
      <div className={cn("h-0.5 w-full rounded-full transition-all group-hover/bar:h-1", trackClassName)}>
        <div
          className="h-full rounded-full bg-current"
          style={{ width: `${total > 0 ? Math.min(100, (at / total) * 100) : 0}%` }}
        />
      </div>
    </div>
  );
}

/**
 * 视频播放器:画面 + 悬停才出现的控件条 + 没在播时压一枚大播放键。
 *
 * 画板节点、大图灯箱、智能体工具结果共用这一副面孔 —— 原生 controls 各家各样、
 * 不吃主题,深色界面里会压进来一条亮条(音频条那里同理)。
 *
 * 两条交互规矩(都在画板上真实踩过):
 * - **不挂 nodrag/nowheel/nopan 在画面或整条控件带上** —— 挂上去节点就拖不动、滚轮就卡住;
 *   进度条的 nodrag 写在 Scrubber 自己内部,按钮点一下不是拖动。
 * - 藏起来的控件条**连 pointer-events 一起收掉**,别只靠 opacity —— 透明不等于不吃事件。
 */
export function VideoPlayer({
  assetId,
  assetSrc,
  autoPlay,
  className,
  onNaturalSize,
}: {
  /** 按素材 id 取带令牌的地址。 */
  assetId?: string;
  /** 手上已经是一个地址时直接给。**两者给一个就行。** */
  assetSrc?: string;
  autoPlay?: boolean;
  className?: string;
  /** 画面的自然尺寸 —— 调用方(如画板节点)拿它校正自己的宽高比。 */
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
        //: **这里不挂 nodrag** —— 视频铺满整个容器,挂上去就等于整块都拖不动。
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
          className="absolute inset-0 grid cursor-pointer place-items-center bg-black/10 transition-colors hover:bg-black/20"
        >
          <span className="grid h-9 w-9 place-items-center rounded-full bg-black/55 text-white backdrop-blur">
            <Play size={15} className="translate-x-px" fill="currentColor" />
          </span>
        </button>
      )}

      {/* 控件条悬停才出现;藏起来时连指针事件一起收掉(透明不等于不吃事件)。 */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 translate-y-full bg-gradient-to-t from-black/80 to-transparent px-2 pb-1.5 pt-4 text-white opacity-0 transition-all group-hover/player:pointer-events-auto group-hover/player:translate-y-0 group-hover/player:opacity-100">
        <Scrubber media={ref} at={at} total={total} className="mb-0.5" trackClassName="bg-white/30" />
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label={t(playing ? "boardPause" : "boardPlay")} onClick={toggle} className="cursor-pointer opacity-90 hover:opacity-100">
            {playing ? <Pause size={13} fill="currentColor" /> : <Play size={13} fill="currentColor" />}
          </button>
          <span className="text-ui-2xs tabular-nums opacity-90">
            {mediaClock(at)} / {mediaClock(total)}
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

/**
 * 音频条:摊平成一条 —— 播放键、进度、时长、静音。
 *
 * 和视频不同,音频的**控件一直在**:一段音频除了这条控件之外没有别的可看,藏起来等于
 * 那里什么都没有。画板节点、智能体工具结果、素材预览三处共用这一副面孔。
 */
export function AudioPlayerBar({
  src,
  className,
  showIcon = true,
  autoPlay = false,
}: {
  src: string;
  className?: string;
  showIcon?: boolean;
  autoPlay?: boolean;
}) {
  const t = useI18n();
  const ref = React.useRef<HTMLAudioElement | null>(null);
  const { playing, muted, at, total, setTotal, toggle, toggleMute, bind } = usePlayback(ref);

  return (
    <div className={cn("flex h-full w-full items-center gap-2 px-3 text-muted-foreground", className)}>
      <audio
        ref={ref}
        src={src}
        autoPlay={autoPlay}
        preload="metadata"
        className="hidden"
        onLoadedMetadata={(event) => setTotal(event.currentTarget.duration)}
        {...bind}
      />
      <button
        type="button"
        aria-label={t(playing ? "boardPause" : "boardPlay")}
        onClick={toggle}
        className="grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full bg-primary text-primary-foreground transition-opacity hover:opacity-90"
      >
        {playing ? <Pause size={12} fill="currentColor" /> : <Play size={12} className="translate-x-px" fill="currentColor" />}
      </button>
      {/* 卡片式布局(调用方在上面已经摆了一枚大音符)可以把它关掉,免得一枚条里两枚图标。 */}
      {showIcon && <Music size={13} className="shrink-0 opacity-60" />}
      <Scrubber media={ref} at={at} total={total} className="min-w-0 flex-1 text-primary" trackClassName="bg-border-strong" />
      <span className="shrink-0 text-ui-2xs tabular-nums">
        {mediaClock(at)} / {mediaClock(total)}
      </span>
      <button type="button" aria-label={t(muted ? "boardUnmute" : "boardMute")} onClick={toggleMute} className="shrink-0 cursor-pointer hover:text-foreground">
        {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
      </button>
    </div>
  );
}
