import React from "react";
import { Maximize2, Music2, Pause, Play, Volume2, VolumeX } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { fetchWaveform } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { mediaClock, usePlayback } from "./media-playback";

/** Full preview transport. The viewing area and controls never overlap. */
export function MediaPreviewPlayer({ src, kind, assetId, autoPlay = true }: {
  src: string;
  assetId?: string;
  kind: "audio" | "video";
  autoPlay?: boolean;
}) {
  const t = useI18n();
  const ref = React.useRef<HTMLMediaElement | null>(null);
  const frame = React.useRef<HTMLDivElement>(null);
  const { playing, muted, at, total, error, setTotal, toggle, toggleMute, bind } = usePlayback(ref);
  const [volume, setVolume] = React.useState(1);
  const [speed, setSpeed] = React.useState("1");
  const [peaks, setPeaks] = React.useState<number[]>([]);
  React.useEffect(() => {
    if (kind !== "audio" || !assetId) return;
    let active = true;
    void fetchWaveform(assetId).then((wave) => {
      if (!active || !wave.peaks.length) return;
      const step = Math.max(1, Math.ceil(wave.peaks.length / 96));
      const sampled: number[] = [];
      for (let i = 0; i < wave.peaks.length; i += step) {
        sampled.push(Math.max(...wave.peaks.slice(i, i + step).map((value) => Math.abs(value))));
      }
      const max = Math.max(...sampled, .001);
      setPeaks(sampled.map((value) => value / max));
    }).catch(() => { /* A missing waveform must not prevent playback. */ });
    return () => { active = false; };
  }, [assetId, kind]);
  const duration = Number.isFinite(total) ? total : 0;
  const props = {
    src, autoPlay, preload: "metadata", ...bind,
    onLoadedMetadata: (event: React.SyntheticEvent<HTMLMediaElement>) => setTotal(event.currentTarget.duration),
    onVolumeChange: () => {
      bind.onVolumeChange();
      setVolume(ref.current?.volume ?? 1);
    },
  };

  return (
    <div ref={frame} className="media-preview-player grid h-full min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)_auto] bg-workspace-subtle">
      <div className="relative grid min-h-0 min-w-0 place-items-center overflow-hidden">
        {kind === "video" ? (
          <video {...props} ref={(element) => { ref.current = element; }} playsInline onClick={toggle} className="h-full min-h-0 w-full object-contain" />
        ) : (
          <>
            <audio {...props} ref={(element) => { ref.current = element; }} />
            <div className="grid w-full justify-items-center gap-5 p-8">
              <div className="grid size-16 place-items-center rounded-2xl bg-accent text-primary">
                <Music2 size={28} strokeWidth={1.5} aria-hidden />
              </div>
              {peaks.length > 0 && <svg viewBox={`0 0 ${peaks.length * 4} 64`} className="h-16 w-full max-w-md text-primary" preserveAspectRatio="none" aria-hidden>
                {peaks.map((peak, index) => <rect key={index} x={index * 4} y={32 - Math.max(1, peak * 28)} width={2} height={Math.max(2, peak * 56)} rx={1} fill="currentColor" opacity={index / peaks.length <= at / duration ? .85 : .25} />)}
              </svg>}
            </div>
          </>
        )}
        {error && <p role="status" className="absolute inset-x-4 bottom-4 rounded-lg bg-popover p-3 text-center text-ui-sm text-destructive">{t("mediaPlaybackError")}</p>}
      </div>
      <div className="grid gap-2 border-t border-divider bg-workspace-panel px-4 py-3">
        <input type="range" aria-label={t("mediaSeek")} min={0} max={duration || 1} step="0.01" value={Math.min(at, duration)} disabled={!duration}
          onChange={(event) => { if (ref.current) ref.current.currentTime = Number(event.target.value); }}
          style={{ "--media-progress": `${duration ? at / duration * 100 : 0}%` } as React.CSSProperties}
          className="media-preview-range h-4 w-full cursor-pointer disabled:cursor-default" />
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Button variant="ghost" size="icon-sm" aria-label={t(playing ? "boardPause" : "boardPlay")} onClick={toggle}>
            {playing ? <Pause fill="currentColor" /> : <Play fill="currentColor" />}
          </Button>
          <span className="mr-auto text-ui-xs tabular-nums text-muted-foreground">{mediaClock(at)} / {mediaClock(duration)}</span>
          <Button variant="ghost" size="icon-sm" aria-label={t(muted ? "boardUnmute" : "boardMute")} onClick={toggleMute}>
            {muted || volume === 0 ? <VolumeX /> : <Volume2 />}
          </Button>
          <input type="range" aria-label={t("mediaVolume")} min={0} max={1} step="0.05" value={muted ? 0 : volume}
            onChange={(event) => { if (ref.current) { ref.current.volume = Number(event.target.value); ref.current.muted = false; } }}
            style={{ "--media-progress": `${muted ? 0 : volume * 100}%` } as React.CSSProperties}
            className="media-preview-range h-4 w-16 cursor-pointer" />
          <Select value={speed} onValueChange={(value) => {
            setSpeed(value);
            if (ref.current) ref.current.playbackRate = Number(value);
          }}>
            <SelectTrigger aria-label={t("mediaSpeed")} className="h-8 w-20 border-transparent bg-control text-ui-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{[0.5, 0.75, 1, 1.25, 1.5, 2].map((rate) => <SelectItem key={rate} value={String(rate)}>{rate}×</SelectItem>)}</SelectContent>
          </Select>
          {kind === "video" && <Button variant="ghost" size="icon-sm" aria-label={t("boardFullscreen")} onClick={() => {
            if (document.fullscreenElement === frame.current) void document.exitFullscreen();
            else void frame.current?.requestFullscreen?.();
          }}><Maximize2 /></Button>}
        </div>
      </div>
    </div>
  );
}
