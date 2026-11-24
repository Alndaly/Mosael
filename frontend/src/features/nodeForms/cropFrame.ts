/**
 * 裁切框(`image_crop`,ADR 0110)的纯算法:框是四个比例(占原图宽 / 高的几分之几),和后端 `assets/image_crop.CropBox`
 * 同一个形状。比例锁(1:1、16:9……)只在这里:一键摆好一个最大的居中框、拖的时候保持比例 —— **不进数据**,数据里只有那四个数。
 */

export interface CropBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const WHOLE: CropBox = { x: 0, y: 0, width: 1, height: 1 };

/** 框最小占原图的多少(两个方向各自)。再小就拖不住了;后端另有一边至少 16 像素的底线。 */
export const MIN_FRACTION = 0.04;

/** 拿着的是哪一处:框里(挪)、四边、四角。 */
export type CropHandle = "move" | "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

/** 一排比例。`ratio` 是**像素**的宽 / 高;`original` 按原图;`free` 不锁。 */
export const CROP_ASPECTS = [
  { id: "free", ratio: null },
  { id: "original", ratio: "original" },
  { id: "1:1", ratio: 1 },
  { id: "4:3", ratio: 4 / 3 },
  { id: "3:4", ratio: 3 / 4 },
  { id: "16:9", ratio: 16 / 9 },
  { id: "9:16", ratio: 9 / 16 },
] as const;

export type CropAspectId = (typeof CROP_ASPECTS)[number]["id"];

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high);

function number(value: unknown, fallback: number): number {
  const parsed = typeof value === "number" ? value : typeof value === "string" && value.trim() ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** 节点上那四格 → 框:没写、写错的按整张,超出的夹进图里(和后端 CropBox.clamped 一致)。 */
export function readCrop(config: Record<string, unknown>): CropBox {
  const x = clamp(number(config.crop_x, 0), 0, 1);
  const y = clamp(number(config.crop_y, 0), 0, 1);
  return {
    x,
    y,
    width: clamp(number(config.crop_width, 1), 0, 1 - x),
    height: clamp(number(config.crop_height, 1), 0, 1 - y),
  };
}

/** 框 → 写回那四格(四位小数:够准,存下来也好读)。 */
export function cropPatch(box: CropBox): Record<string, number> {
  const round = (value: number) => Math.round(value * 10000) / 10000;
  return { crop_x: round(box.x), crop_y: round(box.y), crop_width: round(box.width), crop_height: round(box.height) };
}

/** 某个比例在比例空间里的宽 / 高(框的 width / height 之比):像素比要按原图的宽高比折过来。 */
export function fractionRatio(aspect: CropAspectId, imageAspect: number): number | null {
  const found = CROP_ASPECTS.find((one) => one.id === aspect);
  if (!found || found.ratio === null) return null;
  const pixels = found.ratio === "original" ? imageAspect : found.ratio;
  return pixels / imageAspect;
}

/** 这个比例下最大的、居中的框。 */
export function fitAspect(ratio: number): CropBox {
  const width = ratio >= 1 ? 1 : ratio;
  const height = ratio >= 1 ? 1 / ratio : 1;
  return { x: (1 - width) / 2, y: (1 - height) / 2, width, height };
}

/** 框此刻是哪个比例(和某一档差不到 1%);对不上任何一档就是自由。 */
export function matchingAspect(box: CropBox, imageAspect: number): CropAspectId {
  if (!box.height) return "free";
  const ratio = box.width / box.height;
  const hit = CROP_ASPECTS.find((one) => {
    const target = fractionRatio(one.id, imageAspect);
    return target !== null && Math.abs(ratio / target - 1) < 0.01;
  });
  return hit?.id ?? "free";
}

/**
 * 拿着 `handle` 从 `start` 拖了 (`dx`, `dy`)(都是比例)。挪:整框跟着走、不出图;改大小:动的那几条边跟着走、对边不动,
 * 不小于 MIN_FRACTION、不出图。`ratio`(比例空间的宽 / 高)给了就锁住:角上按宽算高,边上按动的那一维算另一维、
 * 另一维以中线为准;放不下时两维一起收。
 */
export function dragCrop(start: CropBox, handle: CropHandle, dx: number, dy: number, ratio: number | null): CropBox {
  if (handle === "move") {
    return { ...start, x: clamp(start.x + dx, 0, 1 - start.width), y: clamp(start.y + dy, 0, 1 - start.height) };
  }
  let left = start.x;
  let top = start.y;
  let right = start.x + start.width;
  let bottom = start.y + start.height;
  if (handle.includes("w")) left = clamp(left + dx, 0, right - MIN_FRACTION);
  if (handle.includes("e")) right = clamp(right + dx, left + MIN_FRACTION, 1);
  if (handle.includes("n")) top = clamp(top + dy, 0, bottom - MIN_FRACTION);
  if (handle.includes("s")) bottom = clamp(bottom + dy, top + MIN_FRACTION, 1);
  if (ratio === null) return { x: left, y: top, width: right - left, height: bottom - top };
  return lockRatio(start, handle, { left, top, right, bottom }, ratio);
}

function lockRatio(
  start: CropBox,
  handle: CropHandle,
  edges: { left: number; top: number; right: number; bottom: number },
  ratio: number,
): CropBox {
  const vertical = handle === "n" || handle === "s";
  //: 想要多宽:角上和左右边看宽,上下边按高折成宽。
  let width = vertical ? (edges.bottom - edges.top) * ratio : edges.right - edges.left;
  //: 锚点:对角 / 对边不动;边上拖时另一维以原来的中线为准。
  const anchorX = handle.includes("w") ? start.x + start.width : handle.includes("e") ? start.x : start.x + start.width / 2;
  const anchorY = handle.includes("n") ? start.y + start.height : handle.includes("s") ? start.y : start.y + start.height / 2;
  const roomX = handle.includes("w") ? anchorX : handle.includes("e") ? 1 - anchorX : 2 * Math.min(anchorX, 1 - anchorX);
  const roomY = handle.includes("n") ? anchorY : handle.includes("s") ? 1 - anchorY : 2 * Math.min(anchorY, 1 - anchorY);
  width = Math.max(Math.min(width, roomX, roomY * ratio), MIN_FRACTION * Math.max(1, ratio));
  const height = width / ratio;
  const x = handle.includes("w") ? anchorX - width : handle.includes("e") ? anchorX : anchorX - width / 2;
  const y = handle.includes("n") ? anchorY - height : handle.includes("s") ? anchorY : anchorY - height / 2;
  return { x: clamp(x, 0, 1 - width), y: clamp(y, 0, 1 - height), width, height };
}

/** 切出来是多少像素(原图尺寸不知道时是 null)。 */
export function cropPixels(box: CropBox, size: { width: number; height: number } | null): { width: number; height: number } | null {
  if (!size) return null;
  return { width: Math.round(box.width * size.width), height: Math.round(box.height * size.height) };
}
