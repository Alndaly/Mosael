export type RecordingKind = "screen" | "camera" | "mic";

export interface RecordingInput {
  kind: RecordingKind;
  stream: MediaStream;
  filenamePrefix: string;
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

/**
 * Owns one logical recording session, which may contain several independent captures.
 * Every MediaRecorder starts in the same synchronous turn and every stream is released
 * together. Files are returned only after all captures have finished successfully, so a
 * two-source session cannot silently import half of the expected result.
 */
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
    const recorder = new MediaRecorder(input.stream);
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
    const streams = new Set(inputs.map((input) => input.stream));
    streams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
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
