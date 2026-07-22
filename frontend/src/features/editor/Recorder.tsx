import React from "react";
import { Circle, Mic, Monitor as ScreenIcon, Square, Video } from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { cn } from "@/lib/utils";

type Source = "screen" | "camera" | "mic";

/** Capture screen / webcam / mic via MediaRecorder → hand the recorded File to the caller
 *  (imported as an asset). Screen capture in the packaged app needs the Electron main-process
 *  display-media handler (electron/main.cjs). */
export function Recorder({
  open,
  onOpenChange,
  onRecorded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRecorded: (file: File) => void;
}) {
  const t = useI18n();
  const [source, setSource] = React.useState<Source>("screen");
  const [recording, setRecording] = React.useState(false);
  const [secs, setSecs] = React.useState(0);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const streamRef = React.useRef<MediaStream | null>(null);
  const timerRef = React.useRef<number | null>(null);

  const cleanup = React.useCallback(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const stop = React.useCallback(() => {
    recorderRef.current?.stop(); // onstop emits the file + cleans up
    recorderRef.current = null;
    setRecording(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  // Closing the dialog aborts an in-flight recording.
  React.useEffect(() => {
    if (!open && recorderRef.current) {
      recorderRef.current.ondataavailable = null;
      recorderRef.current.onstop = null;
      recorderRef.current.stop();
      recorderRef.current = null;
      setRecording(false);
      cleanup();
    }
  }, [open, cleanup]);
  React.useEffect(() => () => cleanup(), [cleanup]);

  const start = async () => {
    try {
      const media = navigator.mediaDevices;
      const stream =
        source === "screen"
          ? await media.getDisplayMedia({ video: true, audio: true })
          : source === "camera"
            ? await media.getUserMedia({ video: true, audio: true })
            : await media.getUserMedia({ audio: true });
      streamRef.current = stream;
      if (videoRef.current && source !== "mic") {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => undefined);
      }
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || (source === "mic" ? "audio/webm" : "video/webm");
        const blob = new Blob(chunks, { type });
        const label = source === "mic" ? "录音" : source === "camera" ? "摄像头" : "屏幕录制";
        cleanup();
        if (blob.size > 0) onRecorded(new File([blob], `${label}-${Date.now()}.webm`, { type }));
        onOpenChange(false);
      };
      // If the user ends screen sharing from the browser/OS chrome, stop the recording.
      stream.getVideoTracks()[0]?.addEventListener("ended", stop);
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      setSecs(0);
      timerRef.current = window.setInterval(() => setSecs((value) => value + 1), 1000);
    } catch {
      toast.error(t("recordDenied"));
    }
  };

  const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={t("recordTitle")} className="w-[520px]">
      <div className="grid w-full gap-2.5">
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border w-fit justify-self-start" role="group" aria-label={t("recordTitle")}>
          {(["screen", "camera", "mic"] as Source[]).map((s) => (
            <button
              key={s}
              type="button"
              disabled={recording}
              className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", source === s && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
              onClick={() => setSource(s)}
            >
              {s === "screen" ? <ScreenIcon size={13} /> : s === "camera" ? <Video size={13} /> : <Mic size={13} />}{" "}
              {t(`record_${s}` as never)}
            </button>
          ))}
        </div>
        <div className={cn("relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-lg border border-border bg-panel-inset", recording && "bg-black")}>
          {/* Video stays mounted for screen/camera so the ref is stable when start() attaches
              the stream; the idle placeholder covers it until recording begins. */}
          {source !== "mic" && <video ref={videoRef} className="h-full w-full bg-black object-contain" muted playsInline />}
          {recording && source === "mic" && (
            <div className="text-[color-mix(in_oklab,var(--primary)_70%,#fff)]">
              <Mic size={30} />
            </div>
          )}
          {!recording && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-panel-inset text-xs text-muted-foreground">
              {source === "screen" ? <ScreenIcon size={24} /> : source === "camera" ? <Video size={24} /> : <Mic size={24} />}
              <span>{t(`record_${source}_placeholder` as never) as string}</span>
            </div>
          )}
          {recording && <span className="absolute left-2.5 top-2.5 h-2.5 w-2.5 animate-recorder-blink rounded-full bg-destructive" aria-hidden />}
          <span className="timecode absolute bottom-2 right-2.5 tabular-nums text-white [text-shadow:0_1px_3px_rgb(0_0_0/0.7)]">{fmt(secs)}</span>
        </div>
        <div className="flex items-center gap-2.5">
          {!recording ? (
            <Button size="sm" onClick={start}>
              <Circle size={11} className="fill-destructive text-destructive" /> {t("recordStart")}
            </Button>
          ) : (
            <Button size="sm" variant="destructive" onClick={stop}>
              <Square size={11} /> {t("recordStop")}
            </Button>
          )}
          <span className="text-[11.5px] text-muted-foreground">{t(`record_${source}_hint` as never) as string}</span>
        </div>
      </div>
    </ModalShell>
  );
}
