/**
 * 画蒙版那台**相机**:文档(蒙版的像素网格)怎么落到屏幕上(ADR 0057 决定 3「文档与视口分开」)。
 *
 * 相机只有三个数:`scale`(一个文档像素占几个 CSS 像素)和 `x` / `y`(文档左上角落在画布元素的哪一点,CSS 像素)。
 * 屏幕点 = 文档点 × scale + (x, y)。适应窗口、100%、放大缩小、滚轮、捏合、空格拖动、中键拖动**只改这三个数**,
 * 不碰蒙版的一个像素 —— 所以这里是纯函数,和画布、React 都没有关系,能单测。
 */

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface Rect extends Point, Size {}

export interface Camera {
  scale: number;
  x: number;
  y: number;
}

/** 放到最大:一个文档像素 32 个屏幕像素 —— 修单个像素的边已经足够。 */
export const MAX_SCALE = 32;
/** 至少保留在视口里的那一截(CSS 像素):平移再远,图也不会整张跑丢。 */
const KEEP_VISIBLE = 48;
/** 放大 / 缩小键一下走多少。 */
export const ZOOM_STEP = 1.25;

/** 适应窗口:整张图按原始比例含进盒子(contain),居中。 */
export function fitCamera(doc: Size, box: Size): Camera {
  const scale = Math.min(box.width / doc.width, box.height / doc.height);
  return center(doc, box, scale);
}

/** 指定缩放、图居中(「100%」那一下)。 */
export function center(doc: Size, box: Size, scale: number): Camera {
  return { scale, x: (box.width - doc.width * scale) / 2, y: (box.height - doc.height * scale) / 2 };
}

/** 最小缩放:适应窗口那一档的四分之一(再小就只剩一个点),但不会大过 1。 */
export function minScale(doc: Size, box: Size): number {
  return Math.min(1, fitCamera(doc, box).scale / 4);
}

/**
 * 以屏幕上某一点为锚缩放:锚点下面那个文档像素缩放前后不动(指针在哪就朝哪放大)。
 * 缩放夹在 [minScale, MAX_SCALE] 之间;夹完之后平移照常收边。
 */
export function zoomAround(camera: Camera, factor: number, anchor: Point, doc: Size, box: Size): Camera {
  const scale = Math.min(MAX_SCALE, Math.max(minScale(doc, box), camera.scale * factor));
  const ratio = scale / camera.scale;
  return clampPan(
    { scale, x: anchor.x - (anchor.x - camera.x) * ratio, y: anchor.y - (anchor.y - camera.y) * ratio },
    doc,
    box,
  );
}

/** 平移(屏幕像素),收边。 */
export function panBy(camera: Camera, dx: number, dy: number, doc: Size, box: Size): Camera {
  return clampPan({ ...camera, x: camera.x + dx, y: camera.y + dy }, doc, box);
}

/** 收边:图至少有 `KEEP_VISIBLE` 那一截留在盒子里(图比那一截还小时按图自己的尺寸)。 */
export function clampPan(camera: Camera, doc: Size, box: Size): Camera {
  const width = doc.width * camera.scale;
  const height = doc.height * camera.scale;
  const keepX = Math.min(KEEP_VISIBLE, width);
  const keepY = Math.min(KEEP_VISIBLE, height);
  return {
    scale: camera.scale,
    x: Math.min(box.width - keepX, Math.max(keepX - width, camera.x)),
    y: Math.min(box.height - keepY, Math.max(keepY - height, camera.y)),
  };
}

/** 屏幕点(相对画布元素左上角,CSS 像素)→ 文档点。落在图外也照算(笔画到边外由画布自己裁掉)。 */
export function toDoc(camera: Camera, screen: Point): Point {
  return { x: (screen.x - camera.x) / camera.scale, y: (screen.y - camera.y) / camera.scale };
}

/**
 * 整张文档落在**位图**上的那块矩形(位图像素)。`pixelRatio` = 位图宽 / CSS 宽(含 devicePixelRatio 与封顶)。
 * 放大之后它会远远超出位图 —— 真正画哪一块由 `visiblePart` 再裁。
 */
export function placement(camera: Camera, doc: Size, pixelRatio: number): Rect {
  return {
    x: camera.x * pixelRatio,
    y: camera.y * pixelRatio,
    width: doc.width * camera.scale * pixelRatio,
    height: doc.height * camera.scale * pixelRatio,
  };
}

/**
 * 文档那块矩形里**落在位图之内**的部分:位图上的目标矩形,和它在文档上对应的那一段(按 0..1 的比例给,
 * 底图与蒙版尺寸不一定相同,各自乘自己的宽高)。整块在外面时给 null。
 *
 * 只画看得见的那一块:放大到 16 倍时整张图是几万像素宽,派生层那张离屏画布按它分配就是几个 GB。
 */
export function visiblePart(place: Rect, bitmap: Size): { target: Rect; fraction: Rect } | null {
  const left = Math.max(0, place.x);
  const top = Math.max(0, place.y);
  const right = Math.min(bitmap.width, place.x + place.width);
  const bottom = Math.min(bitmap.height, place.y + place.height);
  if (right <= left || bottom <= top || place.width <= 0 || place.height <= 0) return null;
  return {
    target: { x: left, y: top, width: right - left, height: bottom - top },
    fraction: {
      x: (left - place.x) / place.width,
      y: (top - place.y) / place.height,
      width: (right - left) / place.width,
      height: (bottom - top) / place.height,
    },
  };
}

/**
 * 一次滚轮事件该怎么动相机 —— 跟着全局的画布操控方式走(ADR 0057 决定 3,和画板、工作流同一套语义):
 *
 * - 触控板:双指滑动 = 平移;捏合(浏览器给的是带 ctrlKey 的滚轮)或 ⌘ / Ctrl + 滚动 = 缩放;
 * - 鼠标:滚轮 = 缩放(按住 Shift 横向平移)。
 *
 * `deltaMode` 换成像素:行(1)按 16、页(2)按盒子高。
 */
export type WheelIntent = { kind: "zoom"; factor: number } | { kind: "pan"; dx: number; dy: number } | null;

export function wheelIntent(
  event: Pick<WheelEvent, "deltaX" | "deltaY" | "deltaMode" | "ctrlKey" | "metaKey" | "shiftKey">,
  mode: "trackpad" | "mouse",
  boxHeight: number,
): WheelIntent {
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? boxHeight : 1;
  const dx = event.deltaX * unit;
  const dy = event.deltaY * unit;
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return null;
  if (event.ctrlKey || event.metaKey || (mode === "mouse" && !event.shiftKey)) {
    return { kind: "zoom", factor: zoomFactor(dy) };
  }
  if (mode === "mouse") return { kind: "pan", dx: -(dy || dx), dy: 0 };
  return { kind: "pan", dx: -dx, dy: -dy };
}

/** 滚轮的 deltaY → 缩放倍数。和 3D 场景同一条曲线:单次封顶 100,往下滚是缩小。 */
export function zoomFactor(deltaY: number): number {
  const step = Math.min(Math.abs(deltaY), 100) * 0.01;
  return deltaY < 0 ? Math.exp(step) : Math.exp(-step);
}
