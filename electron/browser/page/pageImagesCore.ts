/**
 * 「采集页面图片」里不碰 Electron 的那一半:哪些图值得列(滤掉图标、追踪像素)、取回来的字节是不是图片。
 */

/** 页面上一张图(采集脚本交回来的)。宽高是图片**本身**的像素(naturalWidth/Height)。 */
export interface PageImage {
  url: string;
  width: number;
  height: number;
  alt: string;
}

/**
 * 小于这个的不列:图标、头像角标、按钮。也顺带滤掉追踪像素(1×1)。
 * 单边下限而不是面积:细长的分隔条面积可能不小,但不会有人想要它。
 */
export const MIN_IMAGE_EDGE = 120;
/** 一页最多列多少张。长页面能有几百张缩略图,全列出来既慢又没人一张张看。 */
export const MAX_PAGE_IMAGES = 120;

/** 追踪 / 统计像素常见的地址特征 —— 尺寸没报出来(还没加载完)时靠它兜一下。 */
const TRACKER = /(\/pixel\b|\/beacon\b|facebook\.com\/tr\b|doubleclick\.net|google-analytics\.com|\/collect\?)/i;

export function pickPageImages(raw: PageImage[]): PageImage[] {
  const seen = new Set<string>();
  const picked: PageImage[] = [];
  for (const image of raw) {
    if (!/^https?:\/\//i.test(image.url)) continue;
    if (image.width < MIN_IMAGE_EDGE || image.height < MIN_IMAGE_EDGE) continue;
    if (TRACKER.test(image.url)) continue;
    let key = image.url;
    try {
      const parsed = new URL(image.url);
      parsed.hash = "";
      key = parsed.href;
    } catch {
      continue;
    }
    if (seen.has(key)) continue;
    seen.add(key);
    picked.push({ ...image, url: key, alt: image.alt.trim().slice(0, 200) });
    if (picked.length >= MAX_PAGE_IMAGES) break;
  }
  return picked;
}

/** 图片字节真的是一张图吗(看文件头,不信响应头)。认得的格式交回 MIME,认不出返回 null。 */
export function sniffImage(bytes: Uint8Array): string | null {
  const at = (offset: number, ...values: number[]) => values.every((value, index) => bytes[offset + index] === value);
  if (bytes.length >= 8 && at(0, 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return "image/png";
  if (bytes.length >= 3 && at(0, 0xff, 0xd8, 0xff)) return "image/jpeg";
  if (bytes.length >= 6 && (at(0, 0x47, 0x49, 0x46, 0x38, 0x37, 0x61) || at(0, 0x47, 0x49, 0x46, 0x38, 0x39, 0x61))) return "image/gif";
  if (bytes.length >= 12 && at(0, 0x52, 0x49, 0x46, 0x46) && at(8, 0x57, 0x45, 0x42, 0x50)) return "image/webp";
  if (bytes.length >= 12 && at(4, 0x66, 0x74, 0x79, 0x70)) {
    const brand = String.fromCharCode(...bytes.slice(8, 12));
    if (brand === "avif" || brand === "avis") return "image/avif";
  }
  return null;
}

// 注进页面的脚本是**只读**的:不改 DOM、不触发事件、不发请求,交回可结构化克隆的普通对象。
// 以字符串形式交给 executeJavaScript,所以脚本里不能引用外部变量。

/**
 * 页面上的图:`<img>`(取它实际显示的那一张 currentSrc,带 srcset 的页面才拿得到大图)、
 * `<picture>` 也走 img;再加 og:image。尺寸取图片本身的像素,没加载完的报 0,由 pickPageImages 滤掉。
 */
export const IMAGE_SCAN_SCRIPT = `(() => {
  const abs = (value) => { try { return value ? new URL(value, document.baseURI).href : ""; } catch { return ""; } };
  const images = [...document.images].map((image) => ({
    url: abs(image.currentSrc || image.src),
    width: image.naturalWidth || 0,
    height: image.naturalHeight || 0,
    alt: image.alt || image.title || "",
  }));
  for (const tag of document.querySelectorAll('meta[property="og:image"], meta[property="og:image:url"], meta[name="twitter:image"]')) {
    const url = abs(tag.getAttribute("content"));
    if (!url) continue;
    const width = Number(document.querySelector('meta[property="og:image:width"]')?.getAttribute("content")) || 0;
    const height = Number(document.querySelector('meta[property="og:image:height"]')?.getAttribute("content")) || 0;
    // og:image 不一定声明尺寸;没声明时按「够大」放行,由下载后的真实字节说话。
    images.unshift({ url, width: width || 1200, height: height || 1200, alt: document.title || "" });
  }
  return images;
})()`;
