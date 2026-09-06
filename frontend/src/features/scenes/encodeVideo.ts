import { createFile } from "mp4box";

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
    framerate: 30,
    latencyMode: "realtime",
    avc: { format: "avc" },
  };
  if (!(await VideoEncoder.isConfigSupported(config)).supported) return null;
  const file = createFile(),
    count = Math.ceil(duration * 30),
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
        duration: chunk.duration ?? Math.round(1_000_000 / 30),
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
