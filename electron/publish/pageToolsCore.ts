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
   * 超长页面压到能装进一张纹理为止。
   */
  scale: number;
  /** 页面比上限更长,只截了前面那一段。界面要如实说出来。 */
  truncated: boolean;
}

/**
 * 设备像素比去掉浮点误差(取两位小数;真实的屏幕是 1、1.25、1.5、2、3 这些)。缩放存成 0.30000001,换回原清晰度
 * 后页面读到的是 1.99999988 —— 拿它去乘坐标,37.75 × 它 = 75.49999 就近取整成 75 而不是 76,裁出来错开一行。
 */
export function screenRatio(devicePixelRatio: number): number {
  return Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? Math.round(devicePixelRatio * 100) / 100 : 1;
}

/**
 * 出图要缩小多少(≤ 1):平时按屏幕原生清晰度出图(1),装不进一张纹理就压到装得进为止。
 * `devicePixelRatio` 是截图那一刻页面的设备像素比(缩小显示的页面截图时临时按屏幕的渲染,见 pageCapture)。
 */
function clipScale(size: { width: number; height: number }, devicePixelRatio: number): number {
  const ratio = screenRatio(devicePixelRatio);
  // 两条边的设备像素都要装进纹理;保留三位小数并向下取,免得出图尺寸差一个像素地越界。
  const fit = Math.floor(Math.min(MAX_CAPTURE_EDGE / (size.height * ratio), MAX_CAPTURE_EDGE / (size.width * ratio)) * 1000) / 1000;
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
): FullPagePlan {
  const fullHeight = Math.max(Math.ceil(content.height), Math.ceil(viewport.height), 1);
  const width = Math.min(Math.max(Math.ceil(viewport.width), 1), MAX_CAPTURE_EDGE);
  const height = Math.min(fullHeight, MAX_FULL_PAGE_HEIGHT);
  return { width, height, scale: clipScale({ width, height }, devicePixelRatio), truncated: fullHeight > MAX_FULL_PAGE_HEIGHT };
}

/** 页面上的一块矩形(CSS 像素,从文档左上角起):某个元素。 */
export interface PageRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ClipPlan {
  /** 交给 CDP 的 clip:盖住元素的整数 CSS 区域。 */
  clip: PageRect & { scale: number };
  /** 从 CDP 截出来的图里裁哪一块(出图像素):正好是元素自己,不多不少。 */
  crop: PageRect;
  /** 元素比整页上限还高,只截了上面一段。 */
  truncated: boolean;
}

/**
 * 截某个元素:**左上、右下两条边各自换算成出图像素再取整,宽高用两条边相减。**
 *
 * 此前在 CSS 像素里取整 —— 起点向下取、终点向上取 —— 元素落在小数坐标上时(吸顶栏高 47.5px 这种,
 * 很常见)两头各多带进半个 CSS 像素,在 2 倍屏上就是一整行外圈的颜色(实测:元素顶上一道邻居的蓝边)。
 * 现在两条边在出图像素里各自就近取整,再相减得宽高。
 *
 * 交给 CDP 的区域另算:Chromium 会把 clip 的小数宽高截成整数 CSS 像素(实测 200.5 → 200,右边丢一列),
 * 所以 clip 取盖住元素的整数 CSS 区域,截完按 `crop` 在出图像素里裁 —— 两步都只在整数上做,不再有一像素
 * 的出入。没有大小(元素被藏起来了、还没排版)返回 null;比整页上限还高的只截上面一段。
 */
export function planClip(rect: PageRect, devicePixelRatio: number): ClipPlan | null {
  const cssHeight = Math.min(rect.height, MAX_FULL_PAGE_HEIGHT);
  const shrink = clipScale({ width: Math.max(rect.width, 1), height: Math.max(cssHeight, 1) }, devicePixelRatio);
  const scale = screenRatio(devicePixelRatio) * shrink;
  const x0 = Math.max(0, rect.x);
  const y0 = Math.max(0, rect.y);
  const left = Math.round(x0 * scale);
  const top = Math.round(y0 * scale);
  const right = Math.round((rect.x + rect.width) * scale);
  const bottom = Math.round((rect.y + cssHeight) * scale);
  if (right - left < 1 || bottom - top < 1) return null;
  const clipX = Math.floor(left / scale);
  const clipY = Math.floor(top / scale);
  return {
    clip: {
      x: clipX,
      y: clipY,
      width: Math.ceil(right / scale) - clipX,
      height: Math.ceil(bottom / scale) - clipY,
      scale: shrink,
    },
    crop: { x: left - Math.round(clipX * scale), y: top - Math.round(clipY * scale), width: right - left, height: bottom - top },
    truncated: rect.height > MAX_FULL_PAGE_HEIGHT,
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
