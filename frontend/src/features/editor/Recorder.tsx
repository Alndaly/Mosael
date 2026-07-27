import React from "react";
import { Circle, Mic, Monitor as ScreenIcon, Square, Video } from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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

  // 输入设备选择:默认设备可能是不出数据的虚拟/连续互通设备(录了半天 0.6s 就是
  // 这么来的),必须能换。选择记进 localStorage,下次直接沿用。
  const [mics, setMics] = React.useState<MediaDeviceInfo[]>([]);
  const [cameras, setCameras] = React.useState<MediaDeviceInfo[]>([]);
  const [micId, setMicId] = React.useState<string>(() => localStorage.getItem("openstudio.recorder.mic") ?? "");
  const [cameraId, setCameraId] = React.useState<string>(() => localStorage.getItem("openstudio.recorder.camera") ?? "");
  const [level, setLevel] = React.useState(0); // 0-1 实时输入电平(有声音才有柱,哑设备当场现形)
  const audioCtxRef = React.useRef<AudioContext | null>(null);
  const levelRafRef = React.useRef<number | null>(null);

  // 枚举设备:label 需要权限,弹窗打开时先请求一次再列(拿到即释放)。
  React.useEffect(() => {
    if (!open) return;
    let disposed = false;
    const enumerate = async () => {
      try {
        const probe = await navigator.mediaDevices.getUserMedia({ audio: true, video: true }).catch(() =>
          navigator.mediaDevices.getUserMedia({ audio: true }),
        );
        probe?.getTracks().forEach((track) => track.stop());
      } catch {
        /* 权限被拒:仍尝试枚举(可能只有无 label 的条目) */
      }
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        if (disposed) return;
        setMics(devices.filter((d) => d.kind === "audioinput" && d.deviceId));
        setCameras(devices.filter((d) => d.kind === "videoinput" && d.deviceId));
      } catch {
        /* 枚举失败:退回默认设备 */
      }
    };
    void enumerate();
    return () => {
      disposed = true;
    };
  }, [open]);

  const stopLevelMeter = React.useCallback(() => {
    if (levelRafRef.current) cancelAnimationFrame(levelRafRef.current);
    levelRafRef.current = null;
    void audioCtxRef.current?.close().catch(() => undefined);
    audioCtxRef.current = null;
    setLevel(0);
  }, []);

  const startLevelMeter = React.useCallback((stream: MediaStream) => {
    if (stream.getAudioTracks().length === 0) return;
    try {
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      audioCtxRef.current = ctx;
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const value of data) peak = Math.max(peak, Math.abs(value - 128) / 128);
        setLevel(peak);
        levelRafRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      /* 电平表纯属提示,失败不影响录制 */
    }
  }, []);

  const cleanup = React.useCallback(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    stopLevelMeter();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, [stopLevelMeter]);

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
      // exact 而不是 ideal:用户点名选的设备拿不到就该报错,而不是静默换一个继续录。
      const audioConstraint: MediaTrackConstraints | boolean = micId ? { deviceId: { exact: micId } } : true;
      const videoConstraint: MediaTrackConstraints | boolean = cameraId ? { deviceId: { exact: cameraId } } : true;
      const stream =
        source === "screen"
          ? await media.getDisplayMedia({ video: true, audio: true })
          : source === "camera"
            ? await media.getUserMedia({ video: videoConstraint, audio: audioConstraint })
            : await media.getUserMedia({ audio: audioConstraint });
      streamRef.current = stream;
      startLevelMeter(stream);
      if (videoRef.current && source !== "mic") {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => undefined);
      }
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => {
        toast.error(t("recordEmpty"));
        cleanup();
        setRecording(false);
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || (source === "mic" ? "audio/webm" : "video/webm");
        const blob = new Blob(chunks, { type });
        const label = source === "mic" ? "录音" : source === "camera" ? "摄像头" : "屏幕录制";
        cleanup();
        // 设备不出数据时 MediaRecorder 只吐 ~110B 的容器头(摄像头/麦克风被占用或
        // 虚拟设备):导入这种空壳只会得到坏素材,拦下并留在弹窗里让用户重试。
        if (blob.size < 2048) {
          toast.error(t("recordEmpty"));
          return;
        }
        onRecorded(new File([blob], `${label}-${Date.now()}.webm`, { type }));
        onOpenChange(false);
      };
      // If the user ends screen sharing from the browser/OS chrome, stop the recording.
      stream.getVideoTracks()[0]?.addEventListener("ended", stop);
      // 1s 切片:数据持续落 chunks,即使收尾环节出岔子也不至于两手空空。
      recorder.start(1000);
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
        <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border w-fit justify-self-start" role="group" aria-label={t("recordTitle")}>
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

        {/* 设备选择 + 输入电平:摄像头/麦克风模式可指定设备;电平柱有声即动,
            哑设备(录了 0 秒那种)当场现形。录制中锁定选择。 */}
        {source !== "screen" && (
          <div className="grid gap-1.5">
            <div className={cn("grid gap-1.5", source === "camera" && "grid-cols-2 max-[560px]:grid-cols-1")}>
              {source === "camera" && (
                <Select
                  value={cameraId || "default"}
                  onValueChange={(next) => {
                    const id = next === "default" ? "" : next;
                    setCameraId(id);
                    localStorage.setItem("openstudio.recorder.camera", id);
                  }}
                  disabled={recording}
                >
                  <SelectTrigger className="h-8" title={t("recordCamera")} aria-label={t("recordCamera")}>
                    <Video size={12} className="shrink-0 text-muted-foreground" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">{t("recordDeviceDefault")}</SelectItem>
                    {cameras.map((device) => (
                      <SelectItem key={device.deviceId} value={device.deviceId}>
                        {device.label || t("recordDeviceUnnamed")}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Select
                value={micId || "default"}
                onValueChange={(next) => {
                  const id = next === "default" ? "" : next;
                  setMicId(id);
                  localStorage.setItem("openstudio.recorder.mic", id);
                }}
                disabled={recording}
              >
                <SelectTrigger className="h-8" title={t("recordMic")} aria-label={t("recordMic")}>
                  <Mic size={12} className="shrink-0 text-muted-foreground" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">{t("recordDeviceDefault")}</SelectItem>
                  {mics.map((device) => (
                    <SelectItem key={device.deviceId} value={device.deviceId}>
                      {device.label || t("recordDeviceUnnamed")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {recording && (
              <div className="flex items-center gap-2" title={t("recordLevel")}>
                <Mic size={11} className="shrink-0 text-muted-foreground" />
                <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-panel-inset">
                  <div
                    className={cn("h-full rounded-full transition-[width] duration-75", level > 0.02 ? "bg-[var(--success)]" : "bg-border-strong")}
                    style={{ width: `${Math.min(100, Math.round(level * 130))}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

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
