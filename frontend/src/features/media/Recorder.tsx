import React from "react";
import {
  Circle,
  FlipHorizontal2,
  Maximize2,
  Minimize2,
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
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { ModalShell } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { createInputPreview } from "./inputPreview";
import { AudioLevelMeter, MicrophoneLevelMeter } from "./MicrophoneLevelMeter";
import { selectableRecordingDevices } from "./recordingDevices";
import {
  createRecordingController,
  RecordingCancelledError,
  RecordingStartError,
  type RecordingController,
  type RecordingPermissionIssue,
  type RecordingSource,
} from "./recordingController";
import { EmptyRecordingError } from "./recordingSession";

const SOURCES: readonly RecordingSource[] = ["screen", "camera", "screenCamera", "mic"];
const CAMERA_MIRROR_STORAGE_KEY = "mosael.recorder.cameraMirror";
/** 录屏时是否同时录麦克风(记住选择)。 */
const SCREEN_MIC_STORAGE_KEY = "mosael.recorder.screenMic";
const SYSTEM_AUDIO_STORAGE_KEY = "mosael.recorder.systemAudio";

type InputPermission = "camera" | "microphone";
type GrantedInputs = Readonly<Record<InputPermission, boolean>>;
const NO_INPUTS_GRANTED: GrantedInputs = { camera: false, microphone: false };

interface PreviewStreams {
  screen: MediaStream | null;
  camera: MediaStream | null;
  microphone: MediaStream | null;
}

const NO_PREVIEW_STREAMS: PreviewStreams = { screen: null, camera: null, microphone: null };

/**
 * A live preview owns the DOM-to-stream binding, rather than treating it as a one-off command.
 * Radix replaces its dialog content when the recorder changes from modal setup to a non-modal
 * floating controller. This component is mounted with the replacement <video>, so the active
 * stream is attached again instead of leaving the new element black. The element is display-only:
 * captures never read frames from it, because the element it replaces is paused once detached.
 */
function LivePreviewVideo({
  stream,
  ...props
}: React.VideoHTMLAttributes<HTMLVideoElement> & {
  stream: MediaStream | null;
}) {
  const videoRef = React.useRef<HTMLVideoElement | null>(null);

  React.useEffect(() => {
    const video = videoRef.current;
    if (!video || !stream) return;
    video.srcObject = stream;
    void video.play().catch(() => undefined);
    return () => {
      if (video.srcObject === stream) video.srcObject = null;
    };
  }, [stream]);

  return <video ref={videoRef} {...props} />;
}

function PreviewPlaceholder({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-panel-inset px-3 text-center text-xs text-muted-foreground">
      {icon}
      <span>{text}</span>
    </div>
  );
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
  const [source, setSource] = React.useState<RecordingSource>("screen");
  const capturesScreen = source === "screen" || source === "screenCamera";
  const capturesCamera = source === "camera" || source === "screenCamera";
  const capturesMicrophone = source !== "screen";
  const [recording, setRecording] = React.useState(false);
  const [minimized, setMinimized] = React.useState(false);
  const [starting, setStarting] = React.useState(false);
  const [stopping, setStopping] = React.useState(false);
  const [secs, setSecs] = React.useState(0);
  const [previewStreams, setPreviewStreams] = React.useState<PreviewStreams>(NO_PREVIEW_STREAMS);
  const controllerRef = React.useRef<RecordingController | null>(null);
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
  /**
   * 录屏幕时**同时录麦克风**(讲课时屏幕里的声音和自己的解说都要)。记住选择。
   *
   * 默认**关**:麦克风在用户点开这个开关之前不该被打开 —— 屏幕上放的东西和"有没有人在听"
   * 是两件事,不能因为选了「屏幕」就默认开始收音。
   */
  const [captureScreenMic, setCaptureScreenMic] = React.useState(() => {
    const stored = localStorage.getItem(SCREEN_MIC_STORAGE_KEY);
    return stored === "1";
  });
  const [captureSystemAudio, setCaptureSystemAudio] = React.useState(
    () => localStorage.getItem(SYSTEM_AUDIO_STORAGE_KEY) !== "false",
  );
  const [permissionIssue, setPermissionIssue] = React.useState<RecordingPermissionIssue | null>(null);
  // Tracked per device kind, so readiness always matches the current source's own inputs: a
  // microphone grant never counts as camera access, and switching between sources that need the
  // same inputs keeps the camera open rather than dropping and reopening it.
  const [grantedInputs, setGrantedInputs] = React.useState<GrantedInputs>(NO_INPUTS_GRANTED);
  const inputPermissionsReady =
    (!capturesCamera || grantedInputs.camera) && (!capturesMicrophone || grantedInputs.microphone);
  const [requestingPermissions, setRequestingPermissions] = React.useState(false);

  // 摄像头/麦克风在录制前就打开:摄像头给出实时预览、让自动曝光在按下「开始录制」前收敛好,
  // 麦克风给出实时电平(哑设备在开录前就现形);开始录制时录制会话直接接管这条流
  // (inputPreview.take),不再重开设备。只在已获授权时打开,不在弹窗打开时偷偷触发系统授权。
  const [inputPreview] = React.useState(() => createInputPreview());
  const inputPreviewState = React.useSyncExternalStore(inputPreview.subscribe, inputPreview.getState);
  // Bumped to retry a failed preview; open() is a no-op while a stream for the inputs is live.
  const [inputPreviewAttempt, setInputPreviewAttempt] = React.useState(0);
  // Every source that records a microphone opens its inputs; a null camera opens the microphone alone.
  const previewCameraId = capturesCamera ? cameraId : null;
  const previewsInputs = open && capturesMicrophone && inputPermissionsReady && !recording && !stopping;
  React.useEffect(() => {
    if (!previewsInputs) {
      inputPreview.close();
      return;
    }
    // A starting recording may be about to take this stream; replacing it now would hand the
    // recording a camera that has not settled. Selection is locked while starting, and a
    // failed start re-runs this effect, which reopens the inputs if they had been taken.
    if (starting) return;
    inputPreview.open({ cameraId: previewCameraId, micId });
  }, [inputPreview, inputPreviewAttempt, micId, previewCameraId, previewsInputs, starting]);
  React.useEffect(() => () => inputPreview.close(), [inputPreview]);
  const inputPreviewFailed = inputPreviewState.error !== null;
  // While recording, the streams the recording owns; before that, the preview's own stream.
  const cameraStream = previewStreams.camera ?? (capturesCamera ? inputPreviewState.stream : null);
  const microphoneStream = recording ? previewStreams.microphone : inputPreviewState.stream;
  //: 录制中要显示的那条电平:有麦克风就看麦克风,否则看屏幕里的系统声音(只录屏幕时最该确认的是它)。
  const recordingMicPresent = Boolean(recording && previewStreams.microphone?.getAudioTracks().length);
  const audioLevelStream = !recording
    ? null
    : recordingMicPresent
      ? previewStreams.microphone
      : previewStreams.screen?.getAudioTracks().length
        ? previewStreams.screen
        : null;
  const visiblePermissionIssue: RecordingPermissionIssue | null =
    permissionIssue ?? (inputPreviewFailed ? (capturesCamera ? "cameraMicrophone" : "microphone") : null);

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
    if (!open) {
      setGrantedInputs(NO_INPUTS_GRANTED);
      return;
    }
    if (recording) return;
    let disposed = false;
    setPermissionIssue(null);
    const bridge = window.mosaelDesktop?.recordingPermissions;
    const check = bridge?.getStatus;
    if (!check) return;

    const readStatuses = async () => {
      if (capturesScreen) {
        const status = await check("screen");
        //: **两个方向都要处理**:拒绝 → 弹出提示;已经允许(用户在系统设置里勾上了)→ 把提示收掉。
        //: 只判前者的话,用户明明授权了,红框还会一直挂在那儿。
        if (!disposed) setPermissionIssue(status === "denied" || status === "restricted" ? "screen" : null);
      }
      const required: InputPermission[] = [];
      if (capturesCamera) required.push("camera");
      if (capturesMicrophone) required.push("microphone");
      if (required.length === 0) return;
      const statuses = await Promise.all(required.map(async (kind) => [kind, await check(kind)] as const));
      if (disposed) return;
      // "unknown" (platforms without a native status) keeps what an explicit request established.
      const known = statuses.filter(([, status]) => status !== "unknown");
      setGrantedInputs((current) => ({
        ...current,
        ...Object.fromEntries(known.map(([kind, status]) => [kind, status === "granted"])),
      }));
    };
    void readStatuses().catch(() => undefined);
    //: 用户去系统设置里勾选、再回到 Mosael:窗口拿到焦点时再读一次状态。
    //: macOS 的授权对**当前进程**不一定立刻生效,但那句提示该不该继续挂着,这里能判断。
    const onFocus = () => void readStatuses().catch(() => undefined);
    window.addEventListener("focus", onFocus);
    const poll = window.setInterval(onFocus, 3_000);
    return () => {
      disposed = true;
      window.removeEventListener("focus", onFocus);
      window.clearInterval(poll);
    };
  }, [capturesCamera, capturesMicrophone, capturesScreen, open, recording, source]);

  const requestInputPermissions = React.useCallback(async () => {
    setRequestingPermissions(true);
    setPermissionIssue(null);
    const required: InputPermission[] = [];
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
      setGrantedInputs((current) => ({ ...current, ...Object.fromEntries(required.map((kind) => [kind, true])) }));
      setInputPreviewAttempt((attempt) => attempt + 1);
      await enumerateInputDevices();
    } catch {
      setPermissionIssue(capturesCamera ? "cameraMicrophone" : "microphone");
      toast.error(t("recordDenied"));
    } finally {
      setRequestingPermissions(false);
    }
  }, [capturesCamera, capturesMicrophone, enumerateInputDevices, t]);

  const cleanupUi = React.useCallback(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    setPreviewStreams(NO_PREVIEW_STREAMS);
  }, []);

  const cancel = React.useCallback(() => {
    controllerRef.current?.cancel();
    controllerRef.current = null;
    setStarting(false);
    setRecording(false);
    setMinimized(false);
    cleanupUi();
  }, [cleanupUi]);

  const stop = React.useCallback(async () => {
    const controller = controllerRef.current;
    if (!controller) return;
    // Claim the controller before awaiting so the Stop button and the OS "stop sharing"
    // event cannot both finalize and import the same files.
    controllerRef.current = null;
    setRecording(false);
    setMinimized(false);
    // Keeps the camera closed while the recording finalizes: a successful stop closes the dialog.
    setStopping(true);
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    try {
      const files = await controller.stop();
      onRecorded(files);
      onOpenChange(false);
    } catch (error) {
      toast.error(t(error instanceof EmptyRecordingError ? "recordEmpty" : "recordFailed"));
    } finally {
      setStopping(false);
      cleanupUi();
    }
  }, [cleanupUi, onOpenChange, onRecorded, t]);

  //: 一旦不在录了,计时归零并停表 —— 别把上一轮的秒数留给下一眼看到的人。
  React.useEffect(() => {
    if (recording) return;
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    setSecs(0);
  }, [recording]);

  // Closing the dialog aborts an in-flight recording.
  React.useEffect(() => {
    if (!open && controllerRef.current) cancel();
  }, [open, cancel]);
  React.useEffect(() => () => cancel(), [cancel]);

  const start = async () => {
    if (controllerRef.current) return;
    setPermissionIssue(null);
    setStarting(true);
    const controller = createRecordingController();
    controllerRef.current = controller;
    try {
      const active = await controller.start({
        source,
        captureSystemAudio,
        //: 只有「纯屏幕」这一档才需要它:摄像头 / 屏幕+摄像头 / 麦克风来源本来就带麦克风
        //: (屏幕+摄像头那条的摄像头流里就有麦克风),再取一次会抢走本该给摄像头的那一份。
        captureMicrophone: source === "screen" && captureScreenMic,
        inputs: { take: () => inputPreview.take({ cameraId: previewCameraId, micId }) },
        mirrorCamera,
        filenames: {
          screen: t("record_screen_file"),
          camera: t("record_camera_file"),
          mic: t("record_mic_file"),
        },
        requestStop: () => void stop(),
      });
      setPreviewStreams(active.previewStreams);
      setStarting(false);
      setRecording(true);
      setMinimized(false);
      setSecs(0);
      timerRef.current = window.setInterval(() => setSecs((value) => value + 1), 1000);
      setGrantedInputs((current) => ({
        camera: current.camera || capturesCamera,
        microphone: current.microphone || capturesMicrophone,
      }));
    } catch (error) {
      if (controllerRef.current === controller) controllerRef.current = null;
      setStarting(false);
      cleanupUi();
      if (error instanceof RecordingCancelledError) return;
      if (error instanceof RecordingStartError) {
        setPermissionIssue(error.issue);
        toast.error(t(error.issue === "systemAudio" ? "recordSystemAudioMissing" : "recordDenied"));
        return;
      }
      toast.error(t("recordFailed"));
    }
  };

  const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  if (recording && minimized) {
    return (
      <div
        data-recording-minimized=""
        role="group"
        aria-label={t("recordInProgress")}
        className="fixed bottom-3 right-3 z-70 flex items-center gap-1 rounded-full border border-floating-border bg-panel/95 py-0.5 pl-1 pr-0.5 text-foreground shadow-[var(--shadow-floating)] backdrop-blur-xl [.is-desktop_&]:[-webkit-app-region:no-drag]"
      >
        <span className="size-1.5 animate-recorder-blink rounded-full bg-destructive" aria-hidden />
        <span className="text-ui-2xs font-semibold">{t("recordInProgress")}</span>
        <span className="timecode tabular-nums text-ui-2xs text-muted-foreground">{fmt(secs)}</span>
        <IconButton
          size="icon-2xs"
          shape="round"
          label={t("recordExpand")}
          onClick={() => setMinimized(false)}
        >
          <Maximize2 />
        </IconButton>
        <IconButton
          size="icon-2xs"
          shape="round"
          label={t("recordStop")}
          onClick={() => void stop()}
          className="text-destructive hover:bg-destructive/10 hover:text-destructive"
        >
          <Square className="fill-current" />
        </IconButton>
      </div>
    );
  }

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => {
        if (!next && recording) return;
        onOpenChange(next);
      }}
      title={t("recordTitle")}
      titleAction={
        recording ? (
          <IconButton size="icon-xs" label={t("recordMinimize")} onClick={() => setMinimized(true)}>
            <Minimize2 />
          </IconButton>
        ) : undefined
      }
      dismissible={!recording}
      modal={!recording}
      className={cn(
        "w-[520px]",
        recording &&
          "!bottom-3 !left-auto !right-3 !top-auto !w-[360px] !max-w-[calc(100vw-1.5rem)] !translate-x-0 !translate-y-0",
      )}
      headerClassName={recording ? "px-3 pb-2 pt-3" : undefined}
      bodyClassName={recording ? "px-3" : undefined}
      footerLayout={recording ? "plain" : "dialog"}
      footerClassName={recording ? "px-3 pb-3 pt-3" : undefined}
      footer={
        <div className={cn("w-full min-w-0", recording ? "flex justify-end" : "grid gap-2")}>
          {!recording && (
            <>
              <Truncate className="min-w-0 text-ui-xs leading-[1.4] text-muted-foreground">
                {t(`record_${source}_hint` as never) as string}
              </Truncate>
              <div className="flex justify-end">
                <Button className="shrink-0" size="sm" disabled={starting || stopping} onClick={start}>
                  <Circle size={11} className="fill-destructive text-destructive" /> {t("recordStart")}
                </Button>
              </div>
            </>
          )}
          {recording && (
            <Button size="sm" variant="destructive" onClick={stop}>
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
                  "inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-100 hover:bg-secondary hover:text-foreground",
                  source === s &&
                    "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground",
                )}
                disabled={starting}
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
          {/* Previews only display streams; recording never reads from them. Before recording
              the camera pane shows the warmed-up preview stream the recording will take over. In
              dual mode the split preview makes the two independent outputs explicit. */}
          {source === "screenCamera" ? (
            <div className="grid h-full w-full grid-cols-2 gap-px bg-border">
              <div className="relative min-w-0 overflow-hidden bg-black">
                <LivePreviewVideo
                  stream={previewStreams.screen}
                  className="h-full w-full object-contain"
                  muted
                  playsInline
                />
                {!previewStreams.screen && (
                  <PreviewPlaceholder icon={<ScreenIcon size={24} />} text={t("record_screen_placeholder")} />
                )}
                {recording && (
                  <span className="absolute bottom-2 left-2 rounded-full bg-black/65 px-2 py-0.5 text-ui-xs text-white">
                    {t("record_screen")}
                  </span>
                )}
              </div>
              <div className="relative min-w-0 overflow-hidden bg-black">
                <LivePreviewVideo
                  stream={cameraStream}
                  className={cn("h-full w-full object-contain", mirrorCamera && "-scale-x-100")}
                  muted
                  playsInline
                />
                {!cameraStream && (
                  <PreviewPlaceholder icon={<Video size={24} />} text={t("record_camera_placeholder")} />
                )}
                {recording && (
                  <span className="absolute bottom-2 left-2 rounded-full bg-black/65 px-2 py-0.5 text-ui-xs text-white">
                    {t("record_camera")}
                  </span>
                )}
              </div>
            </div>
          ) : source === "screen" ? (
            <>
              <LivePreviewVideo
                stream={previewStreams.screen}
                className="h-full w-full bg-black object-contain"
                muted
                playsInline
              />
              {!previewStreams.screen && (
                <PreviewPlaceholder icon={<ScreenIcon size={24} />} text={t("record_screen_placeholder")} />
              )}
            </>
          ) : source === "camera" ? (
            <>
              <LivePreviewVideo
                stream={cameraStream}
                className={cn("h-full w-full bg-black object-contain", mirrorCamera && "-scale-x-100")}
                muted
                playsInline
              />
              {!cameraStream && (
                <PreviewPlaceholder icon={<Video size={24} />} text={t("record_camera_placeholder")} />
              )}
            </>
          ) : recording ? (
            <div className="text-[color-mix(in_oklab,var(--primary)_70%,#fff)]">
              <Mic size={30} />
            </div>
          ) : (
            <PreviewPlaceholder icon={<Mic size={24} />} text={t("record_mic_placeholder")} />
          )}
          {/* 录制中的提示层:左上红点、右下计时、**左下音频电平** —— 三者各占一角,互不相压。
              维护者 2026-10-23:「还是用这个方式,但是音频条放到视频左下角」。 */}
          {recording && (
            <span
              className="absolute left-2.5 top-2.5 h-2.5 w-2.5 animate-recorder-blink rounded-full bg-destructive"
              aria-hidden
            />
          )}
          {recording && audioLevelStream && (
            <div
              className={cn(
                "absolute left-2.5 flex w-32 items-center rounded-full bg-black/55 px-2 py-1 backdrop-blur-sm",
                //: 双画面(屏幕 + 摄像头)时左下有「屏幕」那个小标签,电平往上让一格,别压它。
                source === "screenCamera" ? "bottom-9" : "bottom-2",
              )}
            >
              <AudioLevelMeter
                stream={audioLevelStream}
                kind={recordingMicPresent ? "microphone" : "system"}
                className="w-full"
              />
            </div>
          )}
          {/* 计时器只在**真的在录**的时候走:不在录就显示 00:00 —— 别把上一轮的秒数留给下一眼看到的人。 */}
          <span className="timecode absolute bottom-2 right-2.5 tabular-nums text-white [text-shadow:0_1px_3px_rgb(0_0_0/0.7)]">
            {recording ? fmt(secs) : "00:00"}
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

        {source === "screen" && !recording && (
          //: 屏幕 + 自己的解说:讲课时两样都要。和「系统音频」并排同一形态 —— 它们都是
          //: 「这段画面要不要带上某一路声音」。
          <label className="flex items-center justify-between gap-4 rounded-lg border border-border bg-panel px-3 py-2.5">
            <span className="flex min-w-0 items-start gap-2">
              <Mic size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
              <span className="grid min-w-0 gap-0.5">
                <span className="text-xs font-medium text-foreground">{t("recordScreenMicrophone")}</span>
                <span className="text-ui-xs leading-[1.4] text-muted-foreground">
                  {t("recordScreenMicrophoneHint")}
                </span>
              </span>
            </span>
            <Switch
              checked={captureScreenMic}
              onCheckedChange={(checked) => {
                setCaptureScreenMic(checked);
                localStorage.setItem(SCREEN_MIC_STORAGE_KEY, checked ? "1" : "0");
              }}
              aria-label={t("recordScreenMicrophone")}
            />
          </label>
        )}

        {capturesMicrophone && !recording && !inputPermissionsReady && !visiblePermissionIssue && (
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

        {visiblePermissionIssue && !recording && (
          <div
            role="alert"
            className="grid gap-2 rounded-lg border border-destructive/35 bg-destructive/5 px-3 py-2.5"
          >
            <span className="flex min-w-0 items-start gap-2">
              <ShieldAlert size={14} className="mt-0.5 shrink-0 text-destructive" />
              <span className="grid min-w-0 gap-0.5">
                <span className="text-xs font-medium text-foreground">
                  {t(
                    visiblePermissionIssue === "systemAudio"
                      ? "recordSystemAudioPermissionTitle"
                      : visiblePermissionIssue === "screen"
                        ? "recordScreenPermissionTitle"
                        : "recordInputPermissionTitle",
                  )}
                </span>
                <span className="text-ui-xs leading-[1.4] text-muted-foreground">
                  {t(
                    visiblePermissionIssue === "systemAudio"
                      ? "recordSystemAudioPermissionHint"
                      : visiblePermissionIssue === "screen"
                        ? "recordScreenPermissionHint"
                        : "recordInputPermissionHint",
                  )}
                </span>
              </span>
            </span>
            {visiblePermissionIssue === "screen" && (
              <p className="mt-1 text-ui-xs text-muted-foreground">{t("recordScreenPermissionTwiceHint")}</p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              {(visiblePermissionIssue === "screen" || visiblePermissionIssue === "systemAudio") &&
                window.mosaelDesktop?.recordingPermissions?.openSettings && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void window.mosaelDesktop?.recordingPermissions?.openSettings?.("screen")}
                  >
                    <Settings size={12} /> {t("recordOpenSystemSettings")}
                  </Button>
                )}
              {visiblePermissionIssue === "screen" && window.mosaelDesktop?.recordingPermissions?.prepareScreen && (
                //: macOS 只在应用**真的尝试抓屏**时才把它登记进授权列表。这条按下去就是那次尝试:
                //: 系统会弹「要录制你的屏幕吗」,允许之后**重启应用**才生效(macOS 的要求)。
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void window.mosaelDesktop?.recordingPermissions
                      ?.prepareScreen?.()
                      .then((result) => {
                        //: 系统已经拒过一次就不会再弹框(只能去设置里勾):那种情况主进程会顺手
                        //: 把设置面板打开,这里就把话说成「去列表里勾上 / 手动添加」。
                        toast.info(
                          result?.prompted === false
                            ? t("recordScreenPermissionDeniedHint")
                            : t("recordScreenPermissionPrompted"),
                        );
                      })
                      .catch(() => undefined);
                  }}
                >
                  <Settings size={12} /> {t("recordRequestScreenPermission")}
                </Button>
              )}
              {(visiblePermissionIssue === "cameraMicrophone" || visiblePermissionIssue === "microphone") && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={requestingPermissions}
                  onClick={() => void requestInputPermissions()}
                >
                  {t("recordRequestPermissions")}
                </Button>
              )}
              {(visiblePermissionIssue === "cameraMicrophone" || visiblePermissionIssue === "microphone") &&
                window.mosaelDesktop?.recordingPermissions?.openSettings && (
                  <>
                    {visiblePermissionIssue === "cameraMicrophone" && (
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
              <Button
                size="sm"
                onClick={() =>
                  // A preview failure is retried by reopening the preview, so the recording still
                  // starts from a camera that has settled.
                  permissionIssue === null && inputPreviewFailed
                    ? setInputPreviewAttempt((attempt) => attempt + 1)
                    : void start()
                }
              >
                {t("recordRetry")}
              </Button>
            </div>
          </div>
        )}

        {/* 设备选择:摄像头/麦克风模式可指定设备,录制中锁定选择。 */}
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
                  disabled={recording || starting}
                >
                  <Hint label={t("recordCamera")}>
                    <SelectTrigger size="sm" aria-label={t("recordCamera")}>
                      <Video size={12} className="shrink-0 text-muted-foreground" />
                      <SelectValue />
                    </SelectTrigger>
                  </Hint>
                  <SelectContent>
                    <SelectItem value="default">{t("recordDeviceDefault")}</SelectItem>
                    {cameras.map((device) => (
                      <SelectItem key={device.deviceId} value={device.deviceId} truncate>
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
                disabled={recording || starting}
              >
                <Hint label={t("recordMic")}>
                  <SelectTrigger size="sm" aria-label={t("recordMic")}>
                    <Mic size={12} className="shrink-0 text-muted-foreground" />
                    <SelectValue />
                  </SelectTrigger>
                </Hint>
                <SelectContent>
                  <SelectItem value="default">{t("recordDeviceDefault")}</SelectItem>
                  {mics.map((device) => (
                    <SelectItem key={device.deviceId} value={device.deviceId} truncate>
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
          </div>
        )}

        {/* 输入电平:只要麦克风真的开着(录制前的预览流、录制中接管的同一条流)就显示;
            电平柱有声即动,哑设备(录了 0 秒那种)开录前就现形。换麦克风即换流、换电平。 */}
        {capturesMicrophone && microphoneStream && !recording && <MicrophoneLevelMeter stream={microphoneStream} />}

      </div>
    </ModalShell>
  );
}
