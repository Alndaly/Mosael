import React from "react";
import { Pause, Play, Repeat, SkipBack, StepBack, StepForward, Volume2, VolumeX, X } from "lucide-react";

import { assetFileUrl, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { WINDOW_CHROME_HEIGHT, WINDOW_CHROME_INSET } from "@/lib/windowChrome";
import { MIN_CELL, useBestFit } from "./AssetCompareView";
import { formatSeconds } from "./MediaLibraryView";

/**
 * 视频对比:几条视频铺在一屏里**一起播**。
 *
 * 图片对比的灵魂是联动缩放;视频对比的灵魂是**联动时间** —— 各自播放的并排和自己开几个窗口没区别,
 * 比的是「同一时刻」各条长什么样(同一镜头不同模型的生成结果、同一片子的几个导出版本)。所以:
 *
 * - 一套播放控制管所有条:播放 / 暂停、一条共用的时间轴、逐帧前后、倍速、循环;
 * - **最长的那条是时钟**,其余每一帧对着它校正(差出 80ms 以上就拉回来)—— 各自的解码节奏不一样,
 *   不校正的话播几秒就错开了;
 * - 短的播完停在最后一帧,不跳回开头 —— 停在最后一帧才看得出「它到这儿就结束了」;
 * - 默认全部静音(几条声音叠在一起什么也听不清),点某一条上的喇叭只听它。
 */

const RATES = [0.25, 0.5, 1, 2] as const;
/** 跟随的那几条和时钟差出这么多就拉回来。再小会一直在 seek,画面反而卡。 */
const DRIFT = 0.08;

function durationOf(asset: Asset): number {
  const value = Number((asset.media_info ?? {}).duration);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function fpsOf(asset: Asset): number {
  const value = Number((asset.media_info ?? {}).fps);
  return Number.isFinite(value) && value > 0 && value < 240 ? value : 30;
}

function metaOf(asset: Asset): string {
  const info = (asset.media_info ?? {}) as Record<string, unknown>;
  const size = Number(info.width) > 0 && Number(info.height) > 0 ? `${info.width}×${info.height}` : "";
  const fps = Number(info.fps) > 0 ? `${Math.round(Number(info.fps) * 100) / 100}fps` : "";
  return [size, fps, formatSeconds(durationOf(asset))].filter(Boolean).join(" · ");
}

export function VideoCompareView({ assets, onClose }: { assets: Asset[]; onClose: () => void }) {
  const t = useI18n();
  const videos = React.useMemo(() => assets.filter((asset) => asset.kind === "video"), [assets]);
  const refs = React.useRef(new Map<string, HTMLVideoElement>());
  //: 时钟:最长的那一条。它播完,整组才算播完。
  const clock = React.useMemo(
    () => videos.reduce((longest, asset) => (durationOf(asset) > durationOf(longest) ? asset : longest), videos[0]),
    [videos],
  );
  const total = clock ? durationOf(clock) : 0;
  const frame = clock ? 1 / fpsOf(clock) : 1 / 30;

  const [playing, setPlaying] = React.useState(false);
  const [time, setTime] = React.useState(0);
  const [rate, setRate] = React.useState<(typeof RATES)[number]>(1);
  const [loop, setLoop] = React.useState(false);
  const [soundId, setSoundId] = React.useState<string | null>(null);

  const aspect = React.useMemo(() => {
    const ratios = videos
      .map((asset) => Number(asset.media_info?.width) / Number(asset.media_info?.height))
      .filter((ratio) => Number.isFinite(ratio) && ratio > 0)
      .sort((a, b) => a - b);
    return ratios.length ? ratios[Math.floor(ratios.length / 2)] : 16 / 9;
  }, [videos]);
  const { ref: gridRef, layout: fit } = useBestFit(videos.length, aspect);

  /** 所有条跳到同一时刻;比自己长度还靠后的停在最后一帧。 */
  const seekAll = React.useCallback(
    (at: number) => {
      const target = Math.max(0, Math.min(at, total));
      for (const asset of videos) {
        const video = refs.current.get(asset.id);
        if (!video) continue;
        const end = durationOf(asset) || video.duration || 0;
        video.currentTime = Math.min(target, Math.max(0, end - 0.001));
      }
      setTime(target);
    },
    [videos, total],
  );

  const pauseAll = React.useCallback(() => {
    for (const video of refs.current.values()) video.pause();
    setPlaying(false);
  }, []);

  const playAll = React.useCallback(() => {
    // 在结尾按播放:从头来 —— 不然按了没反应(时钟已经停在最后一帧)。
    if (time >= total - frame) seekAll(0);
    for (const asset of videos) {
      const video = refs.current.get(asset.id);
      if (video && video.currentTime < (durationOf(asset) || video.duration) - 0.01) void video.play().catch(() => undefined);
    }
    setPlaying(true);
  }, [videos, time, total, frame, seekAll]);

  // 播放中每一帧:读时钟、校正其余几条、到头了按循环与否收尾。
  React.useEffect(() => {
    if (!playing || !clock) return;
    let handle = 0;
    const tick = () => {
      const master = refs.current.get(clock.id);
      if (master) {
        const now = master.currentTime;
        setTime(now);
        for (const asset of videos) {
          if (asset.id === clock.id) continue;
          const video = refs.current.get(asset.id);
          if (!video) continue;
          const end = durationOf(asset) || video.duration || 0;
          if (now >= end - 0.01) {
            if (!video.paused) video.pause(); // 短的播完停在最后一帧
          } else {
            if (Math.abs(video.currentTime - now) > DRIFT) video.currentTime = now;
            if (video.paused) void video.play().catch(() => undefined);
          }
        }
        if (master.ended || now >= total - 0.01) {
          if (loop) {
            seekAll(0);
            for (const video of refs.current.values()) void video.play().catch(() => undefined);
          } else {
            pauseAll();
            return;
          }
        }
      }
      handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, [playing, clock, videos, total, loop, seekAll, pauseAll]);

  React.useEffect(() => {
    for (const video of refs.current.values()) video.playbackRate = rate;
  }, [rate]);

  React.useEffect(() => {
    for (const [id, video] of refs.current) video.muted = id !== soundId;
  }, [soundId]);

  const step = React.useCallback(
    (direction: 1 | -1) => {
      pauseAll();
      seekAll(time + direction * frame);
    },
    [pauseAll, seekAll, time, frame],
  );

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      else if (event.key === " ") {
        event.preventDefault();
        if (playing) pauseAll();
        else playAll();
      } else if (event.key === "ArrowLeft") step(-1);
      else if (event.key === "ArrowRight") step(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, playing, playAll, pauseAll, step]);

  if (videos.length < 2 || !clock) return null;

  return (
    // 与图片对比同一种覆盖层(系统窗口控件避让、跟随主题的底色),说明见 AssetCompareView。
    <div className="fixed inset-0 z-[140] grid grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto] bg-background text-foreground [.is-desktop_&]:[-webkit-app-region:no-drag]">
      <div
        style={{ minHeight: WINDOW_CHROME_HEIGHT }}
        className={cn(
          "flex items-center gap-1.5 border-b border-border px-3 py-2 [.is-desktop_&]:[-webkit-app-region:drag] [.is-desktop_&_:is(button,a,input,select,[role=button])]:[-webkit-app-region:no-drag]",
          WINDOW_CHROME_INSET,
        )}
      >
        <span className="mr-auto text-ui-sm font-semibold text-foreground">
          {t("mediaCompare")}
          <span className="ml-1.5 font-normal text-muted-foreground">{videos.length}</span>
        </span>
        <Button variant="outline" size="sm" onClick={onClose} aria-label={t("close")}>
          <X size={13} />
        </Button>
      </div>

      <div
        ref={gridRef}
        className={cn("grid min-h-0 gap-2 p-2", fit?.scroll && "content-start overflow-y-auto")}
        style={
          fit
            ? fit.scroll
              ? { gridTemplateColumns: `repeat(${fit.cols}, minmax(0,1fr))`, gridAutoRows: `${MIN_CELL}px` }
              : { gridTemplateColumns: `repeat(${fit.cols}, minmax(0,1fr))`, gridTemplateRows: `repeat(${fit.rows}, minmax(0,1fr))` }
            : { gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }
        }
      >
        {videos.map((asset) => {
          const audible = soundId === asset.id;
          const ended = time >= durationOf(asset) - 0.01 && asset.id !== clock.id;
          return (
            <div key={asset.id} className="relative grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)_auto] overflow-hidden rounded-lg border border-border bg-panel-subtle">
              <div className="relative min-h-0 bg-black">
                <video
                  ref={(element) => {
                    if (element) {
                      element.muted = !audible;
                      element.playbackRate = rate;
                      refs.current.set(asset.id, element);
                    } else refs.current.delete(asset.id);
                  }}
                  src={assetFileUrl(asset.id)}
                  preload="auto"
                  playsInline
                  className="absolute inset-0 h-full w-full object-contain"
                />
                {ended && (
                  <span className="absolute left-2 top-2 rounded-full bg-[rgb(0_0_0/0.6)] px-2 py-0.5 text-ui-2xs font-semibold text-white">
                    {t("videoCompareEnded")}
                  </span>
                )}
              </div>
              <div className="flex min-w-0 items-center gap-2 border-t border-border bg-panel px-2.5 py-1.5">
                <div className="grid min-w-0 flex-1 gap-px">
                  <span className="truncate text-ui-sm font-semibold" title={asset.name}>{asset.name}</span>
                  <span className="timecode truncate text-ui-2xs text-muted-foreground">{metaOf(asset)}</span>
                </div>
                <Button
                  variant={audible ? "secondary" : "ghost"}
                  size="icon-xs"
                  aria-pressed={audible}
                  aria-label={`${t(audible ? "videoCompareMute" : "videoCompareListen")}: ${asset.name}`}
                  title={t(audible ? "videoCompareMute" : "videoCompareListen")}
                  onClick={() => setSoundId(audible ? null : asset.id)}
                >
                  {audible ? <Volume2 /> : <VolumeX />}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {/* 一套播放控制管所有条。 */}
      <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
        <Button variant="outline" size="sm" aria-label={t("videoCompareRestart")} title={t("videoCompareRestart")} onClick={() => seekAll(0)}>
          <SkipBack size={13} />
        </Button>
        <Button variant="outline" size="sm" aria-label={t("videoComparePrevFrame")} title={t("videoComparePrevFrame")} onClick={() => step(-1)}>
          <StepBack size={13} />
        </Button>
        <Button size="sm" aria-label={t(playing ? "videoComparePause" : "videoComparePlay")} onClick={playing ? pauseAll : playAll}>
          {playing ? <Pause size={13} /> : <Play size={13} />}
        </Button>
        <Button variant="outline" size="sm" aria-label={t("videoCompareNextFrame")} title={t("videoCompareNextFrame")} onClick={() => step(1)}>
          <StepForward size={13} />
        </Button>
        <span className="timecode min-w-[5.5rem] text-center text-ui-xs tabular-nums text-muted-foreground">
          {formatSeconds(time)} / {formatSeconds(total)}
        </span>
        <input
          type="range"
          aria-label={t("videoCompareSeek")}
          min={0}
          max={total || 0}
          step={frame}
          value={Math.min(time, total)}
          onChange={(event) => {
            pauseAll();
            seekAll(Number(event.target.value));
          }}
          className="min-w-40 flex-1 accent-[var(--primary)]"
        />
        <div className="flex items-center gap-0.5" role="radiogroup" aria-label={t("videoCompareRate")}>
          {RATES.map((value) => (
            <Button key={value} variant={rate === value ? "secondary" : "ghost"} size="sm" role="radio" aria-checked={rate === value} onClick={() => setRate(value)}>
              {value}×
            </Button>
          ))}
        </div>
        <Button variant={loop ? "secondary" : "outline"} size="sm" aria-pressed={loop} onClick={() => setLoop((current) => !current)}>
          <Repeat size={13} /> {t("videoCompareLoop")}
        </Button>
      </div>
    </div>
  );
}
