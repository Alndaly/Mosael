import { createFile, DataStream, MP4BoxBuffer, type ISOFile, type MultiBufferStream, type Movie, type Sample } from "mp4box";

/**
 * Deterministic, awaitable decode of one full-resolution export proxy (see media/proxy.py,
 * export-proxy.mp4 — short GOP, no B-frames), for the OFFLINE export renderer. Where the live
 * {@link ProxyVideoSource} serves "best frame available right now" on an rAF, this serves "the
 * exact frame at time t", awaiting the decode — required so an export frame is reproducible and
 * pixel-matches the preview.
 *
 * Strategy: decode one GOP at a time and cache it. `frameAt(sec)` finds the keyframe ≤ target,
 * decodes that whole GOP to completion (a single `flush()` — no partial-output races), caches its
 * frames, and returns the newest with t ≤ sec. Rendering marches monotonically forward, so within a
 * GOP this is one decode amortised across ~30 frames; a jump just re-decodes the target GOP. Only
 * one GOP is ever held, so memory is bounded regardless of clip length.
 *
 * (mp4box parsing mirrors ProxyVideoSource — the proxies are the same container/codec family. Kept
 * separate so the live streaming path and the offline await path can evolve independently.)
 */

const MICRO = 1_000_000;

interface Decoded {
  t: number; // presentation time, seconds
  frame: VideoFrame;
}

export class OfflineVideoSource {
  private file: ISOFile;
  private samples: Sample[] = []; // decode order == presentation order (no B-frames)
  private trackId = -1;
  private timescale = 1;
  private codec = "";
  private codedWidth = 0;
  private codedHeight = 0;
  private description?: Uint8Array;
  private failed = false;
  private closed = false;
  private gopStart = -1; // sample index of the cached GOP's keyframe, or -1
  private gopFrames: Decoded[] = []; // decoded frames of the cached GOP, ascending t

  readonly ready: Promise<void>;

  constructor(url: string) {
    this.file = createFile();
    this.ready = new Promise<void>((resolve, reject) => {
      this.file.onError = (_module, message) => {
        this.failed = true;
        reject(new Error(message));
      };
      this.file.onReady = (info) => {
        try {
          this.onReady(info);
          resolve();
        } catch (err) {
          this.failed = true;
          reject(err as Error);
        }
      };
      this.file.onSamples = (_id, _user, samples) => {
        for (const s of samples) this.samples.push(s);
      };
    });
    void this.load(url);
  }

  get ok(): boolean {
    return !this.failed;
  }
  get width(): number {
    return this.codedWidth;
  }
  get height(): number {
    return this.codedHeight;
  }

  private async load(url: string): Promise<void> {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`export proxy fetch ${res.status}`);
      const buf = MP4BoxBuffer.fromArrayBuffer(await res.arrayBuffer(), 0);
      this.file.appendBuffer(buf, true);
      this.file.flush();
    } catch {
      this.failed = true;
    }
  }

  private onReady(info: Movie): void {
    const track = info.videoTracks[0];
    if (!track) throw new Error("export proxy has no video track");
    this.trackId = track.id;
    this.timescale = track.timescale;
    this.codec = track.codec;
    this.codedWidth = track.track_width;
    this.codedHeight = track.track_height;
    this.description = this.readDescription();
    this.file.setExtractionOptions(this.trackId, undefined, { nbSamples: Number.POSITIVE_INFINITY });
    this.file.start();
    this.file.flush();
  }

  private readDescription(): Uint8Array | undefined {
    for (const type of ["avcC", "hvcC", "vpcC", "av1C"] as const) {
      const box = this.file.getBox(type);
      if (!box) continue;
      const stream = new DataStream(undefined, 0); // big-endian
      box.write(stream as unknown as MultiBufferStream);
      return new Uint8Array(stream.buffer.slice(8));
    }
    return undefined;
  }

  private sampleTime(i: number): number {
    return this.samples[i].cts / this.timescale;
  }

  /** Largest sample index whose presentation time ≤ sec (binary search). */
  private indexAt(sec: number): number {
    let lo = 0;
    let hi = this.samples.length - 1;
    let ans = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.sampleTime(mid) <= sec) {
        ans = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return ans;
  }

  private nearestKeyframe(idx: number): number {
    for (let i = idx; i >= 0; i--) if (this.samples[i].is_sync) return i;
    return 0;
  }

  /** Decode the entire GOP that starts at sample index `key`, to completion, into `gopFrames`. */
  private async decodeGop(key: number): Promise<void> {
    for (const f of this.gopFrames) f.frame.close();
    this.gopFrames = [];
    this.gopStart = -1;

    const collected: Decoded[] = [];
    let decodeError = false;
    const decoder = new VideoDecoder({
      output: (frame) => collected.push({ t: frame.timestamp / MICRO, frame }),
      error: () => {
        decodeError = true;
      },
    });
    try {
      decoder.configure({
        codec: this.codec,
        codedWidth: this.codedWidth,
        codedHeight: this.codedHeight,
        description: this.description,
      });
      // Feed from the keyframe up to (not including) the next keyframe — the whole GOP.
      let i = key;
      do {
        const s = this.samples[i];
        if (s.data) {
          decoder.decode(
            new EncodedVideoChunk({
              type: s.is_sync ? "key" : "delta",
              timestamp: Math.round((s.cts / this.timescale) * MICRO),
              duration: Math.round((s.duration / this.timescale) * MICRO),
              data: s.data,
            }),
          );
        }
        i++;
      } while (i < this.samples.length && !this.samples[i].is_sync);
      await decoder.flush(); // all fed frames are now output — no partial-output race
    } catch {
      decodeError = true;
    } finally {
      if (decoder.state !== "closed") decoder.close();
    }
    if (decodeError) {
      for (const f of collected) f.frame.close();
      this.failed = true;
      return;
    }
    collected.sort((a, b) => a.t - b.t);
    this.gopFrames = collected;
    this.gopStart = key;
  }

  /** The exact decoded frame to display at presentation time `sec`, or null on failure. */
  async frameAt(sec: number): Promise<VideoFrame | null> {
    if (this.failed || this.samples.length === 0) return null;
    const key = this.nearestKeyframe(this.indexAt(sec));
    if (key !== this.gopStart) {
      await this.decodeGop(key);
      if (this.failed) return null;
    }
    let best: VideoFrame | null = null;
    for (const f of this.gopFrames) {
      if (f.t <= sec + 1e-3) best = f.frame;
      else break; // ascending t
    }
    // Before the first frame's timestamp (rounding at a clip's very start) — show the earliest.
    return best ?? this.gopFrames[0]?.frame ?? null;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    for (const f of this.gopFrames) f.frame.close();
    this.gopFrames = [];
    this.gopStart = -1;
    this.samples = [];
  }
}
