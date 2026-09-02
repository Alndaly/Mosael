export type VideoFrameSource = {
  videoWidth: number;
  videoHeight: number;
};

type FrameCanvas = {
  width: number;
  height: number;
  getContext(type: "2d"): { drawImage(source: VideoFrameSource, x: number, y: number, width: number, height: number): void } | null;
  toDataURL(type: "image/png"): string;
};

type CanvasFactory = () => FrameCanvas;

/** Capture decoded video pixels, not the tab surface or the player's HTML controls. */
export function captureVideoFrame(
  video: VideoFrameSource,
  createCanvas: CanvasFactory = () => document.createElement("canvas") as unknown as FrameCanvas,
): string {
  const width = Math.floor(video.videoWidth);
  const height = Math.floor(video.videoHeight);
  if (width <= 0 || height <= 0) throw new Error("视频画面尚未就绪，请播放后重试");
  const canvas = createCanvas();
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法创建截帧画布");
  context.drawImage(video, 0, 0, width, height);
  return canvas.toDataURL("image/png");
}
