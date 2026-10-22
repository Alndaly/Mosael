import React from "react";
import { Mic, Volume2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Hint } from "@/components/ui/tooltip";
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
export function AudioLevelMeter({
  stream,
  className,
  kind = "microphone",
}: {
  stream: MediaStream;
  className?: string;
  /** 这一条电平代表哪一路声音:麦克风,还是屏幕里的系统声音。 */
  kind?: "microphone" | "system";
}) {
  const t = useI18n();
  const meterRef = React.useRef<HTMLDivElement | null>(null);
  const barRef = React.useRef<HTMLDivElement | null>(null);
  const hasMicrophone = stream.getAudioTracks().length > 0;
  const label = kind === "system" ? t("recordSystemAudioLevel") : t("recordLevel");
  const Icon = kind === "system" ? Volume2 : Mic;
  //: **设备签名**:换设备(比如换成 iPhone 当麦克风)时,MediaStream 对象可能还是同一个,
  //: 而挂在旧轨道上的分析图永远读静音 —— 表现就是「电平柱一根都不动」。签名变了就重建分析图。
  const trackSignature = stream
    .getAudioTracks()
    .map((track) => `${track.id}:${track.getSettings?.().deviceId ?? ""}`)
    .join("|");

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
    //: 没有用户手势时建出来的 AudioContext 会一直 suspended(读到全零 = 电平柱不动)。
    //: 先试一次,不行就等下一次指针按在这块界面上时再 resume —— 用户迟早会点一下「开始录制」。
    //: 建好就问一次(挂起的话这一步就是唤醒);之后只在还挂着时重试。
    void context.resume().catch(() => undefined);
    const resume = () => {
      //: `state` 拿不到时按「可能挂起」处理 —— 宁可多 resume 一次,也不要读到一屏全零。
      if (context.state !== "running") void context.resume().catch(() => undefined);
    };
    const gesture = () => resume();
    window.addEventListener("pointerdown", gesture, true);
    const resumeTimer = window.setInterval(resume, 500);

    const samples = new Uint8Array(analyser.fftSize);
    const floats = new Float32Array(analyser.fftSize);
    let level = 0;
    let active: boolean | null = null;
    let frame = 0;
    const render = () => {
      analyser.getByteTimeDomainData(samples);
      let peak = 0;
      for (const sample of samples) peak = Math.max(peak, Math.abs(sample - 128) / 128);
      //: byte 读法在个别设备(外接 / Continuity 麦克风)上会给出恒 128(看起来像静音);
      //: 这时再读一次 float 数据,有信号就用它。
      if (peak < 1e-4 && analyser.getFloatTimeDomainData) {
        analyser.getFloatTimeDomainData(floats);
        for (const sample of floats) peak = Math.max(peak, Math.abs(sample));
      }
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
      window.removeEventListener("pointerdown", gesture, true);
      window.clearInterval(resumeTimer);
      cancelAnimationFrame(frame);
      source.disconnect();
      analyser.disconnect();
      void context.close().catch(() => undefined);
      bar.style.transform = "scaleX(0)";
      meter.setAttribute("aria-valuenow", "0");
      delete meter.dataset.active;
      meter.hidden = false;
    };
  }, [hasMicrophone, stream, trackSignature]);

  if (!hasMicrophone) return null;

  return (
    <Hint label={label}>
      <div
        ref={meterRef}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={0}
        className={cn("group flex items-center gap-2", className)}
      >
        <Icon size={11} className="shrink-0 text-muted-foreground" />
        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-panel-inset">
          <div
            ref={barRef}
            className="h-full w-full origin-left rounded-full bg-border-strong group-data-[active=true]:bg-[var(--success)]"
            style={{ transform: "scaleX(0)" }}
          />
        </div>
      </div>
    </Hint>
  );
}

/** 麦克风电平(旧名字,保留给已有的调用点)。 */
export const MicrophoneLevelMeter = AudioLevelMeter;
