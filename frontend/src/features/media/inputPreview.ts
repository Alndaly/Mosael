import { exactRecordingDevice } from "./recordingDevices";

/** The devices a preview opens. A null camera means a microphone-only preview. */
export interface PreviewInputs {
  cameraId: string | null;
  micId: string;
}

export interface InputPreviewState {
  /** The live stream the preview currently owns: camera + microphone, or microphone alone. */
  stream: MediaStream | null;
  /** Why the last acquisition failed; cleared by the next open or close. */
  error: unknown;
}

export interface InputPreview {
  /** Opens these inputs, replacing a stream opened for other inputs. */
  open(inputs: PreviewInputs): void;
  /** Stops the owned stream. A stream already handed over by take() is not affected. */
  close(): void;
  /**
   * Hands the input stream over to a recording. The caller owns the result and must stop it.
   * The already-open stream is reused when it was opened for the same inputs, including one
   * still being acquired; otherwise a new stream is acquired.
   */
  take(inputs: PreviewInputs): Promise<MediaStream>;
  getState(): InputPreviewState;
  subscribe(listener: () => void): () => void;
}

interface Acquisition {
  key: string;
  pending: Promise<MediaStream>;
  stream: MediaStream | null;
  handedOver: boolean;
}

function inputsKey({ cameraId, micId }: PreviewInputs): string {
  return JSON.stringify([cameraId, micId]);
}

function inputConstraints({ cameraId, micId }: PreviewInputs): MediaStreamConstraints {
  const audio = exactRecordingDevice(micId);
  return cameraId === null ? { audio } : { video: exactRecordingDevice(cameraId), audio };
}

function stopStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

const EMPTY_STATE: InputPreviewState = { stream: null, error: null };

/**
 * Owns the camera and microphone that the recorder opens before recording starts.
 *
 * A camera needs a moment after it opens before auto-exposure settles; its first frames are
 * nearly black. Keeping the inputs open while the user is still setting up lets the camera
 * settle, gives a live picture and a live microphone level (a mute device shows up before
 * anything is recorded), and the recording then takes over that very stream instead of opening
 * the devices again at the moment the user presses record. Each stream has exactly one owner:
 * the preview until take(), the recording afterwards. Acquisitions that resolve after being
 * superseded or closed are stopped immediately, so device switches cannot leak a device.
 */
export function createInputPreview(
  mediaDevices: Pick<MediaDevices, "getUserMedia"> = navigator.mediaDevices,
): InputPreview {
  let current: Acquisition | null = null;
  let state = EMPTY_STATE;
  const listeners = new Set<() => void>();

  const setState = (next: InputPreviewState) => {
    if (next.stream === state.stream && next.error === state.error) return;
    state = next;
    listeners.forEach((listener) => listener());
  };

  const release = () => {
    const acquisition = current;
    current = null;
    // A pending acquisition is stopped when it resolves, because it is no longer current.
    if (acquisition?.stream) stopStream(acquisition.stream);
  };

  const acquire = (inputs: PreviewInputs): Acquisition => {
    const acquisition: Acquisition = {
      key: inputsKey(inputs),
      pending: mediaDevices.getUserMedia(inputConstraints(inputs)),
      stream: null,
      handedOver: false,
    };
    acquisition.pending.then(
      (stream) => {
        if (acquisition.handedOver) return;
        if (current !== acquisition) {
          stopStream(stream);
          return;
        }
        acquisition.stream = stream;
        setState({ stream, error: null });
      },
      (error: unknown) => {
        if (acquisition.handedOver || current !== acquisition) return;
        current = null;
        setState({ stream: null, error });
      },
    );
    return acquisition;
  };

  return {
    open(inputs) {
      if (current?.key === inputsKey(inputs)) return;
      release();
      setState(EMPTY_STATE);
      current = acquire(inputs);
    },

    close() {
      release();
      setState(EMPTY_STATE);
    },

    take(inputs) {
      const acquisition = current?.key === inputsKey(inputs) ? current : null;
      if (!acquisition) {
        release();
        setState(EMPTY_STATE);
        return mediaDevices.getUserMedia(inputConstraints(inputs));
      }
      acquisition.handedOver = true;
      current = null;
      setState(EMPTY_STATE);
      return acquisition.stream ? Promise.resolve(acquisition.stream) : acquisition.pending;
    },

    getState: () => state,

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
