import * as React from "react";
import { Brush, Check, Circle, Contrast, Droplets, Eraser, Feather, Redo2, Square, SunMedium, Trash, Undo2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { assetPreviewUrl, importAsset, type Asset } from "@/api/domains/assets";
import { errorText } from "@/api/errorMessage";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { FailureCard } from "@/components/failure/FailureCard";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { Segmented } from "@/components/ui/segmented";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  MASK_TINT_TOKEN,
  PASTE_DRAFT,
  PASTE_PREVIOUS,
  PASTE_THRESHOLD,
  alphaMask,
  createMaskWriter,
  featherMask,
  invertMask,
  maskViewLayers,
  thresholdMask,
  type MaskContext,
  type MaskPixels,
  type MaskViewLayer,
} from "@/lib/maskPixels";
import { useThemeColor } from "@/lib/themeColor";

/**
 * 蒙版编辑器:在**浏览器 canvas** 上刷出「要改的那一块」,产出一张灰度 PNG(ADR 0056 决定 3 / 5 / 7 的第二步)。
 *
 * ## 产出的东西是一张黑白图,不是一张带 alpha 的图
 *
 * 契约在 `backend/app/ai/providers/contracts/generation.py` 的 MASK:**灰度图、白 = 要改的地方**。
 * ComfyUI 插件那条路注入的是 `LoadImageMask(image=…, channel="red")`,读的是**红通道**
 * (`plugins/bundled/comfyui/tools/graph.py` 的 `_MASK_CHANNEL`)。所以画布是**不透明的黑底 + 白笔迹**,
 * 导出的就是它:黑底那一层不是装饰 —— 带透明通道的 PNG 在那边读出来是整块不透明,**静默地什么都不重绘**。
 *
 * ## 三张画布,各干各的
 *
 * | 画布 | 在哪 | 装什么 |
 * | --- | --- | --- |
 * | 底图 | 只在看得见的这张上 | 要改的那张原图 —— **导出的蒙版里永远没有它** |
 * | 蒙版(离屏) | 不进 DOM,和底图一样大 | 黑白笔迹。笔画累积在它上面,**导出的也是它** |
 * | 可见的那张 | 对话框里 | 底图 + 蒙版,按容器等比缩放到看得见的大小(devicePixelRatio 感知) |
 *
 * 三张分开是为了让「导出」这件事没有任何条件:导出的那张画布上从来没有底图,也不需要重新合成一遍。
 *
 * ## 可见的那张不能把蒙版整张盖上去
 *
 * 蒙版是**不透明**的(见 lib/maskPixels 文件头),`source-over` 整张画上去就是一块黑板 —— 底图被
 * 盖掉、画过和没画过也分不出来(维护者看到的就是「清空 / 反选之后底图没了、图变成灰的」)。
 * 可见的那张照 `maskViewLayers` 给的那份层表画(`drawMaskView`):底图原样在下面,要改的地方
 * **压暗 + 着蒙版色**叠在上面。层表和理由都写在 lib/maskPixels 里,这边只管照着画。
 *
 * ## 蒙版色跟主题走
 *
 * 那个红**不是这里的常量**:2D 上下文读不到 CSS 变量(`fillStyle = "var(--destructive)"` 是不生效的),
 * 所以颜色按主题从 token 解析一次、缓存在 ref 里(`lib/themeColor` 的 `useThemeColor`),`paint()` 每一帧
 * 只读那个缓存 —— 每帧一次 `getComputedStyle` 是上一轮明确避开的代价。主题一切就重画一次那一趟,
 * 屏幕上那一块颜色立刻跟上,不用等用户下一次动手(和「底图读进来」是同一个坑,见下面那条 effect)。
 *
 * ## 读底图像素为什么要绕一圈 fetch
 *
 * `assetPreviewUrl` 是**后端的源**(127.0.0.1:8800),直接把它给 `<img>` 再画进画布会把画布**污染**
 * (tainted canvas)—— 之后 `getImageData` / `toBlob` 一律 SecurityError,而这两步恰恰是「按阈值初始化」
 * 和「导出」必须做的。所以走 fetch → blob → 对象 URL:对象 URL 继承本文档的源,画上去干净。
 * 读不到(断网、不是图片、环境里没有 canvas)就是**没有底图**,编辑器照样能画。
 *
 * ## 像素运算不在这里
 *
 * 反选 / 阈值 / 羽化 / 撤销栈那份单通道全在 `lib/maskPixels`(纯函数,能单测;jsdom 里没有 canvas 2D)。
 * 这里只留「取像素 → 调它 → 写回」。
 *
 * ## 「只动蒙版」不是靠自觉,是靠拿不到别的口子
 *
 * 这个文件**没有** `maskContext().fillRect(...)` 这种写法了:蒙版那张画布由 `lib/maskPixels` 的
 * `createMaskWriter()` 发,**交出来的只有那几个语义方法**(`read` / `write` / `clear` / `paste` /
 * `snapshot` / `restore` / `stroke` / `preview`)。每一次写先过"覆盖不满整张就拒绝",写完的下一微任务
 * 再逐像素验一遍不透明 —— 那三条把不变量踩坏的路(见 maskPixels 里那张表)全在那一个文件里堵住,
 * 这里想绕开得先改那边。**加新动作时不要在这里要原始 ctx**:笔迹类走 `stroke` / `preview`,
 * 整张类走 `write` / `clear` / `paste`,没有第三类。
 *
 * 「橡皮 = 写黑」也是这条不变量的一部分:蒙版按契约没有 alpha 可用(灰度、白 = 要改、全不透明),
 * 所以"擦掉"在数据上只能是写黑;屏幕上"擦完露出原图"由**底图那一层**负责,与蒙版无关
 * (见 maskPixels 的「橡皮为什么是写黑」)。
 */

/**
 * 这个模块**发出去的那几张蒙版画布**(每一个 `MaskWriter` 一张)。只给测试用:像素级的回归要能
 * 从"一堆画布里"认出哪张是蒙版 —— 生产代码一行都不读它。
 */
const MASK_CANVASES = new WeakSet<HTMLCanvasElement>();

/** 这张画布是不是「画蒙版」发出去的那张**蒙版**(不是可见那张、也不是派生层的临时画布)。 */
export function isMaskCanvas(element: HTMLCanvasElement): boolean {
  return MASK_CANVASES.has(element);
}

/** 没有底图、也没有底稿时的画布尺寸。 */
const DEFAULT_DOC = 1024;
/** 撤销栈最多几步(一次按下到松手算一步)。 */
const HISTORY_LIMIT = 30;
/**
 * 撤销栈的总字节上限。一步是**一个像素一个字节**(见 lib/maskPixels 的 grayscaleOf):步数封顶 30,
 * 字节也封顶 —— 4096² 的一步就是 16MB,三十步五百兆,标签页会先卡住。
 */
const HISTORY_BYTES = 96 * 1024 * 1024;
/**
 * 蒙版文档的尺寸上限(长边)。底图比这还大就按比例缩下来:8000² 的一张 RGBA 画布是 256MB,
 * 而局部重绘最终按潜空间尺寸用它,多出来那几千万像素换不来任何东西。
 */
const MAX_DOC_EDGE = 4096;
/**
 * **可见那张**画布的位图上限(长边)。它现在铺满整个盒子、还带 devicePixelRatio,不封顶的话
 * 4K 屏上一个 1180×820 的弹窗就是 2360×1640、约 15MB —— 一张两张还好,而浏览器的画布内存
 * 是**所有**画布共用的(这个对话框里还有底稿、临时画布、导出用的那张),超了之后新建画布会
 * 静默地画不出东西。2048 换到屏幕上早就看不出软(它是给人看着画的,不是导出的那一张)。
 */
const MAX_VIEW_EDGE = 2048;
const TAU = Math.PI * 2;
const BLACK = "#000000";
const WHITE = "#ffffff";
/** 软边渐变的外圈。画布是不透明的,所以"往回混"就够了,不需要 destination-out。 */
const FADE_WHITE = "rgba(255, 255, 255, 0)";
const FADE_BLACK = "rgba(0, 0, 0, 0)";
/** 存下来的素材文件名(素材名另给,见 maskAssetName)。 */
const MASK_FILE_NAME = "mask.png";

type Tool = "brush" | "eraser" | "rect" | "ellipse";
/** 初笔迹是从底图的什么量出来的 —— 阈值滑块改动时重算的就是这一种;null = 还没按过那两个按钮。 */
type FromSource = "luminance" | "alpha";

interface Size {
  width: number;
  height: number;
}
interface Point {
  x: number;
  y: number;
}
/** 一次拖动:按下在哪、上一次到哪、形状工具要用的「按下之前那份像素」。 */
interface Drag {
  tool: Tool;
  from: Point;
  last: Point;
  before: Uint8ClampedArray | null;
}
/** 读进来的底图(像素 + 那张图本身,后者画在看得见的那张画布上当参考)。 */
interface Loaded extends Size {
  data: MaskPixels;
  image: HTMLImageElement;
}

/** 一份底图 / 底稿:素材 id + 名字(名字进新素材的标题,见 ADR 0056 后果那一节)。 */
export interface MaskImage {
  assetId: string;
  name: string;
}

/**
 * 把一份素材的像素读进来。读不出来返回 null —— 没有底图,编辑器照样能用。
 *
 * 走 fetch 而不是直接给 `<img>`:见文件头「读底图像素为什么要绕一圈 fetch」。
 */
async function loadImage(url: string): Promise<Loaded | null> {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    const objectUrl = URL.createObjectURL(await response.blob());
    try {
      const image = await decode(objectUrl);
      const width = image.naturalWidth || image.width;
      const height = image.naturalHeight || image.height;
      if (!width || !height) return null;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(image, 0, 0);
      return { data: ctx.getImageData(0, 0, width, height).data, width, height, image };
    } finally {
      //: 图片已经解码进这张元素里了,URL 可以立刻收回。
      URL.revokeObjectURL(objectUrl);
    }
  } catch {
    return null;
  }
}

function decode(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("decode failed"));
    image.src = url;
  });
}

/** 按上限缩一下(长边);没超就原样。 */
function capsSize(size: Size): Size {
  const edge = Math.max(size.width, size.height);
  if (edge <= MAX_DOC_EDGE) return size;
  const scale = MAX_DOC_EDGE / edge;
  return { width: Math.max(1, Math.round(size.width * scale)), height: Math.max(1, Math.round(size.height * scale)) };
}

/** 一笔画上去:沿 from→to 按间距盖圆点。间距取半径的四成 —— 比半径密,笔迹才不显颗粒。 */
function paintLine(
  ctx: CanvasRenderingContext2D,
  from: Point,
  to: Point,
  radius: number,
  hardness: number,
  ink: string,
  fade: string,
): void {
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  const steps = Math.max(1, Math.ceil(distance / Math.max(1, radius * 0.4)));
  for (let step = 1; step <= steps; step += 1) {
    const at = { x: from.x + ((to.x - from.x) * step) / steps, y: from.y + ((to.y - from.y) * step) / steps };
    ctx.beginPath();
    ctx.arc(at.x, at.y, radius, 0, TAU);
    if (hardness >= 0.99 || radius <= 1) {
      ctx.fillStyle = ink;
      ctx.fill();
      continue;
    }
    //: 硬度 = 实心那一段占半径的比例:1 是硬边,0 是从圆心就开始淡出去。
    const gradient = ctx.createRadialGradient(at.x, at.y, radius * hardness, at.x, at.y, radius);
    gradient.addColorStop(0, ink);
    gradient.addColorStop(1, fade);
    ctx.fillStyle = gradient;
    ctx.fill();
  }
}

/** 矩形 / 椭圆:一次填一块白的(拖动时每帧重画,所以看到的就是松手后的样子)。 */
function paintShape(ctx: CanvasRenderingContext2D, tool: Tool, from: Point, to: Point): void {
  const left = Math.min(from.x, to.x);
  const top = Math.min(from.y, to.y);
  const width = Math.abs(to.x - from.x);
  const height = Math.abs(to.y - from.y);
  ctx.fillStyle = WHITE;
  if (tool === "rect") {
    ctx.fillRect(left, top, width, height);
    return;
  }
  ctx.beginPath();
  ctx.ellipse(left + width / 2, top + height / 2, width / 2, height / 2, 0, 0, TAU);
  ctx.fill();
}

/**
 * `drawMaskView` 真正用到的那几样 —— 可见那张、派生层那张的上下文都满足它。
 *
 * 写成窄接口而不是直接要 `CanvasRenderingContext2D`:`src/test/pixelCanvas` 那份**像素替身**
 * 只要实现这几样就能被断言,不必假装自己是一个完整的 2D 上下文。
 */
export interface MaskViewContext {
  globalAlpha: number;
  globalCompositeOperation: GlobalCompositeOperation;
  clearRect(x: number, y: number, width: number, height: number): void;
  drawImage(source: CanvasImageSource, dx: number, dy: number, dw: number, dh: number): void;
  createRadialGradient(x0: number, y0: number, r0: number, x1: number, y1: number, r1: number): CanvasGradient;
}

/**
 * 把看得见的那张画布按层表画出来(层表见 lib/maskPixels 的 maskViewLayers)。
 *
 * 「哪几层、谁在下、各自怎么叠」只有层表那一处 —— 这里只管照着画,不自己决定合成方式:
 * 屏幕上怎么画和导出的契约是两件事,分开写才改得动其中一件而不动另一件。
 *
 * `mask` / `underlay` 允许是 null(还没铺出蒙版、底图没读进来):缺哪层跳哪层。
 */
export function drawMaskView(
  ctx: MaskViewContext,
  {
    plan,
    mask,
    underlay,
    scratch,
    width,
    height,
  }: {
    plan: MaskViewLayer[];
    mask: CanvasImageSource | null;
    underlay: CanvasImageSource | null;
    /** 复用的一张离屏画布:蒙版那两层要先在它上面铺出来(见 maskLayer)。 */
    scratch: HTMLCanvasElement;
    width: number;
    height: number;
  },
): void {
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
  ctx.clearRect(0, 0, width, height);
  for (const layer of plan) {
    const source = layer.of === "underlay" ? underlay : mask;
    if (!source) continue;
    const canvas =
      layer.of === "maskInverse" || layer.of === "maskTint"
        ? maskLayer(scratch, layer.of, source, width, height, layer.tint ?? "")
        : source;
    if (!canvas) continue;
    ctx.globalAlpha = layer.alpha;
    ctx.globalCompositeOperation = layer.op;
    ctx.drawImage(canvas, 0, 0, width, height);
  }
  //: 收尾复位:这张 ctx 还要接着给下一帧用,状态漏出去就是下一帧的第一层叠错了。
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
}

/**
 * 蒙版那一层的底:反相(未画 = 白)或着色(画过 = 蒙版色)。
 *
 * 蒙版自己是不透明的灰度图,两张派生各靠一次贴合得到,都不需要逐像素循环:
 *
 * - 反相:白底上 `difference` 减一次蒙版 → 255 − 蒙版;
 * - 着色:蒙版色上 `multiply` 乘一次蒙版 → 没画的地方是黑(叠上去时 `lighter` 加零 = 什么都不加),
 *   画过的地方是蒙版色。
 *
 * `tint` 是层表带过来的那个颜色(调用方按主题解析好,见 MASK_TINT_TOKEN)。**空串就铺黑**:黑叠上去
 * 还是「什么都不加」,这一层等于空转 —— 屏幕上还有压暗那一笔兜着。不这么办的话,`fillStyle = ""`
 * 会被静默忽略,底色留在上一次那个**白**(反相那趟刚铺的),画过的地方就糊成一块白斑。
 */
function maskLayer(
  scratch: HTMLCanvasElement,
  kind: "maskInverse" | "maskTint",
  mask: CanvasImageSource,
  width: number,
  height: number,
  tint: string,
): HTMLCanvasElement | null {
  //: 尺寸跟着可见画布走(对话框换大小、dpr 变了);重设 width 会清空整张位图,本来就该重铺。
  if (scratch.width !== width || scratch.height !== height) {
    scratch.width = width;
    scratch.height = height;
  }
  const ctx = scratch.getContext("2d");
  if (!ctx) return null;
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = kind === "maskInverse" ? WHITE : tint || BLACK;
  ctx.fillRect(0, 0, width, height);
  ctx.globalCompositeOperation = kind === "maskInverse" ? "difference" : "multiply";
  ctx.drawImage(mask, 0, 0, width, height);
  ctx.globalCompositeOperation = "source-over";
  return scratch;
}

export function MaskEditor({
  open,
  onOpenChange,
  workspaceId,
  source = null,
  initial = null,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  /** 要改的那张图:画在画布底下当参考,**不进导出的蒙版**。没给就是一块黑画布。 */
  source?: MaskImage | null;
  /** 打开时已经有一张蒙版:它当底稿(ADR 0056 决定 5:要改就在它上面继续画)。 */
  initial?: MaskImage | null;
  /** 存好了:调用方把这份素材放进蒙版槽。 */
  onDone: (asset: Asset) => void;
}) {
  const t = useI18n();
  const queryClient = useQueryClient();
  /** 看得见的那张画布(底图 + 蒙版,只给人看)。它铺满自己的盒子,位图尺寸由 fit() 按盒子写。 */
  const viewRef = React.useRef<HTMLCanvasElement>(null);
  /**
   * 画布外面那个盒子。**量的对象是它**:画布的 CSS 尺寸是 `fit()` 按 contain 写下去的,
   * 量画布自己就成了自己咬自己(写一次尺寸 → ResizeObserver 又叫一次 → 尺寸再变)。
   */
  const frameRef = React.useRef<HTMLDivElement>(null);
  /** 正在画一笔。见 fit():拖动期间不重量(每一次量都要读版面,而拖动每秒几十次)。 */
  const drawingRef = React.useRef(false);
  /**
   * 蒙版本身 —— 离屏、不进 DOM、导出的就是它。**由 `lib/maskPixels` 的 createMaskWriter 发**:
   * 这里拿不到它的原始 2D 上下文,写它只能走那几个语义方法(见文件头「只动蒙版」那一节)。
   */
  const writerRef = React.useRef<ReturnType<typeof createMaskWriter> | null>(null);
  if (!writerRef.current) writerRef.current = createMaskWriter();
  React.useEffect(() => {
    //: 发一次记一次(`resize` 会换画布)—— 测试按这张登记表认出蒙版那张。
    const canvas = writer().canvas();
    if (canvas) MASK_CANVASES.add(canvas);
  });
  /**
   * 合成可见那张画布时复用的一张离屏画布(蒙版的反相 / 着色各要一整张,见 drawMaskView 的
   * maskLayer)。每帧新建一张等于每帧要一块和可见画布一样大的画布内存 —— 浏览器的画布内存是
   * 这个对话框里所有画布共用的,所以复用一张。
   */
  const scratchRef = React.useRef<HTMLCanvasElement | null>(null);
  /** 底图像素(按亮度 / 按 alpha 初始化读的就是它)和那张图(画在看得见的画布上)。 */
  const underlayRef = React.useRef<Loaded | null>(null);
  /** 底稿:打开时已经有的那张蒙版。 */
  const draftRef = React.useRef<HTMLImageElement | null>(null);
  const dragRef = React.useRef<Drag | null>(null);
  /** 撤销栈:每一步是**一整个蒙版的单通道灰度**(见 lib/maskPixels 的 grayscaleOf)。 */
  const historyRef = React.useRef<{ steps: Uint8ClampedArray[]; at: number }>({ steps: [], at: -1 });
  /** 上一步是什么(用来把滑块的连续改动并成一步)。 */
  const lastStepRef = React.useRef<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  /**
   * 要改的地方在屏幕上着的色。**按主题解析一次**(浅深两套值),`paint()` 只读这个缓存 ——
   * 画布不认 `var()`,而这一个字符串在每一帧里都用得上(理由与订阅见 lib/themeColor)。
   */
  const tint = useThemeColor(MASK_TINT_TOKEN);
  const tintRef = React.useRef(tint);

  const [tool, setTool] = React.useState<Tool>("brush");
  const [radius, setRadius] = React.useState(48);
  const [hardness, setHardness] = React.useState(0.9);
  const [feather, setFeather] = React.useState(8);
  const [threshold, setThreshold] = React.useState(0.5);
  const [fromSource, setFromSource] = React.useState<FromSource | null>(null);
  const [showUnderlay, setShowUnderlay] = React.useState(true);
  const [hasUnderlay, setHasUnderlay] = React.useState(false);
  const [canUndo, setCanUndo] = React.useState(false);
  const [canRedo, setCanRedo] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  /** 没存上时那句给人看的话(后端那句,或者本地这一句兜底)。 */
  const [failure, setFailure] = React.useState<string | null>(null);

  const showUnderlayRef = React.useRef(showUnderlay);

  /** 文档尺寸只有一个来源:写入口自己。两边各记一份迟早分叉,而分叉的后果正是"只写了一半"。 */
  const writer = () => writerRef.current as ReturnType<typeof createMaskWriter>;
  const doc = () => writer().size;
  const maskContext = (): MaskContext | null => writer().context();

  const syncHistory = () => {
    const { steps, at } = historyRef.current;
    setCanUndo(at > 0);
    setCanRedo(at >= 0 && at < steps.length - 1);
  };

  /** 当前蒙版的单通道快照(存撤销栈用)。 */
  const snapshot = (): Uint8ClampedArray | null => maskContext()?.snapshot() ?? null;

  /**
   * 把当前状态画到看得见的那张画布上:底图原样在下面,要改的地方压暗 + 着蒙版色叠上去。
   *
   * **只读 ref** —— 所以这个函数在整个生命周期里是同一个,几个 effect 不会因为它的身份变化而重跑。
   * 层表由 `showUnderlayRef` 决定(「显示底图」关掉就只剩蒙版本身),颜色由 `tintRef` 给(主题色,
   * 每帧读样式是不行的 —— 见 lib/themeColor),合成方式全在 lib/maskPixels 的 `maskViewLayers` 里,
   * 这边只负责把它交给 `drawMaskView`。
   */
  const paint = React.useCallback(() => {
    const view = viewRef.current;
    const ctx = view?.getContext("2d") ?? null;
    if (!view || !ctx) return;
    const underlay = underlayRef.current?.image ?? null;
    const scratch = scratchRef.current ?? (scratchRef.current = document.createElement("canvas"));
    drawMaskView(ctx, {
      plan: maskViewLayers({ hasUnderlay: Boolean(underlay), showUnderlay: showUnderlayRef.current, tint: tintRef.current }),
      mask: writer().canvas(),
      underlay,
      scratch,
      width: view.width,
      height: view.height,
    });
  }, []);

  /**
   * 把画布量成**「按原始比例缩进盒子」的那块矩形**(contain),再把当前蒙版重画上去。
   *
   * 维护者:「注意图片应该是原先的比例」。此前画布元素铺满盒子(`h-full w-full`)、位图也按盒子的
   * 尺寸写 —— 源图不是盒子那个比例时**被拉伸/压扁**(竖幅 1624×2880 放进横幅的盒子几乎认不出来)。
   * 现在这里同时定下两件事,两者永远同一个宽高比:
   *
   * - **CSS 尺寸** = contain 之后那块矩形(居中由外层的 `place-items-center` 做)。画布元素自己就是
   *   那个矩形,所以**四周的留白是弹窗自己的底色**(不是把画布刷黑 —— 那正是上一轮抱怨的"两条大黑边"),
   *   而矩形四条边由画布自己的 `border` 画出来,用户知道能画到哪。
   * - **位图尺寸** = 上面那块 × devicePixelRatio(封在 MAX_VIEW_EDGE 里),和文档同一个宽高比 ⇒
   *   底图与蒙版 1:1 画上去,不变形。
   *
   * 所以**量的必须是外面那个盒子**(`frameRef`),不能再量画布自己:画布的 CSS 尺寸是这里写下去的,
   * 量它就成了自己咬自己。
   */
  const fit = React.useCallback(() => {
    const frame = frameRef.current;
    const view = viewRef.current;
    if (!frame || !view) return;
    //: 拖笔途中不重量(下面几处按指针维护 drawingRef):读 clientWidth 会让浏览器先把版面算一遍,
    //: 而这里每帧都会被 ResizeObserver 叫一次。
    if (drawingRef.current) return;
    const boxWidth = frame.clientWidth;
    const boxHeight = frame.clientHeight;
    //: jsdom 里量出来是 0(没有版面);真实环境里也可能是对话框刚挂上、还没量到的那一帧。
    if (!boxWidth || !boxHeight) return;
    const { width: docWidth, height: docHeight } = doc();
    //: contain:两个方向的缩放比取小的那个 —— 长边贴住盒子,短边按原始比例留白。
    const scale = Math.min(boxWidth / docWidth, boxHeight / docHeight);
    const css = { width: Math.max(1, Math.round(docWidth * scale)), height: Math.max(1, Math.round(docHeight * scale)) };
    const width = `${css.width}px`;
    const height = `${css.height}px`;
    if (view.style.width !== width || view.style.height !== height) {
      view.style.width = width;
      view.style.height = height;
    }
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const cap = Math.min(1, MAX_VIEW_EDGE / Math.max(css.width * ratio, css.height * ratio));
    const next = {
      width: Math.max(1, Math.round(css.width * ratio * cap)),
      height: Math.max(1, Math.round(css.height * ratio * cap)),
    };
    if (view.width === next.width && view.height === next.height) return;
    view.width = next.width;
    view.height = next.height;
    paint();
  }, [paint]);

  /**
   * 重铺文档:一张和底图一样大的黑画布 + 底稿,撤销栈从头开始。
   *
   * `carry` 是给「图读完、尺寸变了」那一趟用的:还没读完图就画了几笔的话,那几笔跟着换尺寸,
   * 不丢。打开时那一趟是 false —— 上一次打开留下的笔画不该跟到这一次来。
   */
  const rebuild = React.useCallback(
    (size: Size, carry: boolean) => {
      const next = capsSize(size);
      const previous = writer().canvas();
      //: 黑底由写入口自己铺(`clear()` 那一下 —— 它是不透明那条底线,不是装饰)。
      const ctx = writer().resize(next.width, next.height);
      const draft = draftRef.current;
      if (draft) {
        //: 底稿铺满整张文档(尺寸不一致时缩放):继续画的就是它。
        ctx.paste(draft, PASTE_DRAFT);
      } else if (carry && previous && (previous.width !== next.width || previous.height !== next.height)) {
        ctx.paste(previous, PASTE_PREVIOUS);
      }
      const first = snapshot();
      historyRef.current = first ? { steps: [first], at: 0 } : { steps: [], at: -1 };
      lastStepRef.current = null;
      syncHistory();
      //: `fit()` 在位图尺寸没变时**不会重画**(那条早退是留给 ResizeObserver 的:尺寸没变就没有新内容),
      //: 而 rebuild 换的是**内容** —— 底图读进来那一趟尺寸常常和打开时那一趟一模一样,少了这一下,
      //: 屏幕上就一直停着上一张蒙版,底图要等用户下一次动手才出现。
      fit();
      paint();
    },
    [fit, paint],
  );

  //: 「显示底图」是个纯显示开关:它只重画看得见的那张,不碰撤销栈、不重铺文档。
  React.useEffect(() => {
    showUnderlayRef.current = showUnderlay;
    if (open) paint();
  }, [open, showUnderlay, paint]);

  /**
   * 主题色变了就重画 —— **缓存更新之后必须自己画一次**:`paint()` 每一帧只读 `tintRef`,不会反过来
   * 发现主题变过。少了这一趟,浅 ↔ 深切过去(或者切回来)屏幕上还是上一个主题那个红,要等用户下一次
   * 动手才跟上 —— 和刚修过的「底图读进来要等下一次动手」是同一个坑,不再造一个。
   */
  React.useEffect(() => {
    tintRef.current = tint;
    if (open) paint();
  }, [open, tint, paint]);

  React.useEffect(() => {
    if (!open) return;
    rebuild({ width: DEFAULT_DOC, height: DEFAULT_DOC }, false);
  }, [open, rebuild]);

  //: 底图和底稿读进来。读完把文档换成底图的尺寸 —— 蒙版要和它对齐。
  React.useEffect(() => {
    if (!open) return;
    let alive = true;
    underlayRef.current = null;
    draftRef.current = null;
    setHasUnderlay(false);
    setFromSource(null);
    setFailure(null);
    void (async () => {
      const [underlay, draft] = await Promise.all([
        source ? loadImage(assetPreviewUrl(source.assetId)) : Promise.resolve(null),
        initial ? loadImage(assetPreviewUrl(initial.assetId)) : Promise.resolve(null),
      ]);
      if (!alive) return;
      underlayRef.current = underlay;
      draftRef.current = draft?.image ?? null;
      setHasUnderlay(Boolean(underlay));
      const size = underlay ?? draft;
      rebuild(size ? { width: size.width, height: size.height } : { width: DEFAULT_DOC, height: DEFAULT_DOC }, true);
    })();
    return () => {
      alive = false;
    };
  }, [open, source?.assetId, initial?.assetId, rebuild]);

  /**
   * 放画布的那个盒子一换大小(窗口变了、右栏收窄了)就重量一遍 —— 按新盒子重算 contain 那块矩形,
   * **比例跟着走**(小窗口里竖幅图整张看得全,不溢出)。
   */
  React.useEffect(() => {
    if (!open || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => fit());
    //: **不能在 effect 里读 ref**:这一条 effect 排在那几条铺文档的 effect 后面,而它们那一轮跑的
    //: 时候 ref 还没挂上(`<DialogContent>` 是 portal,子树先于父 ref 落地)—— 读到 null 就 return
    //: 的话,这一整条 observer 永远不会登记(实测:窗口拖大、对话框换尺寸,位图一直停在第一次量到
    //: 的那个尺寸上)。下一帧再登记,那时盒子一定在文档里。观的是**盒子**,画布自己的尺寸是写下去的。
    const frame = requestAnimationFrame(() => {
      const box = frameRef.current;
      if (box) observer.observe(box);
    });
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [open, fit]);

  /**
   * 记一步。`kind` 相同就**并进上一步** —— 阈值滑块拖一下午不该攒出两百步撤销。
   */
  const pushHistory = (kind: string | null) => {
    const snap = snapshot();
    if (!snap) return;
    const history = historyRef.current;
    const coalesce = kind !== null && kind === lastStepRef.current && history.at > 0;
    let steps = history.steps.slice(0, history.at + 1);
    if (coalesce) steps[steps.length - 1] = snap;
    else steps.push(snap);
    const bytes = steps[0]?.length ?? 0;
    while (steps.length > 1 && (steps.length > HISTORY_LIMIT || steps.length * bytes > HISTORY_BYTES)) steps.shift();
    historyRef.current = { steps, at: steps.length - 1 };
    lastStepRef.current = kind;
    syncHistory();
  };

  /**
   * 把一份单通道快照写回蒙版。
   *
   * **尺寸对不上就整张不动**:那份快照说的是另一张画布(拖动途中底图读进来、文档换了尺寸,见下面那条
   * `drag.before` 的重取)。这条不是洁癖 —— `createImageData` 是**零填充**的,`writeGrayscale` 只写
   * 它覆盖得到的那一段:差一个像素,剩下的就全是 `alpha 0`。蒙版一旦有透明像素:
   *
   * - 屏幕上那两张派生层(`maskInverse` / `maskTint`)遇到透明像素会**保持底色**(`difference` /
   *   `multiply` 都按源的 alpha 加权)—— 没画过的地方不再等于原图、**整块画布被蒙版色糊住**;
   * - **导出的 PNG 带上 alpha 通道** —— 插件那条 `LoadImageMask(channel="red")` 读出来整块不透明,
   *   静默地什么都不重绘(见文件头那条契约)。
   */
  const restore = (channel: Uint8ClampedArray) => {
    //: 「整张写、尺寸不符就拒绝」这一步在写入口里(`MaskContext.restore`):这里读不到"写了一半"的状态。
    if (maskContext()?.restore(channel)) paint();
  };

  const undo = () => {
    const history = historyRef.current;
    if (history.at <= 0) return;
    history.at -= 1;
    lastStepRef.current = null;
    syncHistory();
    restore(history.steps[history.at]);
  };

  const redo = () => {
    const history = historyRef.current;
    if (history.at >= history.steps.length - 1) return;
    history.at += 1;
    lastStepRef.current = null;
    syncHistory();
    restore(history.steps[history.at]);
  };

  /** 取像素 → 调纯函数 → **整张**写回,一步(反选、羽化都走它)。 */
  const transform = (run: (data: MaskPixels, size: Size) => void) => {
    const ctx = maskContext();
    if (!ctx) return;
    const image = ctx.read();
    run(image.data, { ...ctx.size });
    ctx.write(image);
    pushHistory(null);
    paint();
  };

  /**
   * 清空 = 整张铺黑(= "这块不改",和橡皮写进去的是同一个值)。
   *
   * 它**只碰蒙版那一张**:底图在另一张画布上(可见那张的层表第一层),这里连它的引用都拿不到。
   */
  const clear = () => {
    const ctx = maskContext();
    if (!ctx) return;
    ctx.clear();
    pushHistory(null);
    paint();
  };

  const invert = () => transform((data) => invertMask(data));

  const applyFeather = () => transform((data, size) => featherMask(data, size.width, size.height, feather));

  /**
   * 从底图起手(ADR 0056 决定 5 的 MaskFromColor 等价物):底图像素复制一份 → 阈值二值化 → 变成初笔迹。
   *
   * **算的底永远是底图那份像素**,不在已经画过的笔迹上再叠一次:阈值滑块来回拖是「重新决定这条线画在哪」,
   * 不是「越拖越白」。所以重算会**替换**当前笔迹(而不是叠上去)。
   */
  const initFromSource = (mode: FromSource, value: number, kind: string | null) => {
    const underlay = underlayRef.current;
    const ctx = maskContext();
    if (!underlay || !ctx) return;
    const copy = new Uint8ClampedArray(underlay.data);
    if (mode === "luminance") thresholdMask(copy, value);
    else alphaMask(copy, value);
    //: 先写进一张和底图同尺寸的画布,再铺到文档上 —— 两者尺寸不同(读图之前就按过)时也不会错位。
    const scratch = document.createElement("canvas");
    scratch.width = underlay.width;
    scratch.height = underlay.height;
    const scratchCtx = scratch.getContext("2d");
    if (!scratchCtx) return;
    const image = scratchCtx.createImageData(underlay.width, underlay.height);
    image.data.set(copy);
    scratchCtx.putImageData(image, 0, 0);
    //: 整张铺(先复位再画,见 MaskContext.paste)—— 部分覆盖会让没碰到的地方留下上一次的像素。
    ctx.paste(scratch, PASTE_THRESHOLD);
    pushHistory(kind);
    paint();
  };

  const pressFromSource = (mode: FromSource) => {
    setFromSource(mode);
    initFromSource(mode, threshold, null);
  };

  const changeThreshold = (value: number) => {
    setThreshold(value);
    //: 还没按过那两个按钮时,滑块只是先定个数;按过之后,改动即时重算。
    if (fromSource) initFromSource(fromSource, value, `threshold:${fromSource}`);
  };

  const docPoint = (event: React.PointerEvent<HTMLCanvasElement>): Point | null => {
    const view = viewRef.current;
    if (!view) return null;
    const rect = view.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const { width, height } = doc();
    return {
      x: ((event.clientX - rect.left) / rect.width) * width,
      y: ((event.clientY - rect.top) / rect.height) * height,
    };
  };

  /** 一笔的墨:笔刷写白(要改)、橡皮写黑(不改)。见文件头「橡皮 = 写黑」那一节。 */
  const inkOf = (tool: Tool) => (tool === "brush" ? { ink: WHITE, fade: FADE_WHITE } : { ink: BLACK, fade: FADE_BLACK });

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const ctx = maskContext();
    const at = docPoint(event);
    if (!ctx || !at) return;
    //: 指针捕获在合成事件 / 某些设备上是会抛的(没有活动指针)。它只是"手指滑出画布也算数"的便利,
    //: 抛了不该让这一笔整个断掉 —— 拖动的状态机在下面,和它无关。
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      //: 拿不到就算了,拖动照旧。
    }
    drawingRef.current = true;
    const freehand = tool === "brush" || tool === "eraser";
    dragRef.current = { tool, from: at, last: at, before: freehand ? null : snapshot() };
    if (freehand) {
      const { ink, fade } = inkOf(tool);
      ctx.stroke((raw) => paintLine(raw, at, at, radius / 2, hardness, ink, fade));
    } else {
      ctx.beginStroke();
      ctx.preview((raw) => paintShape(raw, tool, at, at));
    }
    paint();
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    const ctx = maskContext();
    const at = docPoint(event);
    if (!drag || !ctx || !at) return;
    if (drag.tool === "brush" || drag.tool === "eraser") {
      const { ink, fade } = inkOf(drag.tool);
      ctx.stroke((raw) => paintLine(raw, drag.last, at, radius / 2, hardness, ink, fade));
    } else {
      //: 形状工具每一帧都从按下时那份像素重来:看到的是「松手后会是这样」,不是一层层叠上去的边。
      //: **按下之后底图才读进来**(文档换了尺寸)的话,那份快照已经作废 —— 重取一份当前的,
      //: 否则 `restore` 会把整张挡掉(它拒绝写尺寸对不上的快照),预览就从"每帧重来"变成"一层层叠"。
      if (drag.before && drag.before.length !== doc().width * doc().height) {
        drag.before = snapshot();
        ctx.beginStroke();
      }
      ctx.preview((raw) => paintShape(raw, drag.tool, drag.from, at));
    }
    drag.last = at;
    paint();
  };

  const onPointerUp = () => {
    drawingRef.current = false;
    maskContext()?.endStroke();
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    //: 形状工具**点一下没拖**(一个 0×0 的框,什么都没画上)不算一步:撤销栈里不该多出一条看不出变化,
    //: 却要按一次才过得去的记录。画笔那支点一下就是一个点,是真的画上了。
    const painted =
      drag.tool === "brush" || drag.tool === "eraser" || drag.last.x !== drag.from.x || drag.last.y !== drag.from.y;
    if (painted) pushHistory(null);
  };

  const close = () => {
    //: 上传中途关掉 = 不等它了(importAsset 收了 signal)。
    abortRef.current?.abort();
    abortRef.current = null;
    setSaving(false);
    onOpenChange(false);
  };

  const save = () => {
    const canvas = writer().canvas();
    if (!canvas) return;
    setFailure(null);
    setSaving(true);
    const controller = new AbortController();
    abortRef.current = controller;
    canvas.toBlob((blob) => {
      if (!blob) {
        setSaving(false);
        setFailure(t("maskSaveFailed"));
        return;
      }
      const file = new File([blob], MASK_FILE_NAME, { type: "image/png" });
      const name = t("maskAssetName").replace("{source}", source?.name || t("maskAssetNoSource"));
      importAsset({ workspaceId, file, name, signal: controller.signal })
        .then((asset) => {
          abortRef.current = null;
          setSaving(false);
          void queryClient.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
          void queryClient.invalidateQueries({ queryKey: assetKeys.everywhere() });
          onDone(asset);
        })
        .catch((error: unknown) => {
          //: 中途关掉弹窗 = 不等它了,不是失败。
          if (controller.signal.aborted) return;
          abortRef.current = null;
          setSaving(false);
          setFailure(errorText(error) || t("maskSaveFailed"));
        });
    }, "image/png");
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent
        //: 全屏尺寸的弹窗:画布要尽可能大,底图和笔迹才看得清。**两栏一封**:左边画布、右边控制栏,
        //: 取消 / 存成蒙版落在右栏最底 —— 不再横跨一条底栏(维护者:「排版优化 除去 header,左右分栏,
        //: 右下角按钮放到右侧分栏去」)。
        //
        // 列宽写在一处(`--mask-rail`):右栏和它里面的动作组都读它,所以「存成蒙版」永远落在右栏这条
        // 竖线上,而不是自己另算一个右边距。第一列是 `minmax(0,1fr)`,画布再怎么宽也顶不开这一栏
        // (见 CONVENTIONS「单列 grid 想收缩要写 minmax(0,1fr)」)。
        className="w-[min(1180px,calc(100vw-32px))] max-w-none h-[min(820px,calc(100dvh-32px))] max-h-[calc(100dvh-32px)] grid-cols-[minmax(0,1fr)_var(--mask-rail)] grid-rows-[minmax(0,1fr)] gap-4 overflow-hidden p-5 [--mask-rail:18rem]"
      >
        {/*
          * 标题还在、**只是看不见**(`sr-only`):无障碍名 —— 以及既有测试找它的 `role=dialog` + 名字
          * 「画蒙版」—— 都靠它,radix 少了 `DialogTitle` 也会告警。视觉上不再占顶部那一条:整个弹窗就是
          * 「画布 + 右栏」两块。`pt-8` 是给右上角那颗 ✕ 让位(它离弹窗顶 16px、高 32px,压在右栏顶上)。
          */}
        <DialogTitle className="sr-only">{t("maskEditorTitle")}</DialogTitle>
          {/*
            * 看得见的画布:底图 + 蒙版。导出的不是这一张 —— 见文件头那三张画布。
            *
            * **画布元素自己就是那块「按原始比例缩进盒子」的矩形**(contain):CSS 尺寸由 fit() 写,
            * 宽高比 = 文档的宽高比,`place-items-center` 把它摆在盒子中间。于是:
            *
            * - 源图不会被拉扁/拉长(维护者:「注意图片应该是原先的比例」);
            * - 四周的留白是**弹窗自己的底色** —— 盒子上没有背景色,不是把画布刷黑(那两条"大黑边"
            *   正是上一轮的抱怨);矩形四条边由画布自己的 `border` 画出来,用户知道能画到哪;
            * - 落点换算(`docPoint`)读的仍是这个元素自己的矩形 —— 元素和画出来的图同一个宽高比,
            *   屏幕坐标到蒙版像素的换算不用另外加偏移(拖动中途指针跑到留白上也只是落在文档外,
            *   `fillRect` / 圆的裁剪照旧)。
            *
            * 行轨写成 `minmax(0,1fr)` 而不是让它自己算:画布有固有宽高比,`auto` 那一档会按内容
            * (也就是位图本身)反推出一个更高的行,盒子只有 519 高、行却长到 546,画布就溢出到边框
            * 外面去了 —— 单列 grid 想收缩要写 `minmax(0,…)`,和 CONVENTIONS 里那条是同一件事。
            */}
          {/*: 留白(contain 出来的那两条边)就是这一格的底色 —— 弹窗自己的,不刷黑。没有 padding:
               `fit()` 量的 `clientWidth` 含 padding,量出来的"盒子"会比能用的那一块大。 */}
          <div ref={frameRef} className="grid min-h-0 min-w-0 place-items-center overflow-hidden">
            <canvas
              ref={viewRef}
              className="block max-h-full max-w-full cursor-crosshair touch-none rounded-[2px] border border-border-strong"
              aria-label={t("maskCanvasLabel")}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            />
          </div>

          {/*
            * 控制栏:固定宽度(和正文字体一样,由外壳上的 `--mask-rail` 定),里面三节。
            *
            * 三节的节奏由 ToolGroup 一处管:节标题同一个字重,节与节之间同一条 1px 分隔线 + 同一段
            * 留白(和设置页的分节同一种做法)。此前三节各写各的间距,只有靠加粗小标题硬分。
            */}
          {/*
            * 右栏三段:顶上那行说明(它解释的是「白色是要改的地方」这条契约 —— 所以留下、缩小、
            * 次要色,而**不是**再变回一条 header)+ 三节控件(唯一会滚的地方)+ 底盘的动作组。
            * `pt-8` 让开右上角那颗关闭键(见 DialogTitle 那句);两个轴一起锁 —— 只写 `grid-rows` 的话
            * 隐式列按 max-content 定尺,右栏会被内容顶宽(见 design/gridAxes.test.ts 那条棘轮)。
            */}
          <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto] gap-3 pt-8">
            <DialogDescription className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
              {t("maskEditorHint")}
            </DialogDescription>
            <div className="grid min-h-0 content-start gap-3 overflow-y-auto pr-1">
            <ToolGroup label={t("maskTool")} icon={<Brush size={13} />}>
              <Segmented
                aria-label={t("maskTool")}
                value={tool}
                onValueChange={setTool}
                size="sm"
                fill
                options={[
                  { value: "brush", icon: <Brush size={14} />, ariaLabel: t("maskBrush") },
                  { value: "eraser", icon: <Eraser size={14} />, ariaLabel: t("maskEraser") },
                  { value: "rect", icon: <Square size={14} />, ariaLabel: t("maskRect") },
                  { value: "ellipse", icon: <Circle size={14} />, ariaLabel: t("maskEllipse") },
                ]}
              />
              <SliderField label={t("maskBrushSize")} value={radius} min={2} max={200} step={1} format={pixels} onChange={setRadius} />
              <SliderField
                label={t("maskBrushHardness")}
                value={hardness}
                min={0}
                max={1}
                step={0.05}
                format={percent}
                onChange={setHardness}
              />
              {/*: 撤销 / 重做 / 清空:一排等宽铺满整行,不挤在左边留一截。 */}
              <div className="grid grid-cols-3">
                <IconButton label={t("maskUndo")} disabled={!canUndo} onClick={undo} className="w-full">
                  <Undo2 />
                </IconButton>
                <IconButton label={t("maskRedo")} disabled={!canRedo} onClick={redo} className="w-full">
                  <Redo2 />
                </IconButton>
                <IconButton label={t("maskClear")} onClick={clear} className="w-full">
                  <Trash />
                </IconButton>
              </div>
            </ToolGroup>

            <ToolGroup label={t("maskFeather")} icon={<Feather size={13} />}>
              <SliderField label={t("maskFeatherRadius")} value={feather} min={1} max={64} step={1} format={pixels} onChange={setFeather} />
              <Button variant="outline" size="sm" className="w-full" onClick={applyFeather}>
                <Feather />
                {t("maskFeather")}
              </Button>
            </ToolGroup>

            <ToolGroup label={t("maskFromSource")} icon={<SunMedium size={13} />}>
              {/*: 底图读到之前按了也没用 —— 说清楚为什么,而不是只灰掉。 */}
              <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("maskFromSourceHint")}</p>
              {/*: 说明管着的就是下面这一排动作,所以两个初始化键并排铺满、和说明同宽。 */}
              <div className="grid grid-cols-2">
                <Button variant="outline" size="sm" disabled={!hasUnderlay} onClick={() => pressFromSource("luminance")}>
                  <SunMedium />
                  {t("maskFromLuminance")}
                </Button>
                <Button variant="outline" size="sm" disabled={!hasUnderlay} onClick={() => pressFromSource("alpha")}>
                  <Droplets />
                  {t("maskFromAlpha")}
                </Button>
              </div>
              <SliderField label={t("maskThreshold")} value={threshold} min={0} max={1} step={0.01} format={percent} onChange={changeThreshold} />
              {/*
                * **和上面四根滑块同一条竖线**,而且**不把开关拉长**:名字在 5rem 那一列,开关按
                * `Switch` 自己的尺寸(`h-5 w-9` = 36×20)落在控件列的**起点**上(`justify-self-start`)
                * —— 排一行靠的是 grid 的列,不是把控件撑满。`w-full` 会把那颗开关拉成一条 124px 的长
                * 胶囊(实测),而上面四根滑轨的起点在同一个 x 上,一眼就看出不是一套。
                *
                * 反选那颗方钮落在值那一列、和右值同一条右边线。`role="switch"` 自己挂 aria-label:
                * 套在 `<label>` 里读屏名字会是「显示底图 开关」。
                */}
              <div className="grid grid-cols-[5rem_minmax(0,1fr)_3.5rem] items-center gap-x-3">
                <span className="min-w-0 text-ui-xs text-muted-foreground">{t("maskShowSource")}</span>
                <Switch aria-label={t("maskShowSource")} checked={showUnderlay} onCheckedChange={setShowUnderlay} className="justify-self-start" />
                <IconButton label={t("maskInvert")} onClick={invert} className="justify-self-end">
                  <Contrast />
                </IconButton>
              </div>
            </ToolGroup>
            </div>

            {/*
              * 动作组钉在右栏**最底**:上面那一行才是唯一滚动的地方 ⇒ 小窗口里它也**始终可见**
              * (不会被滚走)。分隔节奏和上面各节同一条(`border-t border-divider pt-4`,见 ToolGroup)。
              * 两个键并排等宽、**铺满右栏** —— 和这条列里其它行的左右边界对齐。
              */}
            <div className="grid gap-3 border-t border-divider pt-4">
              {failure && (
                <FailureCard size="inline" className="max-w-full" title={t("maskSaveFailed")} summary={failure} copyText={failure} />
              )}
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" className="w-full" onClick={close}>
                  {t("cancel")}
                </Button>
                <Button loading={saving} className="w-full" onClick={save}>
                  <Check />
                  {t("maskSave")}
                </Button>
              </div>
            </div>
          </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * 控制栏里的一节:**同一层级的小标题** + 内容。
 *
 * 节与节之间只有这一处节奏:一条 1px 分隔线(`--divider`,和设置页的分节同色)+ 同一段上留白。
 * 此前是三节各写各的 gap,靠加粗小标题硬分,眼睛得自己找边界在哪。
 *
 * 分隔线用 `border-t` 画在**后一节自己身上**(不是插一个 `<hr>`):插独立元素的话,条件渲染的
 * 那一节一走开,线上就会多出一条底下什么都没有的线(设置页踩过这一下,见 CONVENTIONS)。
 */
function ToolGroup({ label, icon, children }: { label: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="grid gap-3 border-t border-divider pt-4 first:border-t-0 first:pt-0">
      <h3 className="flex items-center gap-1.5 text-ui-xs font-semibold text-foreground">
        <span className="text-muted-foreground" aria-hidden>
          {icon}
        </span>
        {label}
      </h3>
      <div className="grid gap-3">{children}</div>
    </section>
  );
}

/**
 * 一根滑块 + 名字 + 当前值。
 *
 * **五行带名字的一行对齐成一条竖线**:名字、控件、右值各占固定的一列 —— 名字 5rem,值 3.5rem
 * (等宽数字,值变宽变窄不推控件),控件吃掉中间剩下的。此前是「名字和值一行、滑块另起一行」:
 * 四行的名字左边距一样只是碰巧,滑块更是各走各的宽度,扫下来没有一条能对上的边。
 *
 * 名字和值都**不截断**:它们是固定文案和几字符的数(`200 px` / `100%`),5rem + 3.5rem 那一栏
 * 放得下;真要放不下就折行,而不是把字切掉(切了要配 Truncate 的悬停全文,见 design/truncatedText)。
 */
function SliderField({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format?: (value: number) => string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="grid grid-cols-[5rem_minmax(0,1fr)_3.5rem] items-center gap-x-3 text-ui-xs text-muted-foreground">
      <span className="min-w-0">{label}</span>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={([next]) => onChange(next)} />
      <span className="text-right tabular-nums">{format ? format(value) : String(value)}</span>
    </label>
  );
}

const percent = (value: number) => `${Math.round(value * 100)}%`;
const pixels = (value: number) => `${Math.round(value)} px`;
