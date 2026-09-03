export interface CameraCapture {
  stream: MediaStream;
  release(): void;
}

const DEFAULT_WIDTH = 1280;
const DEFAULT_HEIGHT = 720;
const DEFAULT_FRAME_RATE = 30;

/**
 * Builds a camera-only recording stream whose video frames are flipped horizontally.
 * The source audio is passed through unchanged. The returned release function owns both
 * streams so callers cannot accidentally leave the camera active after recording stops.
 */
export function createMirroredCameraCapture(source: MediaStream, video: HTMLVideoElement): CameraCapture {
  const sourceVideoTrack = source.getVideoTracks()[0];
  if (!sourceVideoTrack) throw new Error("A mirrored camera capture needs a video track.");

  const settings = sourceVideoTrack.getSettings();
  const width = video.videoWidth || settings.width || DEFAULT_WIDTH;
  const height = video.videoHeight || settings.height || DEFAULT_HEIGHT;
  const frameRate = Math.min(60, Math.max(1, settings.frameRate || DEFAULT_FRAME_RATE));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;

  const context = canvas.getContext("2d");
  if (!context) throw new Error("The camera mirror canvas is unavailable.");
  if (typeof canvas.captureStream !== "function") {
    throw new Error("Camera mirroring is not supported by this browser.");
  }

  const stream = canvas.captureStream(frameRate);
  for (const track of source.getAudioTracks()) stream.addTrack(track);

  let frameRequest: number | null = null;
  let released = false;
  const renderFrame = () => {
    if (released) return;
    try {
      context.clearRect(0, 0, width, height);
      context.save();
      try {
        context.translate(width, 0);
        context.scale(-1, 1);
        context.drawImage(video, 0, 0, width, height);
      } finally {
        context.restore();
      }
    } catch {
      // A stream can briefly have track metadata before its first drawable frame. Keep waiting.
    } finally {
      if (!released) frameRequest = requestAnimationFrame(renderFrame);
    }
  };
  frameRequest = requestAnimationFrame(renderFrame);

  return {
    stream,
    release() {
      if (released) return;
      released = true;
      if (frameRequest !== null) cancelAnimationFrame(frameRequest);
      const tracks = new Set([...source.getTracks(), ...stream.getTracks()]);
      tracks.forEach((track) => track.stop());
    },
  };
}
