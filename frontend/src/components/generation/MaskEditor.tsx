import * as React from "react";
import {
  Brush,
  Check,
  Circle,
  Contrast,
  Droplets,
  Eraser,
  Maximize2,
  Redo2,
  Square,
  SunMedium,
  Trash,
  Undo2,
  Wand2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { assetPreviewUrl, savePaintedMask, type Asset } from "@/api/domains/assets";
import { errorText } from "@/api/errorMessage";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { CanvasInputModeSwitch } from "@/components/app/CanvasInputModeSwitch";
import { CanvasToolbar, CanvasToolbarGroup } from "@/components/app/CanvasToolbar";
import { useCanvasInputMode } from "@/components/app/canvasInputMode";
import { FailureCard } from "@/components/failure/FailureCard";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
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
  growMask,
  invertMask,
  maskViewLayers,
  thresholdMask,
  type MaskContext,
  type MaskPixels,
  type MaskViewLayer,
} from "@/lib/maskPixels";
import { formatCombo, isTypingTarget } from "@/lib/shortcuts";
import { useThemeColor } from "@/lib/themeColor";

import {
  ZOOM_STEP,
  center,
  clampPan,
  fitCamera,
  panBy,
  placement,
  toDoc,
  visiblePart,
  wheelIntent,
  zoomAround,
  type Camera,
  type Point,
  type Rect,
  type Size,
} from "./maskCamera";

/**
 * 蒙版编辑器:在**浏览器 canvas** 上画出「要改的那一块」,存成一张蒙版素材(ADR 0056 第二步,ADR 0057 决定 3)。
 *
 * ## 产出的东西是一张黑白图,不是一张带 alpha 的图
 *
 * 契约在 `backend/app/ai/providers/contracts/generation.py` 的 MASK:**灰度图、白 = 要改的地方**。
 * ComfyUI 插件那条路注入的是 `LoadImageMask(image=…, channel="red")`,读的是**红通道**
 * (`plugins/bundled/comfyui/tools/graph.py` 的 `_MASK_CHANNEL`)。所以蒙版画布是**不透明的黑底 + 白笔迹**,
 * 导出的就是它:带透明通道的 PNG 在那边读出来是整块不透明,**静默地什么都不重绘**。存的时候交给后端那个
 * 唯一的写出口(`POST /api/assets/masks` → `write_mask_asset`):名字、出处、归一成 L 模式、缩回源图尺寸
 * 都是那边的事,这里只交像素。
 *
 * ## 文档与视口分开
 *
 * | 画布 | 在哪 | 装什么 |
 * | --- | --- | --- |
 * | 底图 | 只在看得见的这张上 | 要改的那张原图 —— **导出的蒙版里永远没有它** |
 * | 蒙版(离屏,"文档") | 不进 DOM,和底图一样大(长边封顶 4096) | 黑白笔迹。笔画累积在它上面,**导出的也是它** |
 * | 可见的那张 | 对话框里,铺满画布区 | 透过一台**相机**(`maskCamera`:缩放 + 平移)看底图 + 蒙版 |
 *
 * 适应窗口 / 100% / 放大缩小 / 滚轮 / 捏合 / 空格拖动 / 中键拖动都只改相机那三个数,不碰蒙版的一个像素;
 * 底图永远按原始比例画(相机只有一个缩放)。滚轮的语义跟全局的画布操控方式走(触控板:双指平移、捏合缩放;
 * 鼠标:滚轮缩放),这里只读不改。
 *
 * ## 可见的那张不能把蒙版整张盖上去
 *
 * 蒙版是**不透明**的,`source-over` 整张画上去就是一块黑板。可见的那张照 `maskViewLayers` 给的层表画
 * (`drawMaskView`):底图原样在下面,要改的地方**压暗 + 着蒙版色**叠在上面。蒙版色是主题 token
 * (2D 上下文读不到 CSS 变量),按主题解析一次缓存在 ref 里,主题一切就重画。
 *
 * ## 读底图像素为什么要绕一圈 fetch
 *
 * `assetPreviewUrl` 是**后端的源**,直接给 `<img>` 再画进画布会把画布**污染**(tainted canvas)——
 * 之后 `getImageData` / `toBlob` 一律 SecurityError。所以走 fetch → blob → 对象 URL。
 * 读不到(断网、不是图片)就是**没有底图**,编辑器照样能画。
 *
 * ## 「只动蒙版」不是靠自觉,是靠拿不到别的口子
 *
 * 蒙版那张画布由 `lib/maskPixels` 的 `createMaskWriter()` 发,**交出来的只有那几个语义方法**
 * (`read` / `write` / `clear` / `paste` / `snapshot` / `restore` / `stroke` / `preview`)。
 * 加新动作时不要在这里要原始 ctx:笔迹类走 `stroke` / `preview`,整张类走 `write` / `clear` / `paste`。
 * 「橡皮 = 写黑」也是这条不变量的一部分:蒙版没有 alpha 可用,"擦掉"在数据上只能是写黑;屏幕上
 * "擦完露出原图"由**底图那一层**负责。像素运算(反选 / 阈值 / 扩张 / 羽化)全在 `lib/maskPixels`,
 * 和后端由 `contracts/mask-cases.json` 逐字节钉住。
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
/** 撤销栈最多几步(一次按下到松手、一条命令各算一步)。 */
const HISTORY_LIMIT = 30;
/**
 * 撤销栈的总字节上限。一步是**一个像素一个字节**(见 lib/maskPixels 的 grayscaleOf):4096² 的一步
 * 就是 16MB,三十步五百兆,标签页会先卡住。
 */
const HISTORY_BYTES = 96 * 1024 * 1024;
/**
 * 蒙版文档的尺寸上限(长边)。底图比这还大就按比例缩下来:8000² 的一张 RGBA 画布是 256MB,
 * 出口那边会按源图尺寸缩回去(ADR 0057 决定 1)。
 */
const MAX_DOC_EDGE = 4096;
/**
 * **可见那张**画布的位图上限(长边)。浏览器的画布内存是**所有**画布共用的(这个对话框里还有底稿、
 * 派生层、导出用的那张),超了之后新建画布会静默地画不出东西。2048 换到屏幕上看不出软。
 */
const MAX_VIEW_EDGE = 2048;
/** 笔刷大小的范围(文档像素,直径)。 */
const BRUSH_MIN = 2;
const BRUSH_MAX = 400;
/** 扩张 / 羽化滑块的范围(文档像素)。 */
const EDGE_MAX = 64;
const TAU = Math.PI * 2;
const BLACK = "#000000";
const WHITE = "#ffffff";
/** 软边渐变的外圈。画布是不透明的,所以"往回混"就够了,不需要 destination-out。 */
const FADE_WHITE = "rgba(255, 255, 255, 0)";
const FADE_BLACK = "rgba(0, 0, 0, 0)";
/** 上传时的文件名(素材名由后端起,见后端 domain/assets/masks.write_mask_asset)。 */
const MASK_FILE_NAME = "mask.png";

type Tool = "brush" | "eraser" | "rect" | "ellipse";
/** 初笔迹是从底图的什么量出来的 —— 阈值滑块改动时重算的就是这一种。 */
type FromSource = "luminance" | "alpha";

/** 工具和它的单键快捷键(画图软件通行的那几个字母)。 */
const TOOL_KEYS: Record<string, Tool> = { b: "brush", e: "eraser", r: "rect", o: "ellipse" };

/** 一次拖动:按下在哪、上一次到哪、形状工具要用的「按下之前那份像素」。 */
interface Drag {
  tool: Tool;
  from: Point;
  last: Point;
  before: Uint8ClampedArray | null;
  /**
   * 按下那一刻的文档尺寸。拖动途中底图 / 底稿读进来(rebuild)会把文档换成另一个尺寸,
   * 而 `from` / `last` 还是旧坐标系的 —— 那时要按新旧尺寸比把它们搬过来(carry 正是把
   * 旧画布按同一个比缩进新文档的),否则这一笔会从旧空间的点划到新空间的点,横跨整张图
   * 落在错位的地方。
   */
  pressed: Size;
}
/** 一次平移拖动(空格 + 左键,或中键):上一次指针在哪(屏幕坐标)。 */
interface PanDrag {
  pointerId: number;
  x: number;
  y: number;
}
/** 读进来的底图(像素 + 那张图本身,后者画在看得见的那张画布上当参考)。 */
interface Loaded extends Size {
  data: MaskPixels;
  image: HTMLImageElement;
}

/** 一份底图 / 底稿:素材 id + 名字。 */
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
  drawImage(
    source: CanvasImageSource,
    sx: number,
    sy: number,
    sw: number,
    sh: number,
    dx: number,
    dy: number,
    dw: number,
    dh: number,
  ): void;
  createRadialGradient(x0: number, y0: number, r0: number, x1: number, y1: number, r1: number): CanvasGradient;
}

/** 一个画布源自己的像素尺寸(`<img>` 读 natural 那一对)。 */
function sourceSize(source: CanvasImageSource): Size {
  const image = source as { naturalWidth?: number; naturalHeight?: number; width?: number; height?: number };
  return {
    width: Number(image.naturalWidth || image.width || 0),
    height: Number(image.naturalHeight || image.height || 0),
  };
}

/** 一个源上对应 `fraction` 那一段的源矩形。 */
function sourceRect(source: CanvasImageSource, fraction: Rect): Rect | null {
  const size = sourceSize(source);
  if (!size.width || !size.height) return null;
  return {
    x: fraction.x * size.width,
    y: fraction.y * size.height,
    width: fraction.width * size.width,
    height: fraction.height * size.height,
  };
}

/**
 * 把看得见的那张画布按层表画出来(层表见 lib/maskPixels 的 maskViewLayers)。
 *
 * 「哪几层、谁在下、各自怎么叠」只有层表那一处 —— 这里只管照着画,不自己决定合成方式。
 *
 * `place` 是整张文档落在这张位图上的矩形(相机给的,见 maskCamera 的 placement);没给就铺满整张。
 * **只画落在位图之内的那一块**(`visiblePart`):放大之后整张文档是几万像素宽,派生层按它分配画布
 * 就是几个 GB。`mask` / `underlay` 允许是 null(还没铺出蒙版、底图没读进来):缺哪层跳哪层。
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
    place,
  }: {
    plan: MaskViewLayer[];
    mask: CanvasImageSource | null;
    underlay: CanvasImageSource | null;
    /** 复用的一张离屏画布:蒙版那两层要先在它上面铺出来(见 maskLayer)。 */
    scratch: HTMLCanvasElement;
    width: number;
    height: number;
    place?: Rect;
  },
): void {
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
  ctx.clearRect(0, 0, width, height);
  const visible = visiblePart(place ?? { x: 0, y: 0, width, height }, { width, height });
  if (visible) {
    const { target, fraction } = visible;
    for (const layer of plan) {
      const source = layer.of === "underlay" ? underlay : mask;
      if (!source) continue;
      const derived = layer.of === "maskInverse" || layer.of === "maskTint";
      const canvas = derived ? maskLayer(scratch, layer.of as "maskInverse" | "maskTint", source, fraction, target, layer.tint ?? "") : source;
      const from = derived ? { x: 0, y: 0, width: target.width, height: target.height } : sourceRect(source, fraction);
      if (!canvas || !from) continue;
      ctx.globalAlpha = layer.alpha;
      ctx.globalCompositeOperation = layer.op;
      ctx.drawImage(canvas, from.x, from.y, from.width, from.height, target.x, target.y, target.width, target.height);
    }
  }
  //: 收尾复位:这张 ctx 还要接着给下一帧用,状态漏出去就是下一帧的第一层叠错了。
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
}

/**
 * 蒙版那一层的底:反相(未画 = 白)或着色(画过 = 蒙版色),只铺看得见的那一块(`target` 那么大)。
 *
 * - 反相:白底上 `difference` 减一次蒙版 → 255 − 蒙版;
 * - 着色:蒙版色上 `multiply` 乘一次蒙版 → 没画的地方是黑(叠上去时 `lighter` 加零 = 什么都不加),
 *   画过的地方是蒙版色。
 *
 * `tint` 是层表带过来的那个颜色。**空串就铺黑**:黑叠上去还是「什么都不加」。不这么办的话,
 * `fillStyle = ""` 会被静默忽略,底色留在上一次那个**白**,画过的地方就糊成一块白斑。
 */
function maskLayer(
  scratch: HTMLCanvasElement,
  kind: "maskInverse" | "maskTint",
  mask: CanvasImageSource,
  fraction: Rect,
  target: Rect,
  tint: string,
): HTMLCanvasElement | null {
  const from = sourceRect(mask, fraction);
  if (!from) return null;
  const width = Math.max(1, Math.ceil(target.width));
  const height = Math.max(1, Math.ceil(target.height));
  //: 尺寸跟着看得见的那一块走;重设 width 会清空整张位图,本来就该重铺。
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
  ctx.drawImage(mask, from.x, from.y, from.width, from.height, 0, 0, target.width, target.height);
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
  const [inputMode] = useCanvasInputMode();
  /** 看得见的那张画布。它铺满画布区(CSS),位图尺寸由 measure() 按自己的盒子写。 */
  const viewRef = React.useRef<HTMLCanvasElement>(null);
  /** 文档的边框(一个跟着相机走的 div):用户看得出图的边在哪、能画到哪。 */
  const frameRef = React.useRef<HTMLDivElement>(null);
  /** 笔刷的圈:跟着指针、按屏幕上的真实大小画(放大之后笔刷看上去也跟着大)。 */
  const ringRef = React.useRef<HTMLDivElement>(null);
  /** 正在画一笔:拖动期间不重量盒子(每一次量都要读版面,而拖动每秒几十次)。 */
  const drawingRef = React.useRef(false);
  /**
   * 蒙版本身 —— 离屏、不进 DOM、导出的就是它。**由 `lib/maskPixels` 的 createMaskWriter 发**:
   * 这里拿不到它的原始 2D 上下文,写它只能走那几个语义方法。
   */
  const writerRef = React.useRef<ReturnType<typeof createMaskWriter> | null>(null);
  if (!writerRef.current) writerRef.current = createMaskWriter();
  React.useEffect(() => {
    //: 发一次记一次(`resize` 会换画布)—— 测试按这张登记表认出蒙版那张。
    const canvas = writer().canvas();
    if (canvas) MASK_CANVASES.add(canvas);
  });
  /** 合成可见那张画布时复用的一张离屏画布(蒙版的反相 / 着色,见 drawMaskView 的 maskLayer)。 */
  const scratchRef = React.useRef<HTMLCanvasElement | null>(null);
  /** 底图像素(按亮度 / 按 alpha 初始化读的就是它)和那张图(画在看得见的画布上)。 */
  const underlayRef = React.useRef<Loaded | null>(null);
  /** 底稿:打开时已经有的那张蒙版。 */
  const draftRef = React.useRef<HTMLImageElement | null>(null);
  const dragRef = React.useRef<Drag | null>(null);
  const panRef = React.useRef<PanDrag | null>(null);
  /** 相机(见 maskCamera)。null = 还没量到盒子(jsdom、对话框刚挂上那一帧)。 */
  const cameraRef = React.useRef<Camera | null>(null);
  /** 相机是不是「适应窗口」那一档:是的话盒子一变就重新适应;用户缩放 / 平移过就不再自作主张。 */
  const fittedRef = React.useRef(true);
  /** 画布元素的 CSS 尺寸(相机的坐标系)。 */
  const boxRef = React.useRef<Size | null>(null);
  /** 指针在不在画布上 —— 空格平移只在这时候接管空格(否则空格还是「按下这颗按钮」)。 */
  const hoverRef = React.useRef(false);
  /** WebKit 的捏合手势:上一次的 scale(Chromium 给的是带 ctrlKey 的滚轮,走 wheelIntent)。 */
  const gestureRef = React.useRef<number | null>(null);
  /** 撤销栈:每一步是**一整个蒙版的单通道灰度**(见 lib/maskPixels 的 grayscaleOf)。 */
  const historyRef = React.useRef<{ steps: Uint8ClampedArray[]; at: number }>({ steps: [], at: -1 });
  /** 上一步是什么(用来把滑块的连续改动并成一步)。 */
  const lastStepRef = React.useRef<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  /** 要改的地方在屏幕上着的色。**按主题解析一次**,`paint()` 只读这个缓存(理由与订阅见 lib/themeColor)。 */
  const tint = useThemeColor(MASK_TINT_TOKEN);
  const tintRef = React.useRef(tint);
  const modeRef = React.useRef(inputMode);
  React.useEffect(() => {
    modeRef.current = inputMode;
  }, [inputMode]);

  const [tool, setTool] = React.useState<Tool>("brush");
  /** 笔刷大小(直径,文档像素)。 */
  const [brushSize, setBrushSize] = React.useState(48);
  const [hardness, setHardness] = React.useState(0.9);
  /** 扩张(正)/ 收缩(负),文档像素。 */
  const [grow, setGrow] = React.useState(0);
  const [feather, setFeather] = React.useState(0);
  const [threshold, setThreshold] = React.useState(0.5);
  const [fromSource, setFromSource] = React.useState<FromSource | null>(null);
  const [showUnderlay, setShowUnderlay] = React.useState(true);
  const [hasUnderlay, setHasUnderlay] = React.useState(false);
  const [canUndo, setCanUndo] = React.useState(false);
  const [canRedo, setCanRedo] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  /** 底栏那一行:输出尺寸和当前缩放(只给人看;真值在 ref 里)。尺寸在底图/底稿读出来之前是 null ——
   *  那一刻输出尺寸还不存在,拿 1024 占位谎称「已确立」正是"打开一瞬间尺寸不对"的来源。 */
  const [readout, setReadout] = React.useState<{ size: Size | null; zoom: number | null }>({
    size: null,
    zoom: null,
  });
  /** 空格按着(准备平移)/ 正在平移 —— 只决定指针的样子。 */
  const [panMode, setPanMode] = React.useState<"off" | "ready" | "dragging">("off");
  /** 没存上时那句给人看的话(后端那句,或者本地这一句兜底)。 */
  const [failure, setFailure] = React.useState<string | null>(null);

  const showUnderlayRef = React.useRef(showUnderlay);
  const spaceRef = React.useRef(false);

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

  /** 文档边框那个 div 跟着相机走(CSS 像素,和相机同一个坐标系)。 */
  const placeFrame = React.useCallback(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const camera = cameraRef.current;
    if (!camera) {
      frame.hidden = true;
      return;
    }
    const { width, height } = writer().size;
    frame.hidden = false;
    frame.style.transform = `translate(${camera.x}px, ${camera.y}px)`;
    frame.style.width = `${width * camera.scale}px`;
    frame.style.height = `${height * camera.scale}px`;
  }, []);

  /**
   * 把当前状态画到看得见的那张画布上:底图原样在下面,要改的地方压暗 + 着蒙版色叠上去。
   *
   * **只读 ref** —— 所以这个函数在整个生命周期里是同一个,几个 effect 不会因为它的身份变化而重跑。
   */
  const paint = React.useCallback(() => {
    const view = viewRef.current;
    const ctx = view?.getContext("2d") ?? null;
    if (!view || !ctx) return;
    const underlay = underlayRef.current?.image ?? null;
    const scratch = scratchRef.current ?? (scratchRef.current = document.createElement("canvas"));
    const camera = cameraRef.current;
    const box = boxRef.current;
    drawMaskView(ctx, {
      plan: maskViewLayers({ hasUnderlay: Boolean(underlay), showUnderlay: showUnderlayRef.current, tint: tintRef.current }),
      mask: writer().canvas(),
      underlay,
      scratch,
      width: view.width,
      height: view.height,
      place: camera && box ? placement(camera, writer().size, view.width / box.width) : undefined,
    });
    placeFrame();
  }, [placeFrame]);

  /** 换相机:记下来、底栏的缩放跟上。`fitted` = 这是不是「适应窗口」那一档。 */
  const setCamera = React.useCallback((next: Camera, fitted: boolean) => {
    cameraRef.current = next;
    fittedRef.current = fitted;
    setReadout((previous) => (previous.zoom === next.scale ? previous : { ...previous, zoom: next.scale }));
  }, []);

  /**
   * 量盒子、写位图尺寸、按需要重新适应窗口。返回「有没有变」—— 没变就不必重画。
   *
   * 量的是**画布元素自己**:它的 CSS 尺寸由版面给(铺满画布区),位图尺寸是这里写的,两者互不咬。
   * 位图 = 盒子 × devicePixelRatio,封在 MAX_VIEW_EDGE 里。
   */
  const measure = React.useCallback(
    (refit: boolean): boolean => {
      const view = viewRef.current;
      if (!view || drawingRef.current) return false;
      const box = { width: view.clientWidth, height: view.clientHeight };
      //: jsdom 里量出来是 0(没有版面);真实环境里也可能是对话框刚挂上、还没量到的那一帧。
      if (!box.width || !box.height) return false;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const cap = Math.min(1, MAX_VIEW_EDGE / Math.max(box.width * ratio, box.height * ratio));
      const bitmap = { width: Math.max(1, Math.round(box.width * ratio * cap)), height: Math.max(1, Math.round(box.height * ratio * cap)) };
      const previous = boxRef.current;
      let changed = !previous || previous.width !== box.width || previous.height !== box.height;
      boxRef.current = box;
      if (view.width !== bitmap.width || view.height !== bitmap.height) {
        view.width = bitmap.width;
        view.height = bitmap.height;
        changed = true;
      }
      const camera = cameraRef.current;
      if (refit || fittedRef.current || !camera) {
        const next = fitCamera(writer().size, box);
        if (!camera || refit || next.scale !== camera.scale || next.x !== camera.x || next.y !== camera.y) changed = true;
        setCamera(next, true);
      } else if (changed) {
        setCamera(clampPan(camera, writer().size, box), false);
      }
      return changed;
    },
    [setCamera],
  );

  /** 盒子换了大小(窗口变了):重量一遍,有变化才重画。 */
  const refresh = React.useCallback(() => {
    if (measure(false)) paint();
  }, [measure, paint]);

  /**
   * 重铺文档:一张和底图一样大的黑画布 + 底稿,撤销栈从头开始,相机回到「适应窗口」。
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
      if (drawingRef.current) {
        //: 拖动途中文档换了尺寸:`measure` 被「拖动中」挡掉,但相机**必须当场重适应** ——
        //: 否则松手之前整张图都按旧文档的尺寸摆(图错位、四周露出画布底色),松手之后也没有
        //: 任何东西会补这一下。不量盒子(盒子没变),只按新文档重算那一档适应窗口。
        const box = boxRef.current;
        if (box) setCamera(fitCamera({ width: next.width, height: next.height }, box), true);
      } else {
        //: 内容换了 —— 不管盒子变没变都要重画一次(底图读进来那一趟尺寸常常和打开时一模一样)。
        measure(true);
      }
      paint();
    },
    [measure, paint, setCamera],
  );

  //: 「显示底图」是个纯显示开关:它只重画看得见的那张,不碰撤销栈、不重铺文档。
  React.useEffect(() => {
    showUnderlayRef.current = showUnderlay;
    if (open) paint();
  }, [open, showUnderlay, paint]);

  /** 主题色变了就重画 —— `paint()` 每一帧只读 `tintRef`,不会反过来发现主题变过。 */
  React.useEffect(() => {
    tintRef.current = tint;
    if (open) paint();
  }, [open, tint, paint]);

  React.useEffect(() => {
    if (!open) return;
    //: 尺寸要等下面那个 effect 读完底图才确立 —— 先清掉上一轮的,别拿旧图/占位的数字顶包。
    setReadout((previous) => (previous.size ? { ...previous, size: null } : previous));
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
      //: 底栏的输出尺寸**此刻才确立**(出口会把蒙版缩回源图那么大,所以给封顶之前的原始尺寸);
      //: 读出来之前那一格是 "—",不是谎称的 1024 占位。
      setReadout((previous) => ({
        ...previous,
        size: size ? { width: size.width, height: size.height } : { width: DEFAULT_DOC, height: DEFAULT_DOC },
      }));
    })();
    return () => {
      alive = false;
    };
  }, [open, source?.assetId, initial?.assetId, rebuild]);

  /**
   * 缩放:以屏幕上某一点为锚(滚轮、捏合是指针所在,按钮和快捷键是画布中心)。
   * 只改相机 —— 蒙版一个像素都不动。
   */
  const zoomBy = React.useCallback(
    (factor: number, anchor?: Point) => {
      const camera = cameraRef.current;
      const box = boxRef.current;
      if (!camera || !box) return;
      setCamera(zoomAround(camera, factor, anchor ?? { x: box.width / 2, y: box.height / 2 }, writer().size, box), false);
      paint();
    },
    [paint, setCamera],
  );

  const fitView = () => {
    const box = boxRef.current;
    if (!box) return;
    setCamera(fitCamera(doc(), box), true);
    paint();
  };

  /** 100%:一个文档像素一个屏幕像素(CSS),图居中。 */
  const actualPixels = () => {
    const box = boxRef.current;
    if (!box) return;
    setCamera(clampPan(center(doc(), box, 1), doc(), box), false);
    paint();
  };

  /**
   * 盒子一换大小就重量一遍;滚轮 / 捏合挂在画布上(要 `passive: false` 才能拦下页面自己的缩放和滚动,
   * React 的 onWheel 是 passive 的)。
   *
   * **不能在 effect 里直接读 ref**:`<DialogContent>` 是 portal,这一轮 effect 跑的时候 ref 可能还没挂上
   * —— 读到 null 就 return 的话,这一整条永远不会登记。下一帧再登记,那时画布一定在文档里。
   */
  React.useEffect(() => {
    if (!open) return;
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => refresh());
    let attached: HTMLCanvasElement | null = null;
    const local = (event: { clientX: number; clientY: number }): Point | undefined => {
      const rect = attached?.getBoundingClientRect();
      if (!rect || !Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) return undefined;
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const wheel = (event: WheelEvent) => {
      const camera = cameraRef.current;
      const box = boxRef.current;
      //: 预览里也不让滚轮把外面的页面缩放 / 滚走。
      event.preventDefault();
      if (!camera || !box || gestureRef.current !== null) return;
      const intent = wheelIntent(event, modeRef.current, box.height);
      if (!intent) return;
      if (intent.kind === "zoom") {
        zoomBy(intent.factor, local(event));
        return;
      }
      setCamera(panBy(camera, intent.dx, intent.dy, writer().size, box), false);
      paint();
    };
    //: WebKit 把捏合给成 gesture 事件,而不是 Chromium 那种带 ctrlKey 的滚轮。
    const gestureStart = (event: Event) => {
      event.preventDefault();
      gestureRef.current = 1;
    };
    const gestureChange = (event: Event) => {
      event.preventDefault();
      const gesture = event as Event & { scale: number; clientX: number; clientY: number };
      const previous = gestureRef.current;
      if (previous === null || !Number.isFinite(gesture.scale) || gesture.scale <= 0) return;
      zoomBy(gesture.scale / previous, local(gesture));
      gestureRef.current = gesture.scale;
    };
    const gestureEnd = (event: Event) => {
      event.preventDefault();
      gestureRef.current = null;
    };
    const frame = requestAnimationFrame(() => {
      attached = viewRef.current;
      if (!attached) return;
      observer?.observe(attached);
      attached.addEventListener("wheel", wheel, { passive: false });
      attached.addEventListener("gesturestart", gestureStart, { passive: false });
      attached.addEventListener("gesturechange", gestureChange, { passive: false });
      attached.addEventListener("gestureend", gestureEnd, { passive: false });
    });
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      attached?.removeEventListener("wheel", wheel);
      attached?.removeEventListener("gesturestart", gestureStart);
      attached?.removeEventListener("gesturechange", gestureChange);
      attached?.removeEventListener("gestureend", gestureEnd);
    };
  }, [open, refresh, zoomBy, paint, setCamera]);

  /** 记一步。`kind` 相同就**并进上一步** —— 阈值滑块拖一下午不该攒出两百步撤销。 */
  const pushHistory = (kind: string | null) => {
    const snap = snapshot();
    if (!snap) return;
    const history = historyRef.current;
    const coalesce = kind !== null && kind === lastStepRef.current && history.at > 0;
    const steps = history.steps.slice(0, history.at + 1);
    if (coalesce) steps[steps.length - 1] = snap;
    else steps.push(snap);
    const bytes = steps[0]?.length ?? 0;
    while (steps.length > 1 && (steps.length > HISTORY_LIMIT || steps.length * bytes > HISTORY_BYTES)) steps.shift();
    historyRef.current = { steps, at: steps.length - 1 };
    lastStepRef.current = kind;
    syncHistory();
  };

  /**
   * 把一份单通道快照写回蒙版。**尺寸对不上就整张不动**(写入口 `MaskContext.restore` 管):
   * `createImageData` 是零填充的,差一个像素剩下的就全是 `alpha 0` —— 屏幕上整块被蒙版色糊住,
   * 导出的 PNG 带上 alpha,插件那条路静默什么都不重绘。
   */
  const restore = (channel: Uint8ClampedArray) => {
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

  /** 取像素 → 调纯函数 → **整张**写回,一步(反选、应用边缘都走它)。 */
  const transform = (run: (data: MaskPixels, size: Size) => void) => {
    const ctx = maskContext();
    if (!ctx) return;
    const image = ctx.read();
    run(image.data, { ...ctx.size });
    ctx.write(image);
    pushHistory(null);
    paint();
  };

  /** 清空 = 整张铺黑(= "这块不改",和橡皮写进去的是同一个值)。只碰蒙版那一张。 */
  const clear = () => {
    const ctx = maskContext();
    if (!ctx) return;
    ctx.clear();
    pushHistory(null);
    paint();
  };

  const invert = () => transform((data) => invertMask(data));

  /**
   * 「应用到蒙版」:先扩张 / 收缩、再羽化,作用在整张蒙版上,一步撤销(ADR 0057 决定 3)。
   * 次序和后端配方一样(`contracts/mask-cases.json` 的 pipeline),两侧的结果逐字节相同。
   */
  const applyEdges = () =>
    transform((data, size) => {
      growMask(data, size.width, size.height, grow);
      featherMask(data, size.width, size.height, feather);
    });

  /**
   * 从底图起手:底图像素复制一份 → 阈值二值化 → 变成初笔迹。
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
    //: 先写进一张和底图同尺寸的画布,再铺到文档上 —— 两者尺寸不同(底图超过 4096)时也不会错位。
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

  /** 指针在画布元素上的位置(CSS 像素)。 */
  const localPoint = (event: React.PointerEvent<HTMLCanvasElement>): Point | null => {
    const view = viewRef.current;
    if (!view) return null;
    const rect = view.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  /** 指针落在文档的哪一点 —— 透过相机换算(放大、平移之后照样落在对的像素上)。 */
  const docPoint = (event: React.PointerEvent<HTMLCanvasElement>): Point | null => {
    const local = localPoint(event);
    if (!local) return null;
    const camera = cameraRef.current;
    if (camera) return toDoc(camera, local);
    //: 还没量到盒子(没有相机):整张画布当文档。
    const rect = (viewRef.current as HTMLCanvasElement).getBoundingClientRect();
    const { width, height } = doc();
    return { x: (local.x / rect.width) * width, y: (local.y / rect.height) * height };
  };

  /** 笔刷那个圈:屏幕上的真实大小(直径 × 相机缩放),只有画笔和橡皮有。 */
  const moveRing = (event: React.PointerEvent<HTMLCanvasElement> | null) => {
    const ring = ringRef.current;
    if (!ring) return;
    const local = event ? localPoint(event) : null;
    const camera = cameraRef.current;
    const freehand = tool === "brush" || tool === "eraser";
    if (!local || !camera || !freehand || panMode !== "off") {
      ring.hidden = true;
      return;
    }
    const diameter = Math.max(4, brushSize * camera.scale);
    ring.hidden = false;
    ring.style.width = `${diameter}px`;
    ring.style.height = `${diameter}px`;
    ring.style.transform = `translate(${local.x - diameter / 2}px, ${local.y - diameter / 2}px)`;
  };

  /** 一笔的墨:笔刷写白(要改)、橡皮写黑(不改)。见文件头「橡皮 = 写黑」。 */
  const inkOf = (kind: Tool) => (kind === "brush" ? { ink: WHITE, fade: FADE_WHITE } : { ink: BLACK, fade: FADE_BLACK });

  const capture = (event: React.PointerEvent<HTMLCanvasElement>) => {
    //: 指针捕获在合成事件 / 某些设备上是会抛的。它只是"指针滑出画布也算数"的便利,抛了不该让这一笔断掉。
    try {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    } catch {
      //: 拿不到就算了,拖动照旧。
    }
  };

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    //: 中键,或按着空格的左键:平移相机,不画。
    if (event.button === 1 || (event.button === 0 && spaceRef.current)) {
      event.preventDefault();
      capture(event);
      panRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
      setPanMode("dragging");
      moveRing(null);
      return;
    }
    if (event.button !== 0) return;
    const ctx = maskContext();
    const at = docPoint(event);
    if (!ctx || !at) return;
    capture(event);
    drawingRef.current = true;
    const freehand = tool === "brush" || tool === "eraser";
    dragRef.current = { tool, from: at, last: at, before: freehand ? null : snapshot(), pressed: { ...doc() } };
    if (freehand) {
      const { ink, fade } = inkOf(tool);
      ctx.stroke((raw) => paintLine(raw, at, at, brushSize / 2, hardness, ink, fade));
    } else {
      ctx.beginStroke();
      ctx.preview((raw) => paintShape(raw, tool, at, at));
    }
    paint();
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const pan = panRef.current;
    if (pan) {
      const camera = cameraRef.current;
      const box = boxRef.current;
      if (camera && box) setCamera(panBy(camera, event.clientX - pan.x, event.clientY - pan.y, doc(), box), false);
      pan.x = event.clientX;
      pan.y = event.clientY;
      paint();
      return;
    }
    moveRing(event);
    const drag = dragRef.current;
    const ctx = maskContext();
    if (!drag || !ctx) return;
    const at = docPoint(event);
    if (!at) return;
    //: **按下之后底图才读进来**(rebuild 把文档换了尺寸)的话,`from` / `last` 还是旧坐标系的
    //: —— 按新旧尺寸比搬过来(carry 就是把旧画布按同一个比缩进新文档的,笔迹几何跟着同一个比走),
    //: 否则这一笔从旧空间的点划到新空间的点,横跨整张图落在错位的地方。形状工具那份「按下之前的
    //: 像素」快照同时候作废:重取一份当前的,否则 `restore` 会把整张挡掉(它拒绝写尺寸对不上的
    //: 快照),预览就从「每帧重来」变成「一层层叠」。
    const sizeNow = doc();
    if (drag.pressed.width !== sizeNow.width || drag.pressed.height !== sizeNow.height) {
      const scaleX = sizeNow.width / drag.pressed.width;
      const scaleY = sizeNow.height / drag.pressed.height;
      drag.from = { x: drag.from.x * scaleX, y: drag.from.y * scaleY };
      drag.last = { x: drag.last.x * scaleX, y: drag.last.y * scaleY };
      drag.pressed = { ...sizeNow };
      if (drag.before) {
        drag.before = snapshot();
        ctx.beginStroke();
      }
    }
    if (drag.tool === "brush" || drag.tool === "eraser") {
      const { ink, fade } = inkOf(drag.tool);
      ctx.stroke((raw) => paintLine(raw, drag.last, at, brushSize / 2, hardness, ink, fade));
    } else {
      //: 形状工具每一帧都从按下时那份像素重来:看到的是「松手后会是这样」,不是一层层叠上去的边。
      ctx.preview((raw) => paintShape(raw, drag.tool, drag.from, at));
    }
    drag.last = at;
    paint();
  };

  const onPointerUp = () => {
    if (panRef.current) {
      panRef.current = null;
      setPanMode(spaceRef.current ? "ready" : "off");
      return;
    }
    drawingRef.current = false;
    maskContext()?.endStroke();
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    //: 形状工具**点一下没拖**(一个 0×0 的框)不算一步:撤销栈里不该多出一条看不出变化的记录。
    const painted =
      drag.tool === "brush" || drag.tool === "eraser" || drag.last.x !== drag.from.x || drag.last.y !== drag.from.y;
    if (painted) pushHistory(null);
  };

  /** 笔刷大小一档:小笔刷细调、大笔刷粗调(按当前大小的一成半,至少 1)。 */
  const nudgeBrush = (direction: 1 | -1) =>
    setBrushSize((size) => Math.min(BRUSH_MAX, Math.max(BRUSH_MIN, size + direction * Math.max(1, Math.round(size * 0.15)))));

  /**
   * 快捷键。挂在弹窗上(焦点在弹窗里的任何地方都认),但焦点在能打字的地方时一律让路。
   * 空格只在指针停在画布上时接管 —— 不然空格还是「按下焦点所在的那颗按钮」。
   */
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (isTypingTarget(event.target)) return;
    const key = event.key.toLowerCase();
    if (event.metaKey || event.ctrlKey) {
      if (key === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if (key === "y") {
        event.preventDefault();
        redo();
      }
      return;
    }
    if (event.altKey) return;
    if (key === " ") {
      if (!hoverRef.current && !panRef.current) return;
      event.preventDefault();
      if (!spaceRef.current) {
        spaceRef.current = true;
        setPanMode(panRef.current ? "dragging" : "ready");
        if (ringRef.current) ringRef.current.hidden = true;
      }
      return;
    }
    const nextTool = TOOL_KEYS[key];
    if (nextTool) setTool(nextTool);
    else if (key === "[") nudgeBrush(-1);
    else if (key === "]") nudgeBrush(1);
    else if (key === "0") fitView();
    else if (key === "1") actualPixels();
    else if (key === "=" || key === "+") zoomBy(ZOOM_STEP);
    else if (key === "-") zoomBy(1 / ZOOM_STEP);
    else return;
    event.preventDefault();
  };

  const onKeyUp = (event: React.KeyboardEvent) => {
    if (event.key !== " " || !spaceRef.current) return;
    event.preventDefault();
    spaceRef.current = false;
    if (!panRef.current) setPanMode("off");
  };

  const close = () => {
    //: 上传中途关掉 = 不等它了(savePaintedMask 收了 signal)。
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
      //: 名字、出处、归一(红通道、去 alpha、缩放到源图尺寸)都是后端那个写出口的事(ADR 0057 决定 2)。
      savePaintedMask({
        workspaceId,
        sourceAssetId: source?.assetId,
        file: new File([blob], MASK_FILE_NAME, { type: "image/png" }),
        signal: controller.signal,
      })
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

  const tools: { value: Tool; label: string; key: string; icon: React.ReactNode }[] = [
    { value: "brush", label: t("maskBrush"), key: "B", icon: <Brush /> },
    { value: "eraser", label: t("maskEraser"), key: "E", icon: <Eraser /> },
    { value: "rect", label: t("maskRect"), key: "R", icon: <Square /> },
    { value: "ellipse", label: t("maskEllipse"), key: "O", icon: <Circle /> },
  ];
  const edgesIdle = grow === 0 && feather === 0;
  const zoomText = readout.zoom === null ? "—" : `${Math.round(readout.zoom * 100)}%`;
  const cursor =
    panMode === "dragging" ? "cursor-grabbing" : panMode === "ready" ? "cursor-grab" : "cursor-crosshair";

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent
        //: 接近全屏:画布占满主体(左),参数一栏(右,md 档),底栏横跨两列(尺寸与缩放 | 取消、存成蒙版)。
        //: 第一列 `minmax(0,1fr)`:画布再怎么宽也顶不开右栏(见 CONVENTIONS「单列 grid 想收缩要写 minmax(0,1fr)」)。
        className="h-[min(880px,calc(100dvh-32px))] max-h-[calc(100dvh-32px)] w-[min(1320px,calc(100vw-32px))] max-w-none grid-cols-[minmax(0,1fr)_19rem] grid-rows-[minmax(0,1fr)_auto] gap-0 overflow-hidden p-0"
        onKeyDown={onKeyDown}
        onKeyUp={onKeyUp}
      >
        {/*
          * 画布区:浮动工具条在上(它是 `CanvasToolbar`,和画板、工作流同一种),下面是画布。
          * 画布元素铺满它那一格,文档透过相机画在里面 —— 四周的留白是画布区自己的底色,
          * 图的四条边由跟着相机走的那个边框画出来。
          */}
        <div className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-3 bg-panel-inset p-3">
          <CanvasToolbar label={t("maskToolbar")} className="justify-self-center">
            <CanvasToolbarGroup label={t("maskTool")}>
              {tools.map((one) => (
                <IconButton
                  key={one.value}
                  label={one.label}
                  shortcut={one.key}
                  aria-pressed={tool === one.value}
                  onClick={() => setTool(one.value)}
                >
                  {one.icon}
                </IconButton>
              ))}
            </CanvasToolbarGroup>
            <CanvasToolbarGroup label={t("maskHistory")}>
              <IconButton
                label={t("maskUndo")}
                shortcut={formatCombo("Mod+Z")}
                disabled={!canUndo}
                disabledReason={t("nothingToUndo")}
                onClick={undo}
              >
                <Undo2 />
              </IconButton>
              <IconButton
                label={t("maskRedo")}
                shortcut={formatCombo("Mod+Shift+Z")}
                disabled={!canRedo}
                disabledReason={t("nothingToRedo")}
                onClick={redo}
              >
                <Redo2 />
              </IconButton>
            </CanvasToolbarGroup>
            <CanvasToolbarGroup label={t("maskWholeMask")}>
              <IconButton label={t("maskInvert")} onClick={invert}>
                <Contrast />
              </IconButton>
              <IconButton label={t("maskClear")} onClick={clear}>
                <Trash />
              </IconButton>
            </CanvasToolbarGroup>
            <CanvasToolbarGroup label={t("maskView")}>
              <IconButton label={t("maskZoomOut")} shortcut="-" onClick={() => zoomBy(1 / ZOOM_STEP)}>
                <ZoomOut />
              </IconButton>
              <IconButton label={t("maskZoomIn")} shortcut="+" onClick={() => zoomBy(ZOOM_STEP)}>
                <ZoomIn />
              </IconButton>
              <IconButton label={t("maskZoomFit")} shortcut="0" onClick={fitView}>
                <Maximize2 />
              </IconButton>
              <IconButton label={t("maskZoomActual")} shortcut="1" size="sm" className="tabular-nums" onClick={actualPixels}>
                100%
              </IconButton>
              <CanvasInputModeSwitch />
            </CanvasToolbarGroup>
          </CanvasToolbar>

          <div className="relative min-h-0 min-w-0 overflow-hidden">
            <canvas
              ref={viewRef}
              className={`block h-full w-full touch-none ${cursor}`}
              aria-label={t("maskCanvasLabel")}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              onPointerEnter={() => {
                hoverRef.current = true;
              }}
              onPointerLeave={() => {
                hoverRef.current = false;
                moveRing(null);
              }}
              onAuxClick={(event) => event.preventDefault()}
            />
            {/*: 文档的边框与笔刷圈:纯显示,不接指针(事件全落在画布上)。位置由相机写(placeFrame / moveRing)。 */}
            <div
              ref={frameRef}
              data-mask-doc-frame=""
              hidden
              aria-hidden
              className="pointer-events-none absolute left-0 top-0 origin-top-left rounded-[1px] outline outline-1 outline-border-strong shadow-[var(--shadow-panel)]"
            />
            <div
              ref={ringRef}
              hidden
              aria-hidden
              className="pointer-events-none absolute left-0 top-0 rounded-full border border-white shadow-[0_0_0_1px_rgb(0_0_0/0.55)]"
            />
          </div>
        </div>

        {/*
          * 参数一栏(md 档):标题与说明在顶上,四节按「画笔 / 边缘 / 从底图起手 / 显示」分组。
          * 两个轴一起锁 —— 只写 `grid-rows` 的话隐式列按 max-content 定尺,右栏会被内容顶宽
          * (见 design/gridAxes.test.ts 那条棘轮)。
          */}
        <aside className="grid min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] border-l border-divider">
          <div className="grid gap-1 px-5 pb-4 pr-12 pt-5">
            <DialogTitle className="text-ui-md">{t("maskEditorTitle")}</DialogTitle>
            <DialogDescription className="m-0 text-ui-xs">{t("maskEditorHint")}</DialogDescription>
          </div>
          <div className="grid min-h-0 content-start gap-5 overflow-y-auto px-5 pb-5">
            <PanelSection label={t("maskBrushGroup")}>
              <SliderField
                label={t("maskBrushSize")}
                value={brushSize}
                min={BRUSH_MIN}
                max={BRUSH_MAX}
                step={1}
                format={pixels}
                onChange={setBrushSize}
              />
              <SliderField label={t("maskBrushHardness")} value={hardness} min={0} max={1} step={0.05} format={percent} onChange={setHardness} />
            </PanelSection>

            <PanelSection label={t("maskEdges")}>
              <SliderField label={t("maskGrow")} value={grow} min={-EDGE_MAX} max={EDGE_MAX} step={1} format={signedPixels} onChange={setGrow} />
              <SliderField label={t("maskFeather")} value={feather} min={0} max={EDGE_MAX} step={1} format={pixels} onChange={setFeather} />
              <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("maskEdgesHint")}</p>
              <Button variant="outline" className="w-full" disabled={edgesIdle} onClick={applyEdges}>
                <Wand2 />
                {t("maskApplyEdges")}
              </Button>
            </PanelSection>

            <PanelSection label={t("maskFromSource")}>
              <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("maskFromSourceHint")}</p>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" disabled={!hasUnderlay} onClick={() => pressFromSource("luminance")}>
                  <SunMedium />
                  {t("maskFromLuminance")}
                </Button>
                <Button variant="outline" disabled={!hasUnderlay} onClick={() => pressFromSource("alpha")}>
                  <Droplets />
                  {t("maskFromAlpha")}
                </Button>
              </div>
              <SliderField label={t("maskThreshold")} value={threshold} min={0} max={1} step={0.01} format={percent} onChange={changeThreshold} />
            </PanelSection>

            <PanelSection label={t("maskDisplay")}>
              {/*: `role="switch"` 自己挂 aria-label:套在 `<label>` 里读屏名字会是「显示底图 开关」。 */}
              <div className="flex items-center justify-between gap-3">
                <span className="min-w-0 text-ui-sm text-foreground">{t("maskShowSource")}</span>
                <Switch aria-label={t("maskShowSource")} checked={showUnderlay} onCheckedChange={setShowUnderlay} />
              </div>
            </PanelSection>
          </div>
        </aside>

        {/*
          * 底栏横跨两列:左边是输出尺寸、缩放和操作提示,右边是取消与唯一的主动作「存成蒙版」。
          */}
        <footer className="col-span-2 flex min-w-0 items-center gap-4 border-t border-divider px-5 py-3">
          <div className="flex min-w-0 flex-1 items-center gap-3 text-ui-xs text-muted-foreground">
            <span className="shrink-0 tabular-nums text-foreground">
              {readout.size ? `${readout.size.width} × ${readout.size.height} px` : "—"}
            </span>
            <span className="shrink-0 tabular-nums" aria-label={t("maskZoomLevel")}>
              {zoomText}
            </span>
            <span className="hidden min-w-0 lg:inline">{t("maskNavigationHint")}</span>
          </div>
          {failure && <FailureCard size="inline" className="max-w-sm" title={t("maskSaveFailed")} summary={failure} copyText={failure} />}
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" onClick={close}>
              {t("cancel")}
            </Button>
            <Button loading={saving} onClick={save}>
              <Check />
              {t("maskSave")}
            </Button>
          </div>
        </footer>
      </DialogContent>
    </Dialog>
  );
}

/**
 * 参数栏里的一节:**同一层级的小标题** + 内容。节与节之间只有这一处节奏:一条 1px 分隔线 + 同一段上留白。
 * 分隔线画在**后一节自己身上**(`border-t`),不插独立的 `<hr>` —— 条件渲染的那一节一走开就不会多一条空线。
 */
function PanelSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-3 border-t border-divider pt-5 first:border-t-0 first:pt-0">
      <h3 className="m-0 text-ui-xs font-semibold text-muted-foreground">{label}</h3>
      <div className="grid gap-3">{children}</div>
    </section>
  );
}

/**
 * 一根滑块 + 名字 + 当前值:名字、控件、右值各占固定的一列(名字 5rem,值 4rem 等宽数字),
 * 几行对成一条竖线。名字和值都**不截断**:放不下就折行。
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
    <label className="grid grid-cols-[5rem_minmax(0,1fr)_4rem] items-center gap-x-3 text-ui-sm text-foreground">
      <span className="min-w-0">{label}</span>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={([next]) => onChange(next)} />
      <span className="text-right text-ui-xs tabular-nums text-muted-foreground">{format ? format(value) : String(value)}</span>
    </label>
  );
}

const percent = (value: number) => `${Math.round(value * 100)}%`;
const pixels = (value: number) => `${Math.round(value)} px`;
const signedPixels = (value: number) => (value > 0 ? `+${Math.round(value)} px` : value < 0 ? `−${Math.abs(Math.round(value))} px` : "0 px");
