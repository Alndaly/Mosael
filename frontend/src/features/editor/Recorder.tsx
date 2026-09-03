import React from "react";
import {
  Circle,
  FlipHorizontal2,
  Mic,
  Monitor as ScreenIcon,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Square,
  Video,
  Volume2,
} from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { ModalShell } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { createMirroredCameraCapture } from "./cameraCapture";
import { selectableRecordingDevices } from "./recordingDevices";
import {
  createRecordingSession,
  EmptyRecordingError,
  releaseRecordingInputs,
  type RecordingInput,
  type RecordingSession,
} from "./recordingSession";

type Source = "screen" | "camera" | "screenCamera" | "mic";

const SOURCES: readonly Source[] = ["screen", "camera", "screenCamera", "mic"];
const CAMERA_MIRROR_STORAGE_KEY = "mosael.recorder.cameraMirror";
const SYSTEM_AUDIO_STORAGE_KEY = "mosael.recorder.systemAudio";

interface PreviewStreams {
  screen: MediaStream | null;
  camera: MediaStream | null;
}

type PermissionIssue = "screen" | "systemAudio" | "cameraMicrophone" | "microphone";

class SystemAudioUnavailableError extends Error {
  constructor() {
    super("System audio was requested but the display picker did not grant a live audio track.");
    this.name = "SystemAudioUnavailableError";
  }
}

function hasLiveAudioTrack(stream: MediaStream): boolean {
  return stream.getAudioTracks().some((track) => track.readyState === "live");
}

/**
 * A live preview owns the DOM-to-stream binding, rather than treating it as a one-off command.
 * Radix replaces its dialog content when the recorder changes from modal setup to a non-modal
 * floating controller. This component is mounted with the replacement <video>, so the active
 * stream is attached again instead of leaving the new element black.
 */
function LivePreviewVideo({
  stream,
  previewRef,
  ...props
}: React.VideoHTMLAttributes<HTMLVideoElement> & {
  stream: MediaStream | null;
  previewRef: React.MutableRefObject<HTMLVideoElement | null>;
}) {
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const assignRef = React.useCallback(
    (video: HTMLVideoElement | null) => {
      videoRef.current = video;
      previewRef.current = video;
    },
    [previewRef],
  );

  React.useEffect(() => {
    const video = videoRef.current;
    if (!video || !stream) return;
    video.srcObject = stream;
    void video.play().catch(() => undefined);
    return () => {
      if (video.srcObject === stream) video.srcObject = null;
    };
  }, [stream]);

  return <video ref={assignRef} {...props} />;
}

/** Capture screen / webcam / mic via MediaRecorder and hand independent files to the caller.
 *  A screen + camera session deliberately stays as two assets. Screen capture in the packaged
 *  app needs the Electron main-process display-media handler (electron/main.cjs). */
export function Recorder({
  open,
  onOpenChange,
  onRecorded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRecorded: (files: File[]) => void;
}) {
  const t = useI18n();
  const [source, setSource] = React.useState<Source>("screen");
  const capturesScreen = source === "screen" || source === "screenCamera";
  const capturesCamera = source === "camera" || source === "screenCamera";
  const capturesMicrophone = source !== "screen";
  const [recording, setRecording] = React.useState(false);
  const [secs, setSecs] = React.useState(0);
  const [previewStreams, setPreviewStreams] = React.useState<PreviewStreams>({ screen: null, camera: null });
  const screenVideoRef = React.useRef<HTMLVideoElement | null>(null);
  const cameraVideoRef = React.useRef<HTMLVideoElement | null>(null);
  const sessionRef = React.useRef<RecordingSession | null>(null);
  const timerRef = React.useRef<number | null>(null);

  // 输入设备选择:默认设备可能是不出数据的虚拟/连续互通设备(录了半天 0.6s 就是
  // 这么来的),必须能换。选择记进 localStorage,下次直接沿用。
  const [mics, setMics] = React.useState<MediaDeviceInfo[]>([]);
  const [cameras, setCameras] = React.useState<MediaDeviceInfo[]>([]);
  const [micId, setMicId] = React.useState<string>(() => localStorage.getItem("mosael.recorder.mic") ?? "");
  const [cameraId, setCameraId] = React.useState<string>(() => localStorage.getItem("mosael.recorder.camera") ?? "");
  const [mirrorCamera, setMirrorCamera] = React.useState(
    () => localStorage.getItem(CAMERA_MIRROR_STORAGE_KEY) === "true",
  );
  const [captureSystemAudio, setCaptureSystemAudio] = React.useState(
    () => localStorage.getItem(SYSTEM_AUDIO_STORAGE_KEY) !== "false",
  );
  const [permissionIssue, setPermissionIssue] = React.useState<PermissionIssue | null>(null);
  const [inputPermissionsReady, setInputPermissionsReady] = React.useState(false);
  const [requestingPermissions, setRequestingPermissions] = React.useState(false);
  const [level, setLevel] = React.useState(0); // 0-1 实时输入电平(有声音才有柱,哑设备当场现形)
  const audioCtxRef = React.useRef<AudioContext | null>(null);
  const levelRafRef = React.useRef<number | null>(null);

  const enumerateInputDevices = React.useCallback(async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      setMics(selectableRecordingDevices(devices, "audioinput"));
      setCameras(selectableRecordingDevices(devices, "videoinput"));
    } catch {
      /* 枚举失败:退回默认设备。授权操作仍可使用系统默认设备。 */
    }
  }, []);

  // 只枚举，不在弹窗打开时偷偷触发摄像头/麦克风系统授权。用户选择相关录制源后，
  // 通过下面明确的“申请权限”动作授权；授权后再枚举一次即可拿到设备名称。
  React.useEffect(() => {
    if (!open) return;
    void enumerateInputDevices();
  }, [enumerateInputDevices, open]);

  React.useEffect(() => {
    if (!open || recording) return;
    let disposed = false;
    setPermissionIssue(null);
    setInputPermissionsReady(false);
    const bridge = window.mosaelDesktop?.recordingPermissions;
    const check = bridge?.getStatus;
    if (!check) return;

    const readStatuses = async () => {
      if (capturesScreen) {
        const status = await check("screen");
        if (!disposed && (status === "denied" || status === "restricted")) setPermissionIssue("screen");
      }
      const required: Array<"camera" | "microphone"> = [];
      if (capturesCamera) required.push("camera");
      if (capturesMicrophone) required.push("microphone");
      if (required.length === 0) return;
      const statuses = await Promise.all(required.map((kind) => check(kind)));
      if (!disposed) setInputPermissionsReady(statuses.every((status) => status === "granted"));
    };
    void readStatuses().catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [capturesCamera, capturesMicrophone, capturesScreen, open, recording, source]);

  const requestInputPermissions = React.useCallback(async () => {
    setRequestingPermissions(true);
    setPermissionIssue(null);
    const required: Array<"camera" | "microphone"> = [];
    if (capturesCamera) required.push("camera");
    if (capturesMicrophone) required.push("microphone");
    const bridgeRequest = window.mosaelDesktop?.recordingPermissions?.request;
    try {
      let useWebRequest = !bridgeRequest;
      if (bridgeRequest) {
        for (const kind of required) {
          const granted = await bridgeRequest(kind);
          if (granted === false) throw new DOMException(`${kind} permission denied`, "NotAllowedError");
          if (granted === null) useWebRequest = true;
        }
      }
      if (useWebRequest) {
        const probe = await navigator.mediaDevices.getUserMedia({
          video: capturesCamera,
          audio: capturesMicrophone,
        });
        probe.getTracks().forEach((track) => track.stop());
      }
      setInputPermissionsReady(true);
      await enumerateInputDevices();
    } catch {
      setPermissionIssue(capturesCamera ? "cameraMicrophone" : "microphone");
      toast.error(t("recordDenied"));
    } finally {
      setRequestingPermissions(false);
    }
  }, [capturesCamera, capturesMicrophone, enumerateInputDevices, t]);

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

  const cleanupUi = React.useCallback(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    stopLevelMeter();
    setPreviewStreams({ screen: null, camera: null });
    if (screenVideoRef.current) screenVideoRef.current.srcObject = null;
    if (cameraVideoRef.current) cameraVideoRef.current.srcObject = null;
  }, [stopLevelMeter]);

  const cancel = React.useCallback(() => {
    sessionRef.current?.cancel();
    sessionRef.current = null;
    setRecording(false);
    cleanupUi();
  }, [cleanupUi]);

  const stop = React.useCallback(async () => {
    const session = sessionRef.current;
    if (!session) return;
    // Claim the session before awaiting so the Stop button and the OS "stop sharing"
    // event cannot both finalize and import the same files.
    sessionRef.current = null;
    setRecording(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    try {
      const files = await session.stop();
      onRecorded(files);
      onOpenChange(false);
    } catch (error) {
      toast.error(t(error instanceof EmptyRecordingError ? "recordEmpty" : "recordFailed"));
    } finally {
      cleanupUi();
    }
  }, [cleanupUi, onOpenChange, onRecorded, t]);

  // Closing the dialog aborts an in-flight recording.
  React.useEffect(() => {
    if (!open && sessionRef.current) cancel();
  }, [open, cancel]);
  React.useEffect(() => () => cancel(), [cancel]);

  const start = async () => {
    const acquiredStreams: MediaStream[] = [];
    const inputs: RecordingInput[] = [];
    const transferStreamOwnership = (stream: MediaStream) => {
      const index = acquiredStreams.indexOf(stream);
      if (index >= 0) acquiredStreams.splice(index, 1);
    };
    let acquiring: "screen" | "cameraMicrophone" | "microphone" | null = null;
    setPermissionIssue(null);
    try {
      const media = navigator.mediaDevices;
      // exact 而不是 ideal:用户点名选的设备拿不到就该报错,而不是静默换一个继续录。
      const audioConstraint: MediaTrackConstraints | boolean = micId ? { deviceId: { exact: micId } } : true;
      const videoConstraint: MediaTrackConstraints | boolean = cameraId ? { deviceId: { exact: cameraId } } : true;
      let screenStream: MediaStream | null = null;
      let cameraStream: MediaStream | null = null;

      if (capturesScreen) {
        acquiring = "screen";
        screenStream = await media.getDisplayMedia({ video: true, audio: captureSystemAudio });
        acquiredStreams.push(screenStream);
        // macOS may return a perfectly valid screen stream after the user leaves audio disabled
        // in the system picker. Treat that as a rejected requested capability, not a successful
        // recording: silently continuing creates a video that can never contain system sound.
        if (captureSystemAudio && !hasLiveAudioTrack(screenStream)) {
          throw new SystemAudioUnavailableError();
        }
        inputs.push({ kind: "screen", stream: screenStream, filenamePrefix: t("record_screen_file") });
        transferStreamOwnership(screenStream);
      }
      if (capturesCamera) {
        acquiring = "cameraMicrophone";
        cameraStream = await media.getUserMedia({ video: videoConstraint, audio: audioConstraint });
        acquiredStreams.push(cameraStream);
      }
      if (source === "mic") {
        acquiring = "microphone";
        const micStream = await media.getUserMedia({ audio: audioConstraint });
        acquiredStreams.push(micStream);
        inputs.push({ kind: "mic", stream: micStream, filenamePrefix: t("record_mic_file") });
        transferStreamOwnership(micStream);
      }

      if (screenVideoRef.current && screenStream) {
        screenVideoRef.current.srcObject = screenStream;
        void screenVideoRef.current.play().catch(() => undefined);
      }
      if (cameraVideoRef.current && cameraStream) {
        cameraVideoRef.current.srcObject = cameraStream;
        await cameraVideoRef.current.play().catch(() => undefined);
        if (mirrorCamera) {
          const capture = createMirroredCameraCapture(cameraStream, cameraVideoRef.current);
          inputs.push({
            kind: "camera",
            stream: capture.stream,
            filenamePrefix: t("record_camera_file"),
            release: capture.release,
          });
        } else {
          inputs.push({ kind: "camera", stream: cameraStream, filenamePrefix: t("record_camera_file") });
        }
        transferStreamOwnership(cameraStream);
      }
      setPreviewStreams({ screen: screenStream, camera: cameraStream });
      const levelStream = cameraStream ?? screenStream ?? inputs[0]?.stream;
      if (levelStream) startLevelMeter(levelStream);

      const session = createRecordingSession(inputs, { onError: () => void stop() });
      sessionRef.current = session;
      // If the user ends screen sharing from the browser/OS chrome, stop the recording.
      screenStream?.getVideoTracks()[0]?.addEventListener("ended", () => void stop(), { once: true });
      // The session starts every recorder in one synchronous turn and keeps one-second chunks.
      session.start();
      setRecording(true);
      setSecs(0);
      timerRef.current = window.setInterval(() => setSecs((value) => value + 1), 1000);
      setInputPermissionsReady(capturesMicrophone);
    } catch (error) {
      const session = sessionRef.current;
      session?.cancel();
      sessionRef.current = null;
      if (!session) {
        releaseRecordingInputs(inputs);
        acquiredStreams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
      }
      cleanupUi();
      setPermissionIssue(error instanceof SystemAudioUnavailableError ? "systemAudio" : acquiring);
      toast.error(t(error instanceof SystemAudioUnavailableError ? "recordSystemAudioMissing" : "recordDenied"));
    }
  };

  const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => {
        if (!next && recording) return;
        onOpenChange(next);
      }}
      title={t("recordTitle")}
      dismissible={!recording}
      modal={!recording}
      className={cn(
        "w-[520px]",
        recording &&
          "!bottom-3 !left-auto !right-3 !top-auto !w-[360px] !max-w-[calc(100vw-1.5rem)] !translate-x-0 !translate-y-0",
      )}
      bodyClassName={recording ? "px-3 py-3" : undefined}
      footer={
        <div className="flex w-full min-w-0 items-center justify-between gap-4">
          <span className="min-w-0 text-ui-xs leading-[1.4] text-muted-foreground">
            {t(`record_${source}_hint` as never) as string}
          </span>
          {!recording ? (
            <Button className="shrink-0" size="sm" onClick={start}>
              <Circle size={11} className="fill-destructive text-destructive" /> {t("recordStart")}
            </Button>
          ) : (
            <Button className="shrink-0" size="sm" variant="destructive" onClick={stop}>
              <Square size={11} /> {t("recordStop")}
            </Button>
          )}
        </div>
      }
    >
      <div className="grid w-full gap-2.5">
        {!recording && (
          <div
            key="source-picker"
            className="inline-flex h-7 w-fit items-stretch justify-self-start overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border"
            role="group"
            aria-label={t("recordTitle")}
          >
            {SOURCES.map((s) => (
              <button
                key={s}
                type="button"
                className={cn(
                  "inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground",
                  source === s &&
                    "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground",
                )}
                onClick={() => setSource(s)}
              >
                {s === "screen" ? (
                  <ScreenIcon size={13} />
                ) : s === "camera" ? (
                  <Video size={13} />
                ) : s === "screenCamera" ? (
                  <span className="inline-flex items-center -space-x-1" aria-hidden>
                    <ScreenIcon size={13} />
                    <Video size={11} className="rounded-sm bg-current/10" />
                  </span>
                ) : (
                  <Mic size={13} />
                )}{" "}
                {t(`record_${s}` as never)}
              </button>
            ))}
          </div>
        )}
        <div
          key="preview"
          className={cn(
            "relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-lg border border-border bg-panel-inset",
            recording && "bg-black",
          )}
        >
          {/* Video stays mounted for the selected source so refs are stable when start() attaches
              streams. In dual mode the split preview makes the two independent outputs explicit. */}
          {source === "screenCamera" ? (
            <div className="grid h-full w-full grid-cols-2 gap-px bg-border">
              <div className="relative min-w-0 overflow-hidden bg-black">
                <LivePreviewVideo
                  previewRef={screenVideoRef}
                  stream={previewStreams.screen}
                  className="h-full w-full object-contain"
                  muted
                  playsInline
                />
                {recording && (
                  <span className="absolute bottom-2 left-2 rounded-full bg-black/65 px-2 py-0.5 text-ui-xs text-white">
                    {t("record_screen")}
                  </span>
                )}
              </div>
              <div className="relative min-w-0 overflow-hidden bg-black">
                <LivePreviewVideo
                  previewRef={cameraVideoRef}
                  stream={previewStreams.camera}
                  className={cn("h-full w-full object-contain", mirrorCamera && "-scale-x-100")}
                  muted
                  playsInline
                />
                {recording && (
                  <span className="absolute bottom-2 left-2 rounded-full bg-black/65 px-2 py-0.5 text-ui-xs text-white">
                    {t("record_camera")}
                  </span>
                )}
              </div>
            </div>
          ) : source === "screen" ? (
            <LivePreviewVideo
              previewRef={screenVideoRef}
              stream={previewStreams.screen}
              className="h-full w-full bg-black object-contain"
              muted
              playsInline
            />
          ) : source === "camera" ? (
            <LivePreviewVideo
              previewRef={cameraVideoRef}
              stream={previewStreams.camera}
              className={cn("h-full w-full bg-black object-contain", mirrorCamera && "-scale-x-100")}
              muted
              playsInline
            />
          ) : null}
          {recording && source === "mic" && (
            <div className="text-[color-mix(in_oklab,var(--primary)_70%,#fff)]">
              <Mic size={30} />
            </div>
          )}
          {!recording && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-panel-inset text-xs text-muted-foreground">
              {source === "screen" ? (
                <ScreenIcon size={24} />
              ) : source === "camera" ? (
                <Video size={24} />
              ) : source === "screenCamera" ? (
                <span className="inline-flex items-center gap-1" aria-hidden>
                  <ScreenIcon size={24} />
                  <Video size={22} />
                </span>
              ) : (
                <Mic size={24} />
              )}
              <span>{t(`record_${source}_placeholder` as never) as string}</span>
            </div>
          )}
          {recording && (
            <span
              className="absolute left-2.5 top-2.5 h-2.5 w-2.5 animate-recorder-blink rounded-full bg-destructive"
              aria-hidden
            />
          )}
          <span className="timecode absolute bottom-2 right-2.5 tabular-nums text-white [text-shadow:0_1px_3px_rgb(0_0_0/0.7)]">
            {fmt(secs)}
          </span>
        </div>

        {capturesScreen && !recording && (
          <label className="flex items-center justify-between gap-4 rounded-lg border border-border bg-panel px-3 py-2.5">
            <span className="flex min-w-0 items-start gap-2">
              <Volume2 size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
              <span className="grid min-w-0 gap-0.5">
                <span className="text-xs font-medium text-foreground">{t("recordSystemAudio")}</span>
                <span className="text-ui-xs leading-[1.4] text-muted-foreground">{t("recordSystemAudioHint")}</span>
              </span>
            </span>
            <Switch
              checked={captureSystemAudio}
              onCheckedChange={(checked) => {
                setCaptureSystemAudio(checked);
                localStorage.setItem(SYSTEM_AUDIO_STORAGE_KEY, String(checked));
              }}
              aria-label={t("recordSystemAudio")}
            />
          </label>
        )}

        {capturesMicrophone && !recording && !inputPermissionsReady && !permissionIssue && (
          <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-panel px-3 py-2.5">
            <span className="flex min-w-0 items-start gap-2">
              <ShieldCheck size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
              <span className="grid min-w-0 gap-0.5">
                <span className="text-xs font-medium text-foreground">{t("recordPermissionsTitle")}</span>
                <span className="text-ui-xs leading-[1.4] text-muted-foreground">{t("recordPermissionsHint")}</span>
              </span>
            </span>
            <Button
              className="shrink-0"
              size="sm"
              variant="outline"
              disabled={requestingPermissions}
              onClick={() => void requestInputPermissions()}
            >
              {t("recordRequestPermissions")}
            </Button>
          </div>
        )}

        {permissionIssue && !recording && (
          <div
            role="alert"
            className="grid gap-2 rounded-lg border border-destructive/35 bg-destructive/5 px-3 py-2.5"
          >
            <span className="flex min-w-0 items-start gap-2">
              <ShieldAlert size={14} className="mt-0.5 shrink-0 text-destructive" />
              <span className="grid min-w-0 gap-0.5">
                <span className="text-xs font-medium text-foreground">
                  {t(
                    permissionIssue === "systemAudio"
                      ? "recordSystemAudioPermissionTitle"
                      : permissionIssue === "screen"
                        ? "recordScreenPermissionTitle"
                        : "recordInputPermissionTitle",
                  )}
                </span>
                <span className="text-ui-xs leading-[1.4] text-muted-foreground">
                  {t(
                    permissionIssue === "systemAudio"
                      ? "recordSystemAudioPermissionHint"
                      : permissionIssue === "screen"
                        ? "recordScreenPermissionHint"
                        : "recordInputPermissionHint",
                  )}
                </span>
              </span>
            </span>
            <div className="flex flex-wrap justify-end gap-2">
              {(permissionIssue === "screen" || permissionIssue === "systemAudio") &&
                window.mosaelDesktop?.recordingPermissions?.openSettings && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void window.mosaelDesktop?.recordingPermissions?.openSettings?.("screen")}
                  >
                    <Settings size={12} /> {t("recordOpenSystemSettings")}
                  </Button>
                )}
              {(permissionIssue === "cameraMicrophone" || permissionIssue === "microphone") && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={requestingPermissions}
                  onClick={() => void requestInputPermissions()}
                >
                  {t("recordRequestPermissions")}
                </Button>
              )}
              {(permissionIssue === "cameraMicrophone" || permissionIssue === "microphone") &&
                window.mosaelDesktop?.recordingPermissions?.openSettings && (
                  <>
                    {permissionIssue === "cameraMicrophone" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          void window.mosaelDesktop?.recordingPermissions?.openSettings?.("camera")
                        }
                      >
                        <Settings size={12} /> {t("recordOpenCameraSettings")}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        void window.mosaelDesktop?.recordingPermissions?.openSettings?.("microphone")
                      }
                    >
                      <Settings size={12} /> {t("recordOpenMicrophoneSettings")}
                    </Button>
                  </>
                )}
              <Button size="sm" onClick={() => void start()}>
                {t("recordRetry")}
              </Button>
            </div>
          </div>
        )}

        {/* 设备选择 + 输入电平:摄像头/麦克风模式可指定设备;电平柱有声即动,
            哑设备(录了 0 秒那种)当场现形。录制中锁定选择。 */}
        {capturesMicrophone && !recording && (
          <div className="grid gap-1.5">
            <div
              className={cn(
                "grid gap-1.5",
                capturesCamera && "grid-cols-2 max-[560px]:grid-cols-1",
              )}
            >
              {capturesCamera && (
                <Select
                  value={cameraId || "default"}
                  onValueChange={(next) => {
                    const id = next === "default" ? "" : next;
                    setCameraId(id);
                    localStorage.setItem("mosael.recorder.camera", id);
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
                  localStorage.setItem("mosael.recorder.mic", id);
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
            {capturesCamera && (
              <label className="flex min-h-8 items-center justify-between gap-3 rounded-md border border-border bg-field px-3 py-1.5">
                <span className="inline-flex min-w-0 items-center gap-2 text-ui-sm">
                  <FlipHorizontal2 size={13} className="shrink-0 text-muted-foreground" />
                  <span>{t("recordCameraMirror")}</span>
                </span>
                <Switch
                  aria-label={t("recordCameraMirror")}
                  checked={mirrorCamera}
                  disabled={recording}
                  onCheckedChange={(checked) => {
                    setMirrorCamera(checked);
                    localStorage.setItem(CAMERA_MIRROR_STORAGE_KEY, String(checked));
                  }}
                />
              </label>
            )}
            {recording && (
              <div className="flex items-center gap-2" title={t("recordLevel")}>
                <Mic size={11} className="shrink-0 text-muted-foreground" />
                <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-panel-inset">
                  <div
                    className={cn(
                      "h-full rounded-full transition-[width] duration-75",
                      level > 0.02 ? "bg-[var(--success)]" : "bg-border-strong",
                    )}
                    style={{ width: `${Math.min(100, Math.round(level * 130))}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </ModalShell>
  );
}
