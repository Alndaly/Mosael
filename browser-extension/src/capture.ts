import type { CaptureGeometry } from "./shared/protocol";

type BitmapSize = { width: number; height: number };
type CropRect = { x: number; y: number; width: number; height: number };


export function scaledCropRect(
  geometry: Pick<CaptureGeometry, "left" | "top" | "width" | "height" | "viewportWidth" | "viewportHeight">,
  bitmap: BitmapSize,
): CropRect {
  const scaleX = bitmap.width / geometry.viewportWidth;
  const scaleY = bitmap.height / geometry.viewportHeight;
  return {
    x: Math.round(geometry.left * scaleX),
    y: Math.round(geometry.top * scaleY),
    width: Math.max(1, Math.round(geometry.width * scaleX)),
    height: Math.max(1, Math.round(geometry.height * scaleY)),
  };
}

export async function cropScreenshot(dataUrl: string, geometry: CaptureGeometry): Promise<Blob> {
  const image = new Image();
  image.src = dataUrl;
  await image.decode();
  const crop = scaledCropRect(geometry, image);
  const canvas = document.createElement("canvas");
  canvas.width = crop.width;
  canvas.height = crop.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法创建截帧画布");
  context.drawImage(image, crop.x, crop.y, crop.width, crop.height, 0, 0, crop.width, crop.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("当前帧编码失败"))), "image/png");
  });
}

export function frameDataUrlToBlob(dataUrl: string): Blob {
  const match = /^data:([^;,]+);base64,(.+)$/s.exec(dataUrl);
  if (!match) throw new Error("当前视频帧格式无效");
  const decoded = atob(match[2]);
  const bytes = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) bytes[index] = decoded.charCodeAt(index);
  return new Blob([bytes], { type: match[1] });
}
