/**
 * 蒙版的像素运算 —— 全是纯函数,画布那头只留「取像素 → 调这里 → 写回」的连线。
 *
 * 单独放一个文件是为了**能单测**:jsdom 里没有 canvas 2D(见 components/generation/MaskEditor)。
 *
 * ## 蒙版是什么,照抄契约,别顺手改
 *
 * **灰度图、白 = 要改的地方**(`backend/app/ai/providers/contracts/generation.py` 的 MASK:和要改的那张图
 * 一起给,白色是要改的地方)。它**不是一张带 alpha 的图**:ComfyUI 插件那条路注入的是
 * `LoadImageMask(image=…, channel="red")`,读的是**红通道**(`plugins/bundled/comfyui/tools/graph.py` 的
 * `_MASK_CHANNEL`)。所以这里每写一次像素都守着两条:
 *
 * - `r = g = b`(灰度;灰度图里红通道就是那个灰);
 * - alpha 一律填满 255 —— 一张带透明通道的图在那边读出来是整块不透明,**静默地什么都不重绘**。
 *
 * 尺寸约定:一份像素是 RGBA 四通道、长度 = `width * height * 4`(和 canvas 的 ImageData 一样)。
 */

/** 一份 RGBA 像素。就地改(和 ImageData.data 一样),不返回新数组。 */
export type MaskPixels = Uint8ClampedArray;

/** 从底图起手时「亮」按什么量。 */
export type MaskFromSource = "luminance" | "alpha";

const CHANNELS = 4;
/** Rec.601:底图不是灰的,按亮度加权才和眼睛看到的"亮"一致。 */
const LUMA_R = 0.299;
const LUMA_G = 0.587;
const LUMA_B = 0.114;

const clamp01 = (value: number) => (Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0);

/** 一份像素里第 i 个像素的灰度。 */
function gray(r: number, g: number, b: number): number {
  return LUMA_R * r + LUMA_G * g + LUMA_B * b;
}

/** 把一个二值结果写进去:非黑即白。 */
function write(data: MaskPixels, at: number, white: boolean): void {
  const value = white ? 255 : 0;
  data[at] = value;
  data[at + 1] = value;
  data[at + 2] = value;
  data[at + 3] = 255;
}

/**
 * 反选:黑变白、白变黑。
 *
 * 灰的(羽化过的边)按 `255 - v` 翻,边翻过来还是同样软的一条边 —— 不是重新二值化。
 */
export function invertMask(data: MaskPixels): void {
  for (let at = 0; at < data.length; at += CHANNELS) {
    const value = 255 - data[at];
    data[at] = value;
    data[at + 1] = value;
    data[at + 2] = value;
    data[at + 3] = 255;
  }
}

/**
 * 阈值二值化,**按亮度**:亮度 ≥ `value` 的变白,其余变黑。
 *
 * `value` 是 0..1(界面上那根滑块的原始值)。0 全白、1 只剩纯白 —— 两头都是合法输入,不特殊处理。
 * 底图直接喂进来也行(灰阶加权对灰像素就是它自己),「按亮度阈值初始化」走的正是这条路。
 */
export function thresholdMask(data: MaskPixels, value: number): void {
  const cut = clamp01(value) * 255;
  for (let at = 0; at < data.length; at += CHANNELS) {
    write(data, at, gray(data[at], data[at + 1], data[at + 2]) >= cut);
  }
}

/**
 * 阈值二值化,**按 alpha**:不透明的地方变白。
 *
 * 抠好的 PNG(主体实、背景透)走这一条就是"把它抠出来";底图没有透明通道时是整块白 ——
 * 那不是这里算错,是那张图本来就没有透的地方。
 */
export function alphaMask(data: MaskPixels, value: number): void {
  const cut = clamp01(value) * 255;
  for (let at = 0; at < data.length; at += CHANNELS) {
    write(data, at, data[at + 3] >= cut);
  }
}

/**
 * 羽化:把边晕开 `radius` 个像素。三遍盒式模糊 ≈ 高斯(中心极限),够用而且没有系数要调。
 *
 * 为什么不用 canvas 的 `ctx.filter = "blur(Npx)"`:那要先把像素搬进一张画布、再搬回来,而且
 * **在 jsdom 里根本跑不了**(没有 canvas 2D),这条运算就没法单测了;盒式模糊是纯算术,两边一样。
 *
 * 边缘按**夹取**处理(取样点越界就取边上那个像素),不然画布四边会自己变黑一圈 ——
 * 蒙版的边常常正是要改的地方。`radius < 1` 什么都不做(0.4px 的模糊看不出来,却是三遍全画布扫描)。
 */
export function featherMask(data: MaskPixels, width: number, height: number, radius: number): void {
  const reach = Math.round(radius);
  //: 尺寸对不上就不动它:按错的宽度重排像素,出来的是一张谁也认不出的图 —— 宁可什么都不做。
  if (reach < 1 || width < 1 || height < 1 || data.length !== width * height * CHANNELS) return;
  //: 单通道跑:羽化只对灰度有定义,四通道各跑一遍是四倍工作量、结果还一样。
  const channel = new Float32Array(width * height);
  for (let at = 0, i = 0; at < data.length; at += CHANNELS, i += 1) channel[i] = data[at];
  const scratch = new Float32Array(width * height);
  //: 一横一纵 = 一遍;三遍下来,权重分布已经贴着高斯了。
  for (let pass = 0; pass < 3; pass += 1) {
    blurAxis(channel, scratch, width, height, reach, true);
    blurAxis(scratch, channel, width, height, reach, false);
  }
  for (let at = 0, i = 0; at < data.length; at += CHANNELS, i += 1) {
    const value = Math.round(channel[i]);
    data[at] = value;
    data[at + 1] = value;
    data[at + 2] = value;
    data[at + 3] = 255;
  }
}

/** 一趟盒式模糊:沿一个轴滑动窗口求和,窗口是 [i-reach, i+reach]。 */
function blurAxis(
  from: Float32Array,
  to: Float32Array,
  width: number,
  height: number,
  reach: number,
  horizontal: boolean,
): void {
  const outer = horizontal ? height : width;
  const inner = horizontal ? width : height;
  const step = horizontal ? 1 : width;
  const span = reach * 2 + 1;
  for (let line = 0; line < outer; line += 1) {
    const base = horizontal ? line * width : line;
    let sum = 0;
    for (let offset = -reach; offset <= reach; offset += 1) {
      sum += from[base + clampIndex(offset, inner) * step];
    }
    for (let i = 0; i < inner; i += 1) {
      to[base + i * step] = sum / span;
      sum -= from[base + clampIndex(i - reach, inner) * step];
      sum += from[base + clampIndex(i + reach + 1, inner) * step];
    }
  }
}

const clampIndex = (index: number, length: number) => (index < 0 ? 0 : index >= length ? length - 1 : index);

/**
 * ## 看得见那张画布怎么合成:蒙版是**不透明**的,不能整张盖上去
 *
 * 蒙版按契约是「黑底 + 白笔迹、每个像素都不透明」,所以 `source-over` 把它整张画上去就是一块黑板:
 * 底图再怎么画也被盖掉,而且「画过」和「没画过」在屏幕上没有区别 —— 反选前后、清空前后一个样,
 * 看着就像「底图没了」「源图被弄成灰度了」。
 *
 * 屏幕上的层数不写在组件里,写在这里:**哪几层、谁在下、各自怎么叠**是一份数据,画布那头照着画
 * (组件里的 `drawMaskView`),于是这套合成在没有画布的环境里也能断言(见 maskPixels.test.ts)。
 *
 * | 层 | 像素从哪来 | 怎么叠 | 出来是什么 |
 * | --- | --- | --- | --- |
 * | 底图 | 原图 | `source-over`,alpha 1 | 这张图**原样** —— 要改的地方在它上面标出来 |
 * | 蒙版反相 | 255 − 蒙版 | `multiply`,alpha `MASK_TINT_DIM` | 没画的地方是白(乘了等于没乘),画过的地方压暗 |
 * | 蒙版着色 | 蒙版 × **调用方给的颜色** | `lighter` | 画过的地方加一层蒙版色 —— 底图再亮也认得出 |
 *
 * 那个颜色**不是这里的常量**:它跟主题走(浅 / 深两套),而 canvas 2D 读不到 CSS 变量 —— 所以由调用方
 * 按主题解析好、当参数传进 `maskViewLayers`(token 的名字在 `MASK_TINT_TOKEN`,解析与缓存见
 * `lib/themeColor`)。这个文件仍然是纯函数,node 里能单测。
 *
 * 两笔都要的原因:只压暗的话,底图本来就黑的那一块看不出来;只着色的话,底图本来就白的那一块
 * 也看不出来 —— 压暗给暗处兜底、着色给亮处兜底,两头都认得出来。
 * 而压暗用的是**反相** `multiply`(不是把蒙版直接乘上去):直接乘是「没画的地方」变黑 —— 那是把底图抹掉。
 *
 * 屏幕上的事到此为止:导出的那张自始至终是蒙版本身(组件里 `save()` 走 maskRef 那张离屏画布),
 * 和这条合成没有任何关系。
 */

/**
 * 要改的地方在屏幕上着的色是**哪一个主题 token**。
 *
 * 用已有的语义色 `--destructive`(「这一块要动」),浅色 `#bd383e` / 深色 `#f28d96`(值是 tokens.css
 * 的事,不抄到这里来)。此前这里是一个写死的红 `#e5484d`:浅深两套主题同一个红,深色主题上就糊了。
 *
 * 这里只留**名字**:值是调用方读计算样式解析出来的(2D 上下文不认 `var()`,理由见 lib/themeColor),
 * 再当参数交给 `maskViewLayers`。
 */
export const MASK_TINT_TOKEN = "--destructive";
/** 画过的地方压暗多少:1 = 压成纯黑,0 = 不压。压掉的底图正好让上面那层蒙版色认得出来。 */
export const MASK_TINT_DIM = 0.7;

/**
 * 看得见那张画布上的一层。`of` 说这一层的像素从哪来,`op` / `alpha` 说它怎么叠上去。
 *
 * `maskInverse` / `maskTint` 是蒙版的两张派生(反相、着色),由画布那头先铺在一张离屏画布上再叠:
 * 蒙版自己没有透明通道,不能直接当「只有画过的地方才画」的模板用。
 */
export interface MaskViewLayer {
  of: "underlay" | "mask" | "maskInverse" | "maskTint";
  op: GlobalCompositeOperation;
  alpha: number;
  /** 只有 `maskTint` 那一层有:画过的地方要着的颜色(调用方按主题解析好传进来,见 `MASK_TINT_TOKEN`)。 */
  tint?: string;
}

/**
 * 看得见那张画布要画的层,**先画的在下面**。
 *
 * 「显示底图」关掉、或者根本没有底图(读图失败、断网)时只剩蒙版本身:一张最朴素的黑白视图,
 * 和导出的那张一模一样 —— 所以那个开关是真的有用,不是空转。
 *
 * `tint` 是**要改的地方在屏幕上着的色**,由调用方给(它是主题色,见 `MASK_TINT_TOKEN` / `lib/themeColor`)。
 * 这个函数不碰 DOM:给什么颜色就用什么颜色,两套主题各调一次就是两个不同的层表。
 */
export function maskViewLayers(view: { hasUnderlay: boolean; showUnderlay: boolean; tint: string }): MaskViewLayer[] {
  if (!view.hasUnderlay || !view.showUnderlay) return [{ of: "mask", op: "source-over", alpha: 1 }];
  return [
    { of: "underlay", op: "source-over", alpha: 1 },
    { of: "maskInverse", op: "multiply", alpha: MASK_TINT_DIM },
    { of: "maskTint", op: "lighter", alpha: 1, tint: view.tint },
  ];
}

/**
 * 一份像素的**单通道**灰度 —— 撤销栈按它存。
 *
 * 一步一份四通道的像素在 2048² 上是 16MB,三十步就是五百兆;蒙版本身是灰的,一像素一个字节就够。
 * 还原走 writeGrayscale。
 */
export function grayscaleOf(data: MaskPixels): Uint8ClampedArray {
  const count = Math.floor(data.length / CHANNELS);
  const channel = new Uint8ClampedArray(count);
  for (let at = 0, i = 0; i < count; at += CHANNELS, i += 1) channel[i] = data[at];
  return channel;
}

/** 把单通道灰度写回一份 RGBA 像素(alpha 填满,见文件头)。长度不够的写多少算多少。 */
export function writeGrayscale(channel: Uint8ClampedArray, data: MaskPixels): void {
  const count = Math.min(channel.length, Math.floor(data.length / CHANNELS));
  for (let at = 0, i = 0; i < count; at += CHANNELS, i += 1) {
    const value = channel[i];
    data[at] = value;
    data[at + 1] = value;
    data[at + 2] = value;
    data[at + 3] = 255;
  }
}
