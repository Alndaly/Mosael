import { createMirroredCameraCapture, type CameraCapture } from "./cameraCapture";
import {
  createRecordingSession,
  releaseRecordingInputs,
  type RecordingInput,
  type RecordingKind,
  type RecordingSession,
} from "./recordingSession";

export type RecordingSource = "screen" | "camera" | "screenCamera" | "mic";
export type RecordingPermissionIssue = "screen" | "systemAudio" | "cameraMicrophone" | "microphone";

/**
 * Supplies the stream of the recording's own input devices: camera + microphone for camera
 * sources, the microphone alone for the mic source. Ownership transfers on take(): the recording
 * stops the stream when it ends or fails to start.
 */
export interface RecordingInputSource {
  take(): Promise<MediaStream>;
}

export interface RecordingStartOptions {
  source: RecordingSource;
  captureSystemAudio: boolean;
  inputs: RecordingInputSource;
  mirrorCamera: boolean;
  filenames: Record<RecordingKind, string>;
  requestStop: () => void;
}

export interface ActiveRecording {
  previewStreams: {
    screen: MediaStream | null;
    camera: MediaStream | null;
    /** The stream carrying the recorded microphone, for a live level; null when none is recorded. */
    microphone: MediaStream | null;
  };
}

export interface RecordingController {
  start(options: RecordingStartOptions): Promise<ActiveRecording>;
  stop(): Promise<File[]>;
  cancel(): void;
}

interface RecordingMediaDevices {
  getDisplayMedia(constraints?: DisplayMediaStreamOptions): Promise<MediaStream>;
}

export interface RecordingControllerDependencies {
  mediaDevices: RecordingMediaDevices;
  createSession: typeof createRecordingSession;
  createMirroredCapture(source: MediaStream): CameraCapture;
}

export class RecordingStartError extends Error {
  constructor(
    readonly issue: RecordingPermissionIssue,
    options?: ErrorOptions,
  ) {
    super(`Unable to acquire the requested recording input: ${issue}.`, options);
    this.name = "RecordingStartError";
  }
}

export class RecordingCancelledError extends Error {
  constructor() {
    super("Recording startup was cancelled.");
    this.name = "RecordingCancelledError";
  }
}

function hasLiveAudioTrack(stream: MediaStream): boolean {
  return stream.getAudioTracks().some((track) => track.readyState === "live");
}

function stopStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

/**
 * Owns capture acquisition and the recording session as one lifecycle.
 *
 * React may render or replace preview elements at any time, so no capture reads from or binds
 * to the DOM: previews only display the returned streams. Camera and microphone are not opened
 * here: they come from the caller's input source, which has normally had them open (the camera's
 * exposure settled, the microphone level visible) since before recording, and are taken only
 * after the screen picker succeeds, so a cancelled picker leaves them with the source. Partial acquisition, mirrored-camera
 * resources, native screen-stop events, cancellation during a pending system picker, and
 * concurrent finalization all converge here so every capture has exactly one release path.
 */
export function createRecordingController(
  dependencies: RecordingControllerDependencies = {
    mediaDevices: navigator.mediaDevices,
    createSession: createRecordingSession,
    createMirroredCapture: createMirroredCameraCapture,
  },
): RecordingController {
  let state: "idle" | "starting" | "recording" | "stopping" | "stopped" | "cancelled" | "failed" =
    "idle";
  let session: RecordingSession | null = null;
  let stopPromise: Promise<File[]> | null = null;
  let detachExternalStop: (() => void) | null = null;
  let cancellationRequested = false;

  const detach = () => {
    detachExternalStop?.();
    detachExternalStop = null;
  };

  const assertStarting = () => {
    if (cancellationRequested) throw new RecordingCancelledError();
  };

  const cancel = () => {
    if (state === "cancelled" || state === "stopped") return;
    cancellationRequested = true;
    state = "cancelled";
    detach();
    session?.cancel();
    session = null;
  };

  return {
    async start(options) {
      if (state !== "idle") throw new Error("The recording controller has already been used.");
      state = "starting";

      const acquiredStreams = new Set<MediaStream>();
      const inputs: RecordingInput[] = [];
      let acquisitionIssue: Exclude<RecordingPermissionIssue, "systemAudio"> | null = null;

      const transferToInput = (stream: MediaStream) => acquiredStreams.delete(stream);

      try {
        const capturesScreen = options.source === "screen" || options.source === "screenCamera";
        const capturesCamera = options.source === "camera" || options.source === "screenCamera";
        let screenStream: MediaStream | null = null;
        let cameraStream: MediaStream | null = null;
        let micStream: MediaStream | null = null;

        if (capturesScreen) {
          acquisitionIssue = "screen";
          screenStream = await dependencies.mediaDevices.getDisplayMedia({
            //: **固定 30fps**:不写 frameRate 时 Chromium 按「画面变了才出帧」自适应,出一帧、
            //: 停几帧、再出一帧 —— 在画面里有大片渐变或纯色时,这就是肉眼看到的频闪(维护者
            //: 2026-10-23 报「某些色彩有频闪」)。定住帧率,编码器才有稳定的时间轴可以分配码率。
            video: { frameRate: { ideal: 30, max: 30 } },
            audio: options.captureSystemAudio,
          });
          acquiredStreams.add(screenStream);
          //: 屏幕内容是**细节**型(文字、纯色块、渐变),不是运动型:告诉 Chromium 用 detail 的
          //: 编码策略,它才不会按"运动画面"降帧降质,渐变上的色带 / 闪烁也会少很多。
          for (const track of screenStream.getVideoTracks()) {
            try {
              track.contentHint = "detail";
            } catch {
              /* 不支持 contentHint 的运行时:忽略,固定帧率已经是主要的那一半 */
            }
          }
          assertStarting();
          if (options.captureSystemAudio && !hasLiveAudioTrack(screenStream)) {
            throw new RecordingStartError("systemAudio");
          }
          inputs.push({
            kind: "screen",
            stream: screenStream,
            filenamePrefix: options.filenames.screen,
          });
          transferToInput(screenStream);
        }

        if (capturesCamera) {
          acquisitionIssue = "cameraMicrophone";
          cameraStream = await options.inputs.take();
          acquiredStreams.add(cameraStream);
          assertStarting();

          if (options.mirrorCamera) {
            const capture = dependencies.createMirroredCapture(cameraStream);
            inputs.push({
              kind: "camera",
              stream: capture.stream,
              filenamePrefix: options.filenames.camera,
              release: capture.release,
            });
          } else {
            inputs.push({
              kind: "camera",
              stream: cameraStream,
              filenamePrefix: options.filenames.camera,
            });
          }
          transferToInput(cameraStream);
        }

        if (options.source === "mic") {
          acquisitionIssue = "microphone";
          micStream = await options.inputs.take();
          acquiredStreams.add(micStream);
          assertStarting();
          inputs.push({ kind: "mic", stream: micStream, filenamePrefix: options.filenames.mic });
          transferToInput(micStream);
        }

        acquisitionIssue = null;
        assertStarting();
        session = dependencies.createSession(inputs, {
          onError: () => {
            if (state === "recording") options.requestStop();
          },
        });

        const screenTrack = screenStream?.getVideoTracks()[0];
        if (screenTrack) {
          const requestStop = () => {
            if (state === "recording") options.requestStop();
          };
          screenTrack.addEventListener("ended", requestStop, { once: true });
          detachExternalStop = () => screenTrack.removeEventListener("ended", requestStop);
        }

        session.start();
        state = "recording";
        return {
          // The camera stream carries the recorded microphone; screen audio is not a microphone.
          previewStreams: { screen: screenStream, camera: cameraStream, microphone: cameraStream ?? micStream },
        };
      } catch (error) {
        detach();
        if (session) {
          session.cancel();
          session = null;
        } else {
          releaseRecordingInputs(inputs);
          acquiredStreams.forEach(stopStream);
        }

        if (cancellationRequested || error instanceof RecordingCancelledError) {
          state = "cancelled";
          throw error instanceof RecordingCancelledError ? error : new RecordingCancelledError();
        }
        state = "failed";
        if (error instanceof RecordingStartError) throw error;
        if (acquisitionIssue) throw new RecordingStartError(acquisitionIssue, { cause: error });
        throw error;
      }
    },

    stop() {
      if (stopPromise) return stopPromise;
      if (state !== "recording" || !session) {
        return Promise.reject(new Error("The recording controller is not active."));
      }
      state = "stopping";
      detach();
      const activeSession = session;
      session = null;
      stopPromise = activeSession.stop().finally(() => {
        state = "stopped";
      });
      return stopPromise;
    },

    cancel,
  };
}
