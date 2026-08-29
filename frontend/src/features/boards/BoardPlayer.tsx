import React from "react";
import { Maximize2, Music, Pause, Play, Volume2, VolumeX } from "lucide-react";

import { assetFileUrl } from "@/api/client";
import { cn } from "@/lib/utils";

/**
 * 画板上的播放器 —— 视频和音频各一副面孔,**共用同一套机件**。
 *
 * **不用原生 controls。** 浏览器自带的那条控件是各家各的样子(Chrome 一套、Safari 又一
 * 套),配色和圆角都不吃主题,在一张浅色画布上会突然压进来一条黑条;而且它占掉的高度是
 * 浏览器说了算的,节点按画面比例算好的框会被它挤变形。
 *
 * 视频和音频要的是同一件事(播/停、走到哪儿、多长、静音),所以播放状态和进度条只写一
 * 遍:抄成两份的话,改一处进度条的手感只会改好其中一个。
 *
 * 交互上只有一条规矩,而且它比看起来容易犯错:
 *
 * **nodrag 只能挂在真的要吞掉拖动的控件上 —— 也就是进度条。** 别的都不要:
 *
 * - 挂在铺满节点的东西上(整块容器、盖住全屏的播放键、始终存在的控件条),节点就再也拖
 *   不动了。这条在这个文件里连着犯过三次,每次的症状都一样:「视频节点无法拖动」。
 * - 按钮**不需要** nodrag:点一下不是拖动,React Flow 要有位移才开始拖,onClick 照常发。
 * - 藏起来的控件条别只靠 opacity —— 透明不等于不吃指针事件,那条看不见的带子照样挡着拖动。
 *   要连 pointer-events 一起收掉。
 *
 * 所以 nodrag 写死在 Scrubber 内部(它自己知道自己要拖),别处一律不写。
 */
function clock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** 播放状态。视频和音频都是 HTMLMediaElement —— 这一层不关心它有没有画面。 */
function usePlayback(ref: React.RefObject<HTMLMediaElement | null>) {
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
function Scrubber({
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

export function BoardVideo({
  assetId,
  className,
  onNaturalSize,
}: {
  assetId: string;
  className?: string;
  /** 画面的自然尺寸 —— 节点拿它把自己的宽高比校正成片子的比例。 */
  onNaturalSize?: (width: number, height: number) => void;
}) {
  const ref = React.useRef<HTMLVideoElement | null>(null);
  const { playing, muted, at, total, setTotal, toggle, toggleMute, bind } = usePlayback(ref);

  return (
    <div className={cn("group/player relative h-full w-full overflow-hidden bg-black", className)}>
      <video
        ref={ref}
        src={assetFileUrl(assetId)}
        preload="metadata"
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
          aria-label="播放"
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
      <div className="nodrag nopan nowheel absolute inset-x-0 bottom-0 translate-y-full bg-gradient-to-t from-black/80 to-transparent px-2 pb-1.5 pt-4 text-white opacity-0 transition-all group-hover/player:translate-y-0 group-hover/player:opacity-100">
        <Scrubber media={ref} at={at} total={total} className="mb-0.5" trackClassName="bg-white/30" />
        <div className="flex items-center gap-1.5">
          <button type="button" aria-label={playing ? "暂停" : "播放"} onClick={toggle} className="cursor-pointer opacity-90 hover:opacity-100">
            {playing ? <Pause size={13} fill="currentColor" /> : <Play size={13} fill="currentColor" />}
          </button>
          <span className="text-ui-2xs tabular-nums opacity-90">
            {clock(at)} / {clock(total)}
          </span>
          <button type="button" aria-label={muted ? "取消静音" : "静音"} onClick={toggleMute} className="ml-auto cursor-pointer opacity-90 hover:opacity-100">
            {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
          </button>
          <button type="button" aria-label="全屏" onClick={() => void ref.current?.requestFullscreen?.()} className="cursor-pointer opacity-90 hover:opacity-100">
            <Maximize2 size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * 音频:摊平成一条 —— 播放键、进度、时长、静音。
 *
 * 和视频不同,这里**控件一直在**:一段音频除了这条控件之外没有别的可看,藏起来等于节点
 * 上什么都没有。
 */
export function BoardAudio({ assetId, className }: { assetId: string; className?: string }) {
  const ref = React.useRef<HTMLAudioElement | null>(null);
  const { playing, muted, at, total, setTotal, toggle, toggleMute, bind } = usePlayback(ref);

  return (
    <div className={cn("flex h-full w-full items-center gap-2 px-3 text-muted-foreground", className)}>
      <audio
        ref={ref}
        src={assetFileUrl(assetId)}
        preload="metadata"
        className="hidden"
        onLoadedMetadata={(event) => setTotal(event.currentTarget.duration)}
        {...bind}
      />
      <button
        type="button"
        aria-label={playing ? "暂停" : "播放"}
        onClick={toggle}
        className="grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full bg-primary text-primary-foreground transition-opacity hover:opacity-90"
      >
        {playing ? <Pause size={12} fill="currentColor" /> : <Play size={12} className="translate-x-px" fill="currentColor" />}
      </button>
      <Music size={13} className="shrink-0 opacity-60" />
      <Scrubber media={ref} at={at} total={total} className="min-w-0 flex-1 text-primary" trackClassName="bg-border-strong" />
      <span className="shrink-0 text-ui-2xs tabular-nums">
        {clock(at)} / {clock(total)}
      </span>
      <button type="button" aria-label={muted ? "取消静音" : "静音"} onClick={toggleMute} className="shrink-0 cursor-pointer hover:text-foreground">
        {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
      </button>
    </div>
  );
}
