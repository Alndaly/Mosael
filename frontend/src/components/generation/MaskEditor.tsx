import * as React from "react";
import { Brush, Check, Circle, Contrast, Droplets, Eraser, Feather, Redo2, Square, SunMedium, Trash, Undo2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { assetPreviewUrl, importAsset, type Asset } from "@/api/domains/assets";
import { errorText } from "@/api/errorMessage";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { FailureCard } from "@/components/failure/FailureCard";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { Segmented } from "@/components/ui/segmented";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  alphaMask,
  featherMask,
  grayscaleOf,
  invertMask,
  thresholdMask,
  writeGrayscale,
  type MaskPixels,
} from "@/lib/maskPixels";

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
 * | 底图 | 只在看得见的这张上,半透明 | 要改的那张原图 —— **导出的蒙版里永远没有它** |
 * | 蒙版(离屏) | 不进 DOM,和底图一样大 | 黑白笔迹。笔画累积在它上面,**导出的也是它** |
 * | 可见的那张 | 对话框里 | 底图 + 蒙版,按容器等比缩放到看得见的大小(devicePixelRatio 感知) |
 *
 * 三张分开是为了让「导出」这件事没有任何条件:导出的那张画布上从来没有底图,也不需要重新合成一遍。
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
 */

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
const TAU = Math.PI * 2;
const BLACK = "#000000";
const WHITE = "#ffffff";
/** 软边渐变的外圈。画布是不透明的,所以"往回混"就够了,不需要 destination-out。 */
const FADE_WHITE = "rgba(255, 255, 255, 0)";
const FADE_BLACK = "rgba(0, 0, 0, 0)";
/** 底图当参考时的透明度:看得清位置,又不至于和白色笔迹抢眼。 */
const UNDERLAY_ALPHA = 0.45;
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
  /** 看得见的那张画布(底图 + 蒙版,只给人看)。 */
  const viewRef = React.useRef<HTMLCanvasElement>(null);
  /** 画布外面那个盒子:按它算等比适配。 */
  const boxRef = React.useRef<HTMLDivElement>(null);
  /** 蒙版本身 —— 离屏、不进 DOM、导出的就是它。 */
  const maskRef = React.useRef<HTMLCanvasElement | null>(null);
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

  const doc = React.useRef<Size>({ width: DEFAULT_DOC, height: DEFAULT_DOC });
  const showUnderlayRef = React.useRef(showUnderlay);

  const maskContext = () => maskRef.current?.getContext("2d") ?? null;

  const syncHistory = () => {
    const { steps, at } = historyRef.current;
    setCanUndo(at > 0);
    setCanRedo(at >= 0 && at < steps.length - 1);
  };

  /** 当前蒙版的单通道快照(存撤销栈用)。 */
  const snapshot = (): Uint8ClampedArray | null => {
    const ctx = maskContext();
    if (!ctx) return null;
    const { width, height } = doc.current;
    return grayscaleOf(ctx.getImageData(0, 0, width, height).data);
  };

  /**
   * 把蒙版画到看得见的那张画布上:底图(半透明)在下面,蒙版在上面。
   *
   * 只读 ref —— 所以这个函数在整个生命周期里是同一个,几个 effect 不会因为它的身份变化而重跑。
   */
  const paint = React.useCallback(() => {
    const view = viewRef.current;
    const ctx = view?.getContext("2d") ?? null;
    if (!view || !ctx) return;
    ctx.clearRect(0, 0, view.width, view.height);
    const underlay = underlayRef.current;
    if (underlay?.image && showUnderlayRef.current) {
      ctx.globalAlpha = UNDERLAY_ALPHA;
      ctx.drawImage(underlay.image, 0, 0, view.width, view.height);
      ctx.globalAlpha = 1;
    }
    const mask = maskRef.current;
    if (mask) ctx.drawImage(mask, 0, 0, view.width, view.height);
  }, []);

  /** 按容器等比适配:整张图看得见,不缩放也不平移(第一版不做那两件事)。 */
  const fit = React.useCallback(() => {
    const box = boxRef.current;
    const view = viewRef.current;
    if (!box || !view) return;
    const { width, height } = doc.current;
    const scale = Math.min(box.clientWidth / width, box.clientHeight / height);
    //: jsdom 里量出来是 0(没有版面);真实环境里也可能是对话框刚挂上、还没量到的那一帧。
    if (!Number.isFinite(scale) || scale <= 0) return;
    const ratio = window.devicePixelRatio || 1;
    const shown = { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
    view.style.width = `${shown.width}px`;
    view.style.height = `${shown.height}px`;
    view.width = Math.round(shown.width * ratio);
    view.height = Math.round(shown.height * ratio);
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
      const previous = maskRef.current;
      const canvas = document.createElement("canvas");
      canvas.width = next.width;
      canvas.height = next.height;
      maskRef.current = canvas;
      doc.current = next;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        //: 黑底不是装饰:导出的 PNG 要每个像素都不透明(带 alpha 的图在插件那条路上读出来是空的)。
        ctx.fillStyle = BLACK;
        ctx.fillRect(0, 0, next.width, next.height);
        const draft = draftRef.current;
        if (draft) {
          //: 底稿铺满整张文档(尺寸不一致时缩放):继续画的就是它。
          ctx.drawImage(draft, 0, 0, next.width, next.height);
        } else if (carry && previous && (previous.width !== next.width || previous.height !== next.height)) {
          ctx.drawImage(previous, 0, 0, next.width, next.height);
        }
      }
      const first = snapshot();
      historyRef.current = first ? { steps: [first], at: 0 } : { steps: [], at: -1 };
      lastStepRef.current = null;
      syncHistory();
      fit();
    },
    [fit],
  );

  //: 「显示底图」是个纯显示开关:它只重画看得见的那张,不碰撤销栈、不重铺文档。
  React.useEffect(() => {
    showUnderlayRef.current = showUnderlay;
    if (open) paint();
  }, [open, showUnderlay, paint]);

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

  /** 按容器大小重排 —— 对话框尺寸变了(用户拖窗口)也能整张看见。 */
  React.useEffect(() => {
    if (!open) return;
    const box = boxRef.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => fit());
    observer.observe(box);
    return () => observer.disconnect();
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

  const restore = (channel: Uint8ClampedArray) => {
    const ctx = maskContext();
    if (!ctx) return;
    const { width, height } = doc.current;
    const image = ctx.createImageData(width, height);
    writeGrayscale(channel, image.data);
    ctx.putImageData(image, 0, 0);
    paint();
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

  /** 取像素 → 调纯函数 → 写回,一步(反选、羽化都走它)。 */
  const transform = (run: (data: MaskPixels, size: Size) => void) => {
    const ctx = maskContext();
    if (!ctx) return;
    const size = { ...doc.current };
    const image = ctx.getImageData(0, 0, size.width, size.height);
    run(image.data, size);
    ctx.putImageData(image, 0, 0);
    pushHistory(null);
    paint();
  };

  const clear = () => {
    const ctx = maskContext();
    if (!ctx) return;
    const { width, height } = doc.current;
    ctx.fillStyle = BLACK;
    ctx.fillRect(0, 0, width, height);
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
    const { width, height } = doc.current;
    ctx.fillStyle = BLACK;
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(scratch, 0, 0, width, height);
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
    const { width, height } = doc.current;
    return {
      x: ((event.clientX - rect.left) / rect.width) * width,
      y: ((event.clientY - rect.top) / rect.height) * height,
    };
  };

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const ctx = maskContext();
    const at = docPoint(event);
    if (!ctx || !at) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const freehand = tool === "brush" || tool === "eraser";
    dragRef.current = { tool, from: at, last: at, before: freehand ? null : snapshot() };
    if (freehand) {
      paintLine(ctx, at, at, radius / 2, hardness, tool === "brush" ? WHITE : BLACK, tool === "brush" ? FADE_WHITE : FADE_BLACK);
    } else {
      paintShape(ctx, tool, at, at);
    }
    paint();
  };

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    const ctx = maskContext();
    const at = docPoint(event);
    if (!drag || !ctx || !at) return;
    if (drag.tool === "brush" || drag.tool === "eraser") {
      paintLine(
        ctx,
        drag.last,
        at,
        radius / 2,
        hardness,
        drag.tool === "brush" ? WHITE : BLACK,
        drag.tool === "brush" ? FADE_WHITE : FADE_BLACK,
      );
    } else {
      //: 形状工具每一帧都从按下时那份像素重来:看到的是「松手后会是这样」,不是一层层叠上去的边。
      if (drag.before) restore(drag.before);
      paintShape(ctx, drag.tool, drag.from, at);
    }
    drag.last = at;
    paint();
  };

  const onPointerUp = () => {
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
    const canvas = maskRef.current;
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
        //: 全屏尺寸的弹窗:画布要尽可能大,底图和笔迹才看得清。网格三段(头 / 画布+工具条 / 尾)。
        className="w-[min(1180px,calc(100vw-32px))] max-w-none h-[min(820px,calc(100dvh-32px))] max-h-[calc(100dvh-32px)] grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto] gap-4 overflow-hidden p-5"
      >
        <DialogHeader>
          <DialogTitle>{t("maskEditorTitle")}</DialogTitle>
          <DialogDescription>{t("maskEditorHint")}</DialogDescription>
        </DialogHeader>

        <div className="grid min-h-0 grid-cols-[minmax(0,1fr)_16rem] gap-4">
          {/*: 看得见的画布:底图(半透明)+ 蒙版。导出的不是这一张 —— 见文件头那三张画布。 */}
          <div ref={boxRef} className="grid min-h-0 place-items-center overflow-hidden rounded-lg border border-border bg-black">
            <canvas
              ref={viewRef}
              className="max-h-full max-w-full cursor-crosshair touch-none"
              aria-label={t("maskCanvasLabel")}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            />
          </div>

          <div className="grid min-h-0 content-start gap-4 overflow-y-auto pr-1">
            <ToolGroup label={t("maskTool")}>
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
              <SliderField label={t("maskBrushSize")} value={radius} min={2} max={200} step={1} onChange={setRadius} />
              <SliderField
                label={t("maskBrushHardness")}
                value={hardness}
                min={0}
                max={1}
                step={0.05}
                format={percent}
                onChange={setHardness}
              />
              <div className="flex items-center gap-1">
                <IconButton label={t("maskUndo")} disabled={!canUndo} onClick={undo}>
                  <Undo2 />
                </IconButton>
                <IconButton label={t("maskRedo")} disabled={!canRedo} onClick={redo}>
                  <Redo2 />
                </IconButton>
                <IconButton label={t("maskClear")} onClick={clear}>
                  <Trash />
                </IconButton>
                <IconButton label={t("maskInvert")} onClick={invert}>
                  <Contrast />
                </IconButton>
              </div>
            </ToolGroup>

            <ToolGroup label={t("maskFeather")}>
              <SliderField label={t("maskFeatherRadius")} value={feather} min={1} max={64} step={1} format={pixels} onChange={setFeather} />
              <Button variant="outline" size="sm" onClick={applyFeather}>
                <Feather />
                {t("maskFeather")}
              </Button>
            </ToolGroup>

            <ToolGroup label={t("maskFromSource")}>
              {/*: 底图读到之前按了也没用 —— 说清楚为什么,而不是只灰掉。 */}
              <span className="text-ui-xs leading-relaxed text-muted-foreground">{t("maskFromSourceHint")}</span>
              <Button
                variant="outline"
                size="sm"
                className="justify-start"
                disabled={!hasUnderlay}
                onClick={() => pressFromSource("luminance")}
              >
                <SunMedium />
                {t("maskFromLuminance")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="justify-start"
                disabled={!hasUnderlay}
                onClick={() => pressFromSource("alpha")}
              >
                <Droplets />
                {t("maskFromAlpha")}
              </Button>
              <SliderField label={t("maskThreshold")} value={threshold} min={0} max={1} step={0.01} format={percent} onChange={changeThreshold} />
              <label className="flex items-center gap-2 text-ui-xs font-semibold text-muted-foreground">
                <Switch checked={showUnderlay} onCheckedChange={setShowUnderlay} />
                {/*: 底图只是参考 —— 导出的是纯黑底 + 白笔迹,没有它。 */}
                <span>{t("maskShowSource")}</span>
              </label>
            </ToolGroup>
          </div>
        </div>

        <DialogFooter className="items-center gap-2">
          {/*: 失败展示全应用只有一份(components/failure):这里用一行档,不自己写一行红字。 */}
          {failure && (
            <FailureCard
              size="inline"
              className="mr-auto max-w-[28rem]"
              title={t("maskSaveFailed")}
              summary={failure}
              copyText={failure}
            />
          )}
          <Button variant="outline" onClick={close}>
            {t("cancel")}
          </Button>
          <Button loading={saving} onClick={save}>
            <Check />
            {t("maskSave")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 工具条里的一组:一行小标题 + 内容。 */
function ToolGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <span className="text-ui-xs font-semibold text-foreground">{label}</span>
      {children}
    </div>
  );
}

/** 一根滑块 + 当前值。 */
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
    <div className="grid gap-1">
      <div className="flex items-center justify-between gap-2 text-ui-xs text-muted-foreground">
        <span>{label}</span>
        <span className="tabular-nums">{format ? format(value) : String(value)}</span>
      </div>
      <Slider value={[value]} min={min} max={max} step={step} onValueChange={([next]) => onChange(next)} />
    </div>
  );
}

const percent = (value: number) => `${Math.round(value * 100)}%`;
const pixels = (value: number) => `${Math.round(value)} px`;
