export type RecordingKind = "screen" | "camera" | "mic";

export interface RecordingInput {
  kind: RecordingKind;
  stream: MediaStream;
  filenamePrefix: string;
  /** Releases resources not represented by `stream`, such as a camera feeding a canvas stream. */
  release?: () => void;
}

export interface RecordingSession {
  start(): void;
  stop(): Promise<File[]>;
  cancel(): void;
}

interface RecordingSessionOptions {
  minimumBytes?: number;
  now?: () => number;
  onError?: (error: Error) => void;
  timesliceMs?: number;
}

export class EmptyRecordingError extends Error {
  constructor(readonly kind: RecordingKind) {
    super(`The ${kind} capture did not contain usable media.`);
    this.name = "EmptyRecordingError";
  }
}

/** Releases every capture resource exactly through the ownership contract declared by its input. */
export function releaseRecordingInputs(inputs: readonly RecordingInput[]): void {
  const streams = new Set(inputs.filter((input) => !input.release).map((input) => input.stream));
  const releases = new Set(inputs.flatMap((input) => (input.release ? [input.release] : [])));
  releases.forEach((release) => release());
  streams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
}

/**
 * Owns one logical recording session, which may contain several independent captures.
 * Every MediaRecorder starts in the same synchronous turn and every stream is released
 * together. Files are returned only after all captures have finished successfully, so a
 * two-source session cannot silently import half of the expected result.
 */
/**
 * MediaRecorder 的参数:**默认值对屏幕内容太省**。
 *
 * 不指定时 Chromium 给的是 VP8 + 约 2.5Mbps —— 录文字和纯色块还过得去,一旦画面里出现大面积
 * 渐变(毛玻璃、阴影、色彩过渡),码率不够就会在色带上"呼吸"式地闪,维护者 2026-10-23 报的
 * 「某些色彩频闪」就是这一类。屏幕内容又不像摄像机画面那样能靠时域冗余省码率:它每个像素都在
 * 详情上,只能给足码率。
 *
 * 顺序上优先 VP9(同码率下渐变明显更干净),不支持才退 VP8 / 裸 webm;音频给 192k 免得
 * 系统声音里的音乐发闷。
 */
function recorderOptions(input: RecordingInput): MediaRecorderOptions {
  if (input.kind === "mic") return { audioBitsPerSecond: 192_000 };
  const video = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find(
    (type) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(type),
  );
  return {
    ...(video ? { mimeType: video } : {}),
    //: 12Mbps 是"屏幕内容"这一档的起点:1080p 的文字/渐变在这个量级上不再需要编码器做取舍。
    videoBitsPerSecond: 12_000_000,
    audioBitsPerSecond: 192_000,
  };
}

export function createRecordingSession(
  inputs: readonly RecordingInput[],
  options: RecordingSessionOptions = {},
): RecordingSession {
  if (inputs.length === 0) throw new Error("A recording session needs at least one capture.");

  const minimumBytes = options.minimumBytes ?? 2048;
  const timesliceMs = options.timesliceMs ?? 1000;
  const timestamp = (options.now ?? Date.now)();
  let state: "idle" | "recording" | "stopping" | "stopped" | "cancelled" = "idle";
  let stopPromise: Promise<File[]> | null = null;
  let released = false;
  let errorReported = false;

  const captures = inputs.map((input) => {
    const recorder = new MediaRecorder(input.stream, recorderOptions(input));
    const chunks: Blob[] = [];
    let failure: Error | null = null;
    let resolveFile!: (file: File) => void;
    let rejectFile!: (error: Error) => void;
    const file = new Promise<File>((resolve, reject) => {
      resolveFile = resolve;
      rejectFile = reject;
    });

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    // MediaRecorder may emit `error` before `stop`. Remember it and reject from the
    // normal completion path, avoiding an unhandled promise rejection mid-recording.
    recorder.onerror = () => {
      failure = new Error(`The ${input.kind} recorder failed.`);
      if (!errorReported) {
        errorReported = true;
        options.onError?.(failure);
      }
    };
    recorder.onstop = () => {
      if (failure) {
        rejectFile(failure);
        return;
      }
      const fallbackType = input.kind === "mic" ? "audio/webm" : "video/webm";
      const type = recorder.mimeType || fallbackType;
      const blob = new Blob(chunks, { type });
      if (blob.size < minimumBytes) {
        rejectFile(new EmptyRecordingError(input.kind));
        return;
      }
      resolveFile(new File([blob], `${input.filenamePrefix}-${timestamp}.webm`, { type }));
    };

    return { input, recorder, file };
  });

  const releaseStreams = () => {
    if (released) return;
    released = true;
    releaseRecordingInputs(inputs);
  };

  const cancel = () => {
    if (state === "cancelled" || state === "stopped") return;
    state = "cancelled";
    for (const { recorder } of captures) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") recorder.stop();
    }
    releaseStreams();
  };

  return {
    start() {
      if (state !== "idle") throw new Error("The recording session has already started.");
      try {
        // Do not await between starts: dual captures should share the same practical start time.
        for (const { recorder } of captures) recorder.start(timesliceMs);
        state = "recording";
      } catch (error) {
        cancel();
        throw error;
      }
    },

    stop() {
      if (stopPromise) return stopPromise;
      if (state !== "recording") return Promise.reject(new Error("The recording session is not active."));

      state = "stopping";
      stopPromise = Promise.all(captures.map(({ file }) => file))
        .then((files) => files)
        .finally(() => {
          state = "stopped";
          releaseStreams();
        });

      for (const { recorder } of captures) {
        if (recorder.state !== "inactive") recorder.stop();
      }
      return stopPromise;
    },

    cancel,
  };
}
