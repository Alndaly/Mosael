/**
 * 浏览器会话「页面工具」里**不碰 Electron 的那一半**:截图的几何(别的能力的纯判断各在自己的模块里)。
 *
 * 拆出来是为了能直接测:主进程那一半要一个活的 WebContents 才跑得起来,而「长图截到哪、框选的哪一块对应
 * 原图的哪几个像素」都是纯函数。
 */

/** 页面是谁:截图、图片、视频、笔记都要把它记进出处。 */
export interface PageInfo {
  url: string;
  title: string;
}

// ---------------------------------------------------------------------------------------------
// 截图几何
// ---------------------------------------------------------------------------------------------

/**
 * 整页长图最多截多高(CSS 像素)。
 *
 * 整页截图是 Chromium 把整页一次画进一张位图(CDP `captureBeyondViewport`),而 GPU 的单张纹理
 * 有上限(常见 16384 设备像素)。超过时 Chromium 要么截出一片空白、要么直接失败 —— 两种都比
 * 「截到这里为止并说明」糟。信息流这种无限下拉的页面也靠这条收口。
 */
export const MAX_FULL_PAGE_HEIGHT = 15_000;
/** 单边设备像素上限:纹理上限,也是缩放比例的天花板。 */
export const MAX_CAPTURE_EDGE = 16_384;

export interface FullPagePlan {
  /** 截取范围(CSS 像素,从页面左上角起)。 */
  width: number;
  height: number;
  /**
   * CDP clip.scale。**它乘在设备像素比上面**:出图像素 = CSS 像素 × scale × devicePixelRatio
   * (真 Electron 里实测:1440 宽的页面在 2 倍屏上传 scale=2 出来 5760 宽)。所以平时是 1 —— 按屏幕原生清晰度出图;
   * 超长页面压到能装进一张纹理为止。页面缩放过时交给 CDP 之前还要换算一次(见 cdpClip)。
   */
  scale: number;
  /** 页面比上限更长,只截了前面那一段。界面要如实说出来。 */
  truncated: boolean;
}

/**
 * 出图要缩小多少(≤ 1):平时按屏幕原生清晰度出图(1),装不进一张纹理就压到装得进为止。
 *
 * `devicePixelRatio` 是页面里读到的 `window.devicePixelRatio` —— 页面缩放过的话它已经乘进了缩放;
 * `zoom` 是那个缩放(悬浮面板把网页缩到三成上下)。出图像素按屏幕的设备像素比(devicePixelRatio / zoom)算。
 */
function clipScale(size: { width: number; height: number }, devicePixelRatio: number, zoom: number): number {
  const ratio = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
  const screen = ratio / (Number.isFinite(zoom) && zoom > 0 ? zoom : 1);
  // 两条边的设备像素都要装进纹理;保留三位小数并向下取,免得出图尺寸差一个像素地越界。
  const fit = Math.floor(Math.min(MAX_CAPTURE_EDGE / (size.height * screen), MAX_CAPTURE_EDGE / (size.width * screen)) * 1000) / 1000;
  return Math.min(1, fit);
}

/**
 * 整页长图截哪一块、按多大比例出图。
 *
 * `content` 是页面内容尺寸(CDP `Page.getLayoutMetrics` 的 cssContentSize),`viewport` 兜底 ——
 * 有些页面把滚动放在内层容器里,文档本身只有一屏高,那时整页就是可见区域那么大。
 */
export function planFullPage(
  content: { width: number; height: number },
  viewport: { width: number; height: number },
  devicePixelRatio: number,
  zoom = 1,
): FullPagePlan {
  const fullHeight = Math.max(Math.ceil(content.height), Math.ceil(viewport.height), 1);
  const width = Math.min(Math.max(Math.ceil(viewport.width), 1), MAX_CAPTURE_EDGE);
  const height = Math.min(fullHeight, MAX_FULL_PAGE_HEIGHT);
  return { width, height, scale: clipScale({ width, height }, devicePixelRatio, zoom), truncated: fullHeight > MAX_FULL_PAGE_HEIGHT };
}

/** 页面上的一块矩形(CSS 像素,从文档左上角起):可见区域、某个元素。 */
export interface PageRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * CSS 矩形 + 缩小比例 → CDP `Page.captureScreenshot` 的 clip。
 *
 * **页面缩放过时,CDP 的 clip 量的是缩放之后的像素**,scale 乘的是屏幕的设备像素比:真 Electron 里实测,
 * 悬浮面板里(缩放 0.3)直接按 CSS 坐标截,1280 宽的可见区域截出来网页只占左上角三成、其余一片白,
 * 某个元素截出来整张是白的(截到了页面更下面的空处)。所以坐标乘上缩放、scale 再除回去 —— 出图像素
 * = CSS 像素 × 缩小比例 × 屏幕的设备像素比,和没缩放的页面一样清楚。缩放是 1 时就是原样。
 */
export function cdpClip(rect: PageRect, shrink: number, zoom: number): PageRect & { scale: number } {
  const z = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
  return { x: rect.x * z, y: rect.y * z, width: rect.width * z, height: rect.height * z, scale: shrink / z };
}

export interface ClipPlan {
  /** 交给 CDP 的 clip(已按页面缩放换算,见 cdpClip)。 */
  clip: PageRect & { scale: number };
  /** 元素比整页上限还高,只截了上面一段。 */
  truncated: boolean;
}

/**
 * 截页面上的一块(可见区域、某个元素):取整到像素、高度不超过整页上限、比例同整页长图。
 * 没有大小(元素被藏起来了、还没排版)返回 null。
 */
export function planClip(rect: PageRect, devicePixelRatio: number, zoom = 1): ClipPlan | null {
  const x = Math.max(0, Math.floor(rect.x));
  const y = Math.max(0, Math.floor(rect.y));
  const width = Math.min(Math.ceil(rect.x + rect.width) - x, MAX_CAPTURE_EDGE);
  const fullHeight = Math.ceil(rect.y + rect.height) - y;
  const height = Math.min(fullHeight, MAX_FULL_PAGE_HEIGHT);
  if (!(width >= 1 && height >= 1)) return null;
  return {
    clip: cdpClip({ x, y, width, height }, clipScale({ width, height }, devicePixelRatio, zoom), zoom),
    truncated: fullHeight > MAX_FULL_PAGE_HEIGHT,
  };
}

/** 框选:用户在冻结画面上拖出来的矩形,按画面的**比例**给(0–1),与显示尺寸无关。 */
export interface SelectionFraction {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 太小的框不算(手一抖的单击)。设备像素。 */
export const MIN_REGION_EDGE = 4;

/**
 * 框选比例 → 原图上的像素矩形。夹进图里;框得太小返回 null(当作没框)。
 *
 * 冻结画面在界面上可能被缩放显示(窗口比截图小、高分屏截图是两倍像素),所以界面只交比例,
 * 换算成像素只在这一处、按原图尺寸做 —— 不会出现「框的是这一块、截出来偏了几个像素」。
 */
export function regionCropRect(
  selection: SelectionFraction,
  image: { width: number; height: number },
): { x: number; y: number; width: number; height: number } | null {
  const clamp = (value: number) => Math.min(1, Math.max(0, value));
  const left = clamp(Math.min(selection.x, selection.x + selection.width));
  const top = clamp(Math.min(selection.y, selection.y + selection.height));
  const right = clamp(Math.max(selection.x, selection.x + selection.width));
  const bottom = clamp(Math.max(selection.y, selection.y + selection.height));
  const x = Math.round(left * image.width);
  const y = Math.round(top * image.height);
  const width = Math.round(right * image.width) - x;
  const height = Math.round(bottom * image.height) - y;
  if (width < MIN_REGION_EDGE || height < MIN_REGION_EDGE) return null;
  return { x, y, width, height };
}
