import { createFile } from "mp4box";

/**
 * 这一页的帧率。**导出和界面上的「逐帧」用的是同一个数** —— 不然按一下 → 走的那一"帧"
 * 在成片里不是一帧,而关键帧对齐到哪一帧本来就是这条快捷键唯一的用处。
 */
export const SHOT_FPS = 30;

/** Deterministic camera sampling and timestamps, independent of viewport frame rate. */
export async function encodeShotVideo(
  canvas: HTMLCanvasElement,
  duration: number,
  draw: (time: number) => void,
  signal: AbortSignal,
  progress: (fraction: number) => void,
): Promise<Blob | null> {
  if (typeof VideoEncoder === "undefined") return null;
  const config: VideoEncoderConfig = {
    codec:
      canvas.width * canvas.height > 1280 * 720 ? "avc1.420028" : "avc1.42001f",
    width: canvas.width,
    height: canvas.height,
    bitrate: 6_000_000,
    framerate: SHOT_FPS,
    latencyMode: "realtime",
    avc: { format: "avc" },
  };
  if (!(await VideoEncoder.isConfigSupported(config)).supported) return null;
  const file = createFile(),
    count = Math.ceil(duration * SHOT_FPS),
    end = Math.round(duration * 1_000_000);
  let track = 0,
    failure: Error | null = null;
  const encoder = new VideoEncoder({
    error: (e) => {
      failure = e;
    },
    output: (chunk, metadata) => {
      if (!track) {
        const description = metadata?.decoderConfig?.description;
        if (!description) {
          failure = new Error("编码器未返回视频格式信息");
          return;
        }
        const bytes = ArrayBuffer.isView(description)
          ? new Uint8Array(
              description.buffer,
              description.byteOffset,
              description.byteLength,
            )
          : new Uint8Array(description);
        track = file.addTrack({
          type: "avc1",
          width: canvas.width,
          height: canvas.height,
          timescale: 1_000_000,
          avcDecoderConfigRecord: bytes.slice().buffer,
          duration: end,
          media_duration: end,
        });
      }
      const data = new Uint8Array(chunk.byteLength);
      chunk.copyTo(data);
      file.addSample(track, data, {
        duration: chunk.duration ?? Math.round(1_000_000 / SHOT_FPS),
        dts: chunk.timestamp,
        cts: chunk.timestamp,
        is_sync: chunk.type === "key",
      });
    },
  });
  try {
    encoder.configure(config);
    for (let i = 0; i < count; i++) {
      if (signal.aborted) throw new Error("已取消导出");
      if (failure) throw failure;
      draw(count === 1 ? 0 : (i / (count - 1)) * duration);
      const timestamp = Math.round((i / count) * end),
        next = Math.round(((i + 1) / count) * end);
      const frame = new VideoFrame(canvas, {
        timestamp,
        duration: next - timestamp,
      });
      try {
        encoder.encode(frame, { keyFrame: i % 60 === 0 });
      } finally {
        frame.close();
      }
      if (i % 8 === 7) {
        await encoder.flush();
        progress((i + 1) / count);
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    }
    await encoder.flush();
    if (failure) throw failure;
    if (signal.aborted) throw new Error("已取消导出");
    progress(1);
    return new Blob([file.getBuffer().buffer], { type: "video/mp4" });
  } finally {
    if (encoder.state !== "closed") encoder.close();
  }
}
