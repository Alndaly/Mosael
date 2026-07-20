import { createFile, DataStream, MP4BoxBuffer, type ISOFile, type MultiBufferStream, type Movie, type Sample } from "mp4box";

/**
 * Decodes one proxy .mp4 (720p, short-GOP, B-frame-free — see media/proxy.py) with
 * WebCodecs and serves the frame at any presentation time. Because the proxy has no
 * B-frames, decode order == presentation order (cts == dts), so seeking is just
 * "flush, jump to the nearest keyframe ≤ target, decode forward".
 *
 * Frames are decoded on demand around the requested time and closed as the playhead
 * passes them, so memory stays bounded regardless of clip length.
 */

const MICRO = 1_000_000;
// How many samples past the requested one to keep the decoder fed during playback.
const LOOKAHEAD = 12;
// Cap on buffered (decoded, open) frames — back-pressure so we never balloon memory.
const MAX_FRAMES = 24;
// Drop frames this far behind the playhead (seconds).
const EVICT_BEHIND = 0.4;

interface Decoded {
  t: number; // presentation time, seconds
  frame: VideoFrame;
}

export class ProxyVideoSource {
  private file: ISOFile;
  private decoder: VideoDecoder | null = null;
  private samples: Sample[] = []; // decode order == presentation order (no B-frames)
  private frames: Decoded[] = []; // buffered decoded frames, ascending t
  private trackId = -1;
  private timescale = 1;
  private codec = "";
  private codedWidth = 0;
  private codedHeight = 0;
  private description?: Uint8Array;
  private decodeCursor = 0; // next sample index to feed the decoder
  private configured = false;
  private closed = false;
  private failed = false;
  private byteLength = 0;

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
        for (const s of samples) {
          this.samples.push(s);
          this.byteLength += s.data?.byteLength ?? 0;
        }
      };
    });
    void this.load(url);
  }

  get width(): number {
    return this.codedWidth;
  }
  get height(): number {
    return this.codedHeight;
  }
  get ok(): boolean {
    return !this.failed;
  }

  /** Bytes of encoded samples still held. Used to bound the idle-source pool. */
  get retainedBytes(): number {
    return this.byteLength;
  }

  private async load(url: string): Promise<void> {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`proxy fetch ${res.status}`);
      const buf = MP4BoxBuffer.fromArrayBuffer(await res.arrayBuffer(), 0);
      this.file.appendBuffer(buf, true);
      this.file.flush();
    } catch {
      this.failed = true;
      // `ready` may already be settled by onError; this covers fetch/parse failures. The flag is
      // what callers actually poll, so a rejected `ready` nobody awaited cannot go unnoticed.
    }
  }

  private onReady(info: Movie): void {
    const track = info.videoTracks[0];
    if (!track) throw new Error("proxy has no video track");
    this.trackId = track.id;
    this.timescale = track.timescale;
    this.codec = track.codec;
    this.codedWidth = track.track_width;
    this.codedHeight = track.track_height;
    this.description = this.readDescription();
    // Extract every sample of the video track (data included) via onSamples.
    this.file.setExtractionOptions(this.trackId, undefined, { nbSamples: Number.POSITIVE_INFINITY });
    this.file.start();
    this.file.flush();
  }

  /** avcC/hvcC box bytes (without the 8-byte box header) for VideoDecoder.configure. */
  private readDescription(): Uint8Array | undefined {
    for (const type of ["avcC", "hvcC", "vpcC", "av1C"] as const) {
      const box = this.file.getBox(type);
      if (!box) continue;
      const stream = new DataStream(undefined, 0); // defaults to big-endian
      // Runtime: box.write drives a DataStream (the canonical mp4box+WebCodecs path);
      // its typings ask for the MultiBufferStream subclass, so bridge with a cast.
      box.write(stream as unknown as MultiBufferStream);
      return new Uint8Array(stream.buffer.slice(8));
    }
    return undefined;
  }

  private ensureDecoder(): VideoDecoder | null {
    if (this.configured) return this.decoder;
    if (typeof VideoDecoder === "undefined") {
      this.failed = true;
      return null;
    }
    const decoder = new VideoDecoder({
      output: (frame) => this.onFrame(frame),
      error: () => {
        // Losing the decoder mid-playback used to leave frameAt returning null forever, which
        // the compositor drew as nothing — a black frame with no explanation. Record it so the
        // caller can fall back to element playback instead.
        this.failed = true;
      },
    });
    try {
      decoder.configure({
        codec: this.codec,
        codedWidth: this.codedWidth,
        codedHeight: this.codedHeight,
        description: this.description,
        optimizeForLatency: true,
      });
    } catch {
      // An unsupported codec throws here rather than going through the error callback.
      this.failed = true;
      return null;
    }
    this.decoder = decoder;
    this.configured = true;
    return decoder;
  }

  private onFrame(frame: VideoFrame): void {
    if (this.closed) {
      frame.close();
      return;
    }
    const t = frame.timestamp / MICRO;
    // Insert keeping ascending order (nearly always an append, no B-frames).
    let i = this.frames.length;
    while (i > 0 && this.frames[i - 1].t > t) i--;
    this.frames.splice(i, 0, { t, frame });
    // Back-pressure: if we somehow overran, close the oldest.
    while (this.frames.length > MAX_FRAMES) this.frames.shift()?.frame.close();
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

  private feed(i: number): void {
    const decoder = this.decoder;
    if (!decoder) return;
    const s = this.samples[i];
    if (!s.data) return;
    decoder.decode(
      new EncodedVideoChunk({
        type: s.is_sync ? "key" : "delta",
        timestamp: Math.round((s.cts / this.timescale) * MICRO),
        duration: Math.round((s.duration / this.timescale) * MICRO),
        data: s.data,
      }),
    );
  }

  /**
   * The decoded frame to display at presentation time `sec`, or null if nothing is
   * decoded yet (the caller repaints on rAF, so a late frame shows on the next tick).
   * Drives on-demand decoding: seeks to the nearest keyframe on a jump, then pumps
   * a few samples ahead of the playhead.
   */
  frameAt(sec: number): VideoFrame | null {
    if (this.failed || this.samples.length === 0) return null;
    const decoder = this.ensureDecoder();
    if (!decoder) return null;

    const target = this.indexAt(sec);
    const haveTarget = this.frames.some((f) => f.t <= sec + 1e-3 && f.t >= this.sampleTime(target) - 1e-3);
    // Reset to a keyframe when we've jumped (backwards, or forward past the buffer).
    if (!haveTarget && (this.decodeCursor > target || this.decodeCursor < this.nearestKeyframe(target))) {
      const key = this.nearestKeyframe(target);
      try {
        decoder.flush().catch(() => undefined);
      } catch {
        /* flush on a fresh decoder can reject; ignore */
      }
      for (const f of this.frames) f.frame.close();
      this.frames = [];
      this.decodeCursor = key;
    }
    // Pump forward: keep the decoder fed a little past the target.
    const limit = Math.min(this.samples.length - 1, target + LOOKAHEAD);
    while (this.decodeCursor <= limit && decoder.decodeQueueSize < LOOKAHEAD) {
      this.feed(this.decodeCursor);
      this.decodeCursor++;
    }
    // The frame to show = the NEWEST frame at or before the playhead. frames is ascending
    // in t, so that's the last one with t ≤ sec (found in one pass). Then evict frames we've
    // moved well past — everything before the chosen frame that is > EVICT_BEHIND behind it.
    let bestIdx = -1;
    for (let i = 0; i < this.frames.length; i++) {
      if (this.frames[i].t <= sec + 1e-3) bestIdx = i;
      else break; // ascending — no later frame can qualify
    }
    if (bestIdx >= 0) {
      const bestT = this.frames[bestIdx].t;
      const keep: Decoded[] = [];
      for (let i = 0; i < this.frames.length; i++) {
        if (i < bestIdx && this.frames[i].t < bestT - EVICT_BEHIND) {
          this.frames[i].frame.close();
        } else {
          keep.push(this.frames[i]);
        }
      }
      this.frames = keep;
      return this.frames.find((f) => f.t === bestT)?.frame ?? null;
    }
    // Nothing ≤ sec yet (just seeked, first frame still decoding) — show the earliest
    // available so the canvas isn't blank; don't evict.
    return this.frames[0]?.frame ?? null;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    for (const f of this.frames) f.frame.close();
    this.frames = [];
    if (this.decoder && this.decoder.state !== "closed") {
      try {
        this.decoder.close();
      } catch {
        /* already closing */
      }
    }
    this.decoder = null;
    this.samples = [];
  }
}
