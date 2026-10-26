import type { CanvasFrame } from "./canvasSizing";

/**
 * The original file as a **paused** high-quality still source.
 *
 * Playback must stay on the proxy: its short GOP and known-good avc/mp4 are
 * what make WebCodecs seeking deterministic. Once the playhead is parked, the
 * browser's own `<video>` decoder can seek the untouched original, which keeps
 * text and fine detail that a 1080p proxy throws away. It is deliberately not
 * used during playback — multi-track sync belongs to the audio clock, not to
 * independently buffering media elements.
 *
 * Unsupported codecs simply never become ready; callers keep painting the
 * proxy frame until then, so this is an upgrade path, never a black frame.
 */
export class OriginalVideoSource {
  private readonly element: HTMLVideoElement;
  private failed = false;

  constructor(url: string, onFrame: () => void) {
    const video = document.createElement("video");
    video.preload = "auto";
    video.muted = true;
    video.playsInline = true;
    // No crossOrigin: Electron's file:// origin is rejected by strict CORS on
    // some shells, and preview readback is not required. A tainted canvas is
    // still valid for display; exports render on the backend.
    video.addEventListener("loadeddata", onFrame);
    video.addEventListener("seeked", onFrame);
    video.addEventListener("error", () => {
      this.failed = true;
    });
    video.src = url;
    video.load();
    this.element = video;
  }

  /** A decoded frame at `at`, or null while the seek is still in flight. */
  frameAt(at: number): { source: CanvasImageSource; w: number; h: number } | null {
    if (this.failed) return null;
    const video = this.element;
    const target = Math.max(0, at);
    const frame = originalFrame(video, target);
    if (frame) return { source: video, w: frame.width, h: frame.height };
    // A seek is asynchronous and can land on a nearby frame. Keep showing the
    // proxy until the element reports a time at the requested instant; one
    // video frame of tolerance prevents an endless re-seek loop at 29.97fps.
    if (!video.seeking) video.currentTime = target;
    return null;
  }

  dispose(): void {
    this.element.pause();
    this.element.removeAttribute("src");
    this.element.load();
  }
}

/** The paused source's intrinsic frame, for tests and non-DOM callers. */
export function originalFrame(
  video: Pick<HTMLVideoElement, "readyState" | "videoWidth" | "videoHeight" | "currentTime" | "seeking">,
  at: number,
): CanvasFrame | null {
  // HAVE_CURRENT_DATA = 2. Spelled numerically so this helper also runs under
  // Node-based unit tests, where HTMLMediaElement does not exist.
  if (video.readyState < 2) return null;
  if (!(video.videoWidth > 0) || !(video.videoHeight > 0)) return null;
  if (Math.abs(video.currentTime - Math.max(0, at)) > 1 / 60) return null;
  return { width: video.videoWidth, height: video.videoHeight };
}
