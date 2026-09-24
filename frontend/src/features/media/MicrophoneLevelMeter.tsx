import React from "react";
import { Mic } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/** Peaks quieter than this read as silence: a mute or virtual device stays grey. */
const SILENCE = 0.02;
/** Headroom so normal speech fills most of the bar instead of a third of it. */
const GAIN = 1.3;
/** Per-frame fall-off, so the bar decays smoothly instead of flickering between peaks. */
const DECAY = 0.85;

/**
 * A live input level for the microphone carried by `stream`, analysed with Web Audio.
 *
 * Renders nothing when the stream has no audio track: there is no microphone to show. The level
 * is written straight to the bar at most once per animation frame, and only when its displayed
 * value changes, never through React state, so the recorder does not re-render sixty times a
 * second. The audio graph belongs to
 * the stream it analyses: a new stream (another device) builds a new graph, and the old one is
 * disconnected and its AudioContext closed, as on unmount. The graph only reads the stream;
 * stopping the stream's tracks stays with whoever owns them.
 */
export function MicrophoneLevelMeter({ stream, className }: { stream: MediaStream; className?: string }) {
  const t = useI18n();
  const meterRef = React.useRef<HTMLDivElement | null>(null);
  const barRef = React.useRef<HTMLDivElement | null>(null);
  const hasMicrophone = stream.getAudioTracks().length > 0;

  React.useEffect(() => {
    const meter = meterRef.current;
    const bar = barRef.current;
    if (!hasMicrophone || !meter || !bar) return;

    let context: AudioContext;
    let source: MediaStreamAudioSourceNode;
    let analyser: AnalyserNode;
    try {
      context = new AudioContext();
    } catch {
      // Without Web Audio there is no level to show; a bar frozen at zero would read as a mute mic.
      meter.hidden = true;
      return;
    }
    try {
      source = context.createMediaStreamSource(stream);
      analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
    } catch {
      meter.hidden = true;
      void context.close().catch(() => undefined);
      return;
    }
    // A context created outside a user gesture can start suspended.
    void context.resume().catch(() => undefined);

    const samples = new Uint8Array(analyser.fftSize);
    let level = 0;
    let active: boolean | null = null;
    let frame = 0;
    const render = () => {
      analyser.getByteTimeDomainData(samples);
      let peak = 0;
      for (const sample of samples) peak = Math.max(peak, Math.abs(sample - 128) / 128);
      level = Math.max(Math.min(1, peak * GAIN), level * DECAY);
      const shown = level.toFixed(2);
      if (shown !== meter.getAttribute("aria-valuenow")) {
        bar.style.transform = `scaleX(${shown})`;
        meter.setAttribute("aria-valuenow", shown);
      }
      const nextActive = peak > SILENCE;
      if (nextActive !== active) {
        active = nextActive;
        meter.dataset.active = String(active);
      }
      frame = requestAnimationFrame(render);
    };
    frame = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(frame);
      source.disconnect();
      analyser.disconnect();
      void context.close().catch(() => undefined);
      bar.style.transform = "scaleX(0)";
      meter.setAttribute("aria-valuenow", "0");
      delete meter.dataset.active;
      meter.hidden = false;
    };
  }, [hasMicrophone, stream]);

  if (!hasMicrophone) return null;

  return (
    <div
      ref={meterRef}
      role="meter"
      aria-label={t("recordLevel")}
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={0}
      title={t("recordLevel")}
      className={cn("group flex items-center gap-2", className)}
    >
      <Mic size={11} className="shrink-0 text-muted-foreground" />
      <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-panel-inset">
        <div
          ref={barRef}
          className="h-full w-full origin-left rounded-full bg-border-strong group-data-[active=true]:bg-[var(--success)]"
          style={{ transform: "scaleX(0)" }}
        />
      </div>
    </div>
  );
}
