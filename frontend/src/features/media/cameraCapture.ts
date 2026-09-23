export interface CameraCapture {
  stream: MediaStream;
  release(): void;
}

/** Chromium's window-exposed track processor (Electron's renderer is always Chromium). */
interface TrackProcessorGlobal {
  MediaStreamTrackProcessor?: new (init: { track: MediaStreamTrack }) => {
    readonly readable: ReadableStream<VideoFrame>;
  };
}

/**
 * Builds a camera-only recording stream whose video frames are flipped horizontally.
 *
 * Frames are pulled from the camera track itself and each one is mirrored onto a canvas and
 * emitted as exactly one recorded frame. Nothing reads from a DOM <video> element or waits
 * for page rendering: the recorder's preview element is replaced by React when recording
 * starts, and a media element removed from the document pauses, which used to freeze the
 * recording on the camera's first, still under-exposed frames. Source audio passes through
 * unchanged.
 * The returned release function owns both streams so the camera cannot outlive the recording.
 */
export function createMirroredCameraCapture(source: MediaStream): CameraCapture {
  const sourceVideoTrack = source.getVideoTracks()[0];
  if (!sourceVideoTrack) throw new Error("A mirrored camera capture needs a video track.");

  const { MediaStreamTrackProcessor: TrackProcessor } = globalThis as unknown as TrackProcessorGlobal;
  if (!TrackProcessor) throw new Error("Camera mirroring is not supported by this runtime.");

  const canvas = document.createElement("canvas");
  // Keep the default canvas. With `{ alpha: false }` Chromium encodes the frames with a different
  // YUV matrix, and the backend's ffmpeg (thumbnails, proxies, export) then decodes them lighter.
  const context = canvas.getContext("2d");
  if (!context) throw new Error("The camera mirror canvas is unavailable.");

  // Frame rate 0: the canvas only emits a frame when one is requested, i.e. once per camera frame.
  const stream = canvas.captureStream(0);
  const mirroredTrack = stream.getVideoTracks()[0] as CanvasCaptureMediaStreamTrack | undefined;
  if (!mirroredTrack) throw new Error("The camera mirror canvas produced no video track.");
  for (const track of source.getAudioTracks()) stream.addTrack(track);

  const stopMirroring = new AbortController();
  const mirrorFrames = new WritableStream<VideoFrame>({
    write(frame) {
      try {
        const width = frame.displayWidth;
        const height = frame.displayHeight;
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width;
          canvas.height = height;
        }
        context.setTransform(-1, 0, 0, 1, width, 0);
        context.drawImage(frame, 0, 0, width, height);
        mirroredTrack.requestFrame();
      } finally {
        frame.close();
      }
    },
  });
  // The pipe settles when the camera ends or release() aborts it; either way the tracks are
  // stopped by release(), so there is nothing further to report here.
  void new TrackProcessor({ track: sourceVideoTrack }).readable
    .pipeTo(mirrorFrames, { signal: stopMirroring.signal })
    .catch(() => undefined);

  let released = false;
  return {
    stream,
    release() {
      if (released) return;
      released = true;
      stopMirroring.abort();
      const tracks = new Set([...source.getTracks(), ...stream.getTracks()]);
      tracks.forEach((track) => track.stop());
    },
  };
}
