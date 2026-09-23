import { exactRecordingDevice } from "./recordingDevices";

export interface CameraDevices {
  cameraId: string;
  micId: string;
}

export interface CameraPreviewState {
  /** The live camera + microphone stream the preview currently owns. */
  stream: MediaStream | null;
  /** Why the last acquisition failed; cleared by the next open or close. */
  error: unknown;
}

export interface CameraPreview {
  /** Opens the camera for these devices, replacing a stream opened for other devices. */
  open(devices: CameraDevices): void;
  /** Stops the owned stream. A stream already handed over by take() is not affected. */
  close(): void;
  /**
   * Hands the camera stream over to a recording. The caller owns the result and must stop it.
   * The already-open (and so already-exposed) stream is reused when it was opened for the same
   * devices, including one still being acquired; otherwise a new stream is acquired.
   */
  take(devices: CameraDevices): Promise<MediaStream>;
  getState(): CameraPreviewState;
  subscribe(listener: () => void): () => void;
}

interface Acquisition {
  key: string;
  pending: Promise<MediaStream>;
  stream: MediaStream | null;
  handedOver: boolean;
}

function devicesKey({ cameraId, micId }: CameraDevices): string {
  return JSON.stringify([cameraId, micId]);
}

function cameraConstraints({ cameraId, micId }: CameraDevices): MediaStreamConstraints {
  return { video: exactRecordingDevice(cameraId), audio: exactRecordingDevice(micId) };
}

function stopStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

const EMPTY_STATE: CameraPreviewState = { stream: null, error: null };

/**
 * Owns the camera that the recorder opens before recording starts.
 *
 * A camera needs a moment after it opens before auto-exposure settles; its first frames are
 * nearly black. Keeping the camera open while the user is still setting up lets it settle and
 * gives a live preview, and the recording then takes over that very stream instead of opening
 * the camera again at the moment the user presses record. Each stream has exactly one owner:
 * the preview until take(), the recording afterwards. Acquisitions that resolve after being
 * superseded or closed are stopped immediately, so device switches cannot leak a camera.
 */
export function createCameraPreview(
  mediaDevices: Pick<MediaDevices, "getUserMedia"> = navigator.mediaDevices,
): CameraPreview {
  let current: Acquisition | null = null;
  let state = EMPTY_STATE;
  const listeners = new Set<() => void>();

  const setState = (next: CameraPreviewState) => {
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

  const acquire = (devices: CameraDevices): Acquisition => {
    const acquisition: Acquisition = {
      key: devicesKey(devices),
      pending: mediaDevices.getUserMedia(cameraConstraints(devices)),
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
    open(devices) {
      if (current?.key === devicesKey(devices)) return;
      release();
      setState(EMPTY_STATE);
      current = acquire(devices);
    },

    close() {
      release();
      setState(EMPTY_STATE);
    },

    take(devices) {
      const acquisition = current?.key === devicesKey(devices) ? current : null;
      if (!acquisition) {
        release();
        setState(EMPTY_STATE);
        return mediaDevices.getUserMedia(cameraConstraints(devices));
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
