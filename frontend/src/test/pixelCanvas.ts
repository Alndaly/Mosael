/**
 * 一份**真的会算像素**的 canvas 2D 替身(jsdom 里没有 canvas 2D)。
 *
 * ## 为什么要它,而不是"记下被调用过什么"
 *
 * 既有那批用例的替身只记 `fillRect` / `drawImage` 这些**调用**,像素一律给全 0 —— 于是
 * 「清空之后底图还在不在」「撤销之后蒙版有没有透明像素」这类问题**一条也测不出来**:它们恰恰是
 * 像素层面的(维护者报的那一族的成因就是蒙版里漏出 alpha 0)。这里按规范把那几条合成算出来:
 *
 * - `drawImage` 源画布 → 目标矩形(缩放按最近邻,和探针里读单点的口径一致);
 * - `globalCompositeOperation` = `source-over` / `difference` / `multiply` / `lighter`;
 * - `globalAlpha`;
 * - `putImageData` / `getImageData`(`putImageData` 按它自己的矩形写,不缩放 —— 和浏览器一样)。
 *
 * 它是**测试专用的平台替身**:生产代码一行都不为它改。浮点按 `Math.round` 收口(浏览器的
 * 混合也是在 8 位上算的),够把"底色被保住"和"底色被算没"这两种结果分开。
 */

type Pixels = Uint8ClampedArray;

const CHANNELS = 4;
const clamp255 = (value: number) => (value < 0 ? 0 : value > 255 ? 255 : Math.round(value));

/** `globalCompositeOperation` 里这一份替身认的那几种(Porter-Duff 的 source-over + 三种混合)。 */
type BlendKind = "source-over" | "difference" | "multiply" | "lighter";

function blendKind(operation: GlobalCompositeOperation): BlendKind {
  if (operation === "difference" || operation === "multiply" || operation === "lighter") return operation;
  return "source-over";
}

/** 混合公式的那个 `B(Cb, Cs)`;`source-over` 没有它(就是源色)。 */
function blend(kind: BlendKind, backdrop: number, source: number): number {
  if (kind === "difference") return Math.abs(backdrop - source);
  if (kind === "multiply") return (backdrop * source) / 255;
  if (kind === "lighter") return backdrop + source;
  return source;
}

/** 一个矩形 —— `fillRect` / `drawImage` / `getImageData` 都用它。 */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export class PixelImage {
  readonly data: Pixels;
  constructor(
    readonly width: number,
    readonly height: number,
  ) {
    this.data = new Uint8ClampedArray(width * height * CHANNELS);
  }
}

/**
 * 一张**有像素**的画布。
 *
 * `source()` 给 `drawImage` 用:`canvas` 那种源就是它本身(可直接读),`HTMLImageElement` 那种
 * 由调用方在 `PixelCanvasSource` 的映射里挂一张 `PixelImage` 上去(测试自己造"底图")。
 */
export class PixelCanvas {
  pixels: PixelImage;
  /**
   * 这一张画布的 2D 上下文(**唯一一个**)。
   *
   * 必须是**同一个实例**:测试回头读"这张画布被要求画过什么"(`ctx.calls`)靠的就是它;早先每次
   * `getContext` 都新建一个,于是组件画的那一个和测试读的那一个不是同一个对象 —— 断言看到的永远是空的。
   */
  context: PixelContext2D | null = null;

  constructor(
    public width: number,
    public height: number,
    /** `drawImage` 认的源:HTMLImageElement → 像素。测试自己往里塞。 */
    readonly images = new WeakMap<object, PixelImage>(),
    /** 对应的那个 `<canvas>` 元素 —— 生产的 2D 上下文认的就是它(`ctx.canvas`)。 */
    public readonly element: HTMLCanvasElement | null = null,
  ) {
    this.pixels = new PixelImage(width, height);
  }

  getContext(kind: string): PixelContext2D | null {
    if (kind !== "2d") return null;
    if (!this.context) this.context = new PixelContext2D(this);
    return this.context;
  }

  /** 改尺寸 = 清空整张位图(和浏览器一样)。 */
  resize(width: number, height: number): void {
    this.width = width;
    this.height = height;
    this.pixels = new PixelImage(width, height);
    this.context?.forget();
  }

  /** 一次 `fillRect`。`rect` 可以超出画布(裁到边界)。 */
  fill(rect: Rect, css: string, alpha: number, operation: GlobalCompositeOperation): void {
    const color = parseColor(css);
    const kind = blendKind(operation);
    for (const [x, y] of this.cells(rect)) this.merge(x, y, color, alpha * color.a, kind);
  }

  /** 一次 `drawImage`(九参那种:源刻度到目标矩形)。 */
  draw(target: Rect, source: PixelImage, alpha: number, operation: GlobalCompositeOperation, sourceRect?: Rect): void {
    // eslint-disable-next-line no-console
    if ((globalThis as { __DBGDRAW?: boolean }).__DBGDRAW) console.log("DRAW", JSON.stringify({ target, op: operation, alpha, source: [source.width, source.height], sourceRect }));
    const from = sourceRect ?? { x: 0, y: 0, width: source.width, height: source.height };
    const kind = blendKind(operation);
    for (const [x, y] of this.cells(target)) {
      //: 最近邻:探针读单点时就是这个口径(缩放后的边界像素不参与断言)。
      const sx = from.width > 0 ? from.x + Math.min(from.width - 1, Math.floor(((x - target.x) * from.width) / target.width)) : from.x;
      const sy = from.height > 0 ? from.y + Math.min(from.height - 1, Math.floor(((y - target.y) * from.height) / target.height)) : from.y;
      if (sx < 0 || sy < 0 || sx >= source.width || sy >= source.height) continue;
      const at = (sy * source.width + sx) * CHANNELS;
      const color = { r: source.data[at], g: source.data[at + 1], b: source.data[at + 2], a: source.data[at + 3] / 255 };
      this.merge(x, y, color, alpha * color.a, kind);
    }
  }

  /** 直接落一个像素(渐变那种逐点算的颜色走它)。 */
  put(x: number, y: number, color: Color, alpha: number, operation: GlobalCompositeOperation): void {
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return;
    this.merge(x, y, color, alpha * color.a, blendKind(operation));
  }

  /** 目标矩形里的每一个格子(裁到画布内)。 */
  *cells(rect: Rect): Generator<[number, number]> {
    const left = Math.max(0, Math.floor(rect.x));
    const top = Math.max(0, Math.floor(rect.y));
    const right = Math.min(this.width, Math.ceil(rect.x + rect.width));
    const bottom = Math.min(this.height, Math.ceil(rect.y + rect.height));
    for (let y = top; y < bottom; y += 1) for (let x = left; x < right; x += 1) yield [x, y];
  }

  /** 把一份颜色按 `kind` 叠到 (x,y) 上 —— 规范里那一条合成公式。 */
  private merge(x: number, y: number, color: Color, effective: number, kind: BlendKind): void {
    if (effective <= 0) return;
    const at = (y * this.width + x) * CHANNELS;
    const data = this.pixels.data;
    const backdrop = data[at + 3] / 255;
    const channels = [color.r, color.g, color.b];
    //: `co = αs·(1-αb)·Cs + αs·αb·B(Cb,Cs) + (1-αs)·αb·Cb`(规范里那一条,`αs` 已含 globalAlpha)。
    for (let channel = 0; channel < 3; channel += 1) {
      const mixed = blend(kind, data[at + channel], channels[channel]);
      data[at + channel] = clamp255(
        effective * (1 - backdrop) * channels[channel] + effective * backdrop * mixed + (1 - effective) * backdrop * data[at + channel],
      );
    }
    data[at + 3] = clamp255((effective + backdrop * (1 - effective)) * 255);
  }
}

interface Color {
  r: number;
  g: number;
  b: number;
  a: number;
}

/**
 * 画笔的**软边**那一支:每一笔是一个径向渐变(实心到透明)。
 *
 * 不做的话,画笔那一笔在替身里铺出来的是"透明黑"(色标读不出来),于是蒙版上什么都没画上 ——
 * 测试会变成"空转的绿"。这里按 `addColorStop` 记下的那几档,按**到圆心的距离**插值 ——
 * `MaskEditor` 的 paintLine 每笔只给两档(实心色 / 同色的全透明),所以线性插值就是它要的效果。
 */
class FakeGradient {
  readonly stops: { offset: number; color: Color }[] = [];
  constructor(
    private readonly kind: "radial",
    private readonly inner: { x: number; y: number; r: number },
    private readonly outer: { x: number; y: number; r: number },
  ) {}
  addColorStop(offset: number, css: string): void {
    this.stops.push({ offset, color: parseColor(css) });
    this.stops.sort((left, right) => left.offset - right.offset);
  }
  /** 某个像素上的颜色。径向:`r0`..`r1` 之外按两端夹取。 */
  at(x: number, y: number): Color {
    if (this.stops.length === 0) return { r: 0, g: 0, b: 0, a: 0 };
    if (this.stops.length === 1) return this.stops[0].color;
    const distance = Math.hypot(x + 0.5 - this.outer.x, y + 0.5 - this.outer.y);
    const span = Math.max(1e-6, this.outer.r - this.inner.r);
    const t = Math.min(1, Math.max(0, (distance - this.inner.r) / span));
    let index = 0;
    while (index < this.stops.length - 2 && t > this.stops[index + 1].offset) index += 1;
    const from = this.stops[index];
    const to = this.stops[index + 1];
    const local = to.offset === from.offset ? 0 : Math.min(1, Math.max(0, (t - from.offset) / (to.offset - from.offset)));
    return {
      r: from.color.r + (to.color.r - from.color.r) * local,
      g: from.color.g + (to.color.g - from.color.g) * local,
      b: from.color.b + (to.color.b - from.color.b) * local,
      a: from.color.a + (to.color.a - from.color.a) * local,
    };
  }
  get spec(): { kind: "radial"; inner: { x: number; y: number; r: number }; outer: { x: number; y: number; r: number } } {
    return { kind: this.kind, inner: this.inner, outer: this.outer };
  }
}

/** `#rrggbb` / `#rgb` / `rgb()` / `rgba()` —— 测试里用到的那几种。不认的一律当**透明黑**。 */
export function parseColor(css: string): Color {
  const text = css.trim().toLowerCase();
  if (text.startsWith("#")) {
    const hex = text.slice(1);
    if (hex.length === 3) return { r: parseInt(hex[0] + hex[0], 16), g: parseInt(hex[1] + hex[1], 16), b: parseInt(hex[2] + hex[2], 16), a: 1 };
    if (hex.length >= 6) return { r: parseInt(hex.slice(0, 2), 16), g: parseInt(hex.slice(2, 4), 16), b: parseInt(hex.slice(4, 6), 16), a: 1 };
    return { r: 0, g: 0, b: 0, a: 0 };
  }
  const numbers = text.match(/-?[\d.]+/g)?.map(Number) ?? [];
  if (numbers.length < 3) return { r: 0, g: 0, b: 0, a: 0 };
  return { r: numbers[0], g: numbers[1], b: numbers[2], a: numbers.length > 3 ? numbers[3] : 1 };
}

/** 一份 2D 上下文:只实现这套代码用得到的那几个方法,但**像素是真的**。 */
export class PixelContext2D {
  fillStyle: string | CanvasGradient | CanvasPattern = "#000000";
  strokeStyle: string | CanvasGradient | CanvasPattern = "#000000";
  globalAlpha = 1;
  globalCompositeOperation: GlobalCompositeOperation = "source-over";
  /** 被要求做过什么 —— 既有那批"顺序 + 混合方式"的断言照旧用得上。 */
  readonly calls: string[] = [];
  private path: Rect | null = null;
  private ellipsePath: { cx: number; cy: number; rx: number; ry: number } | null = null;
  /** `arc()` 记下来的那个圆 —— 画笔每一笔都是一串 `arc` + `fill`(见 MaskEditor 的 paintLine)。 */
  private arcPath: { cx: number; cy: number; r: number } | null = null;

  /** 生产的代码读它(`ctx.canvas`)—— 没有它,`createRadialGradient` 那一类会拿到 `undefined`。 */
  readonly canvas: HTMLCanvasElement;

  constructor(private readonly surface: PixelCanvas) {
    this.canvas = (surface.element ?? { width: surface.width, height: surface.height }) as HTMLCanvasElement;
  }

  forget(): void {
    void this.surface;
  }

  private get pixels(): PixelImage {
    return this.surface.pixels;
  }

  fillRect(x: number, y: number, width: number, height: number): void {
    this.calls.push(`fillRect ${String(this.fillStyle)} @${Math.round(x)},${Math.round(y)} ${Math.round(width)}x${Math.round(height)}`);
    this.surface.fill({ x, y, width, height }, String(this.fillStyle), this.globalAlpha, this.globalCompositeOperation);
  }

  clearRect(x: number, y: number, width: number, height: number): void {
    this.calls.push("clearRect");
    //: `clearRect` 是"抹成透明",不是"铺底色" —— 可见那张画布靠它回到空,于是"没画到的地方是透明的"
    //: 这件事在测试里也成立(断言不许把透明当黑色)。
    for (const [cx, cy] of this.surface.cells({ x, y, width, height })) {
      const at = (cy * this.surface.width + cx) * CHANNELS;
      this.pixels.data[at] = 0;
      this.pixels.data[at + 1] = 0;
      this.pixels.data[at + 2] = 0;
      this.pixels.data[at + 3] = 0;
    }
  }

  drawImage(source: unknown, ...rest: number[]): void {
    this.calls.push(`drawImage ${this.globalCompositeOperation} ${this.globalAlpha}`);
    const image = resolveImage(source, this.surface);
    if (!image) return;
    if (rest.length >= 8) {
      const [sx, sy, sw, sh, dx, dy, dw, dh] = rest;
      this.surface.draw({ x: dx, y: dy, width: dw, height: dh }, image, this.globalAlpha, this.globalCompositeOperation, {
        x: sx,
        y: sy,
        width: sw,
        height: sh,
      });
      return;
    }
    if (rest.length >= 4) {
      const [dx, dy, dw, dh] = rest;
      this.surface.draw({ x: dx, y: dy, width: dw, height: dh }, image, this.globalAlpha, this.globalCompositeOperation);
      return;
    }
    const [dx, dy] = rest;
    this.surface.draw({ x: dx, y: dy, width: image.width, height: image.height }, image, this.globalAlpha, this.globalCompositeOperation);
  }

  getImageData(x: number, y: number, width: number, height: number): ImageData {
    const out = new ImageData(width, height);
    for (const [cx, cy] of this.surface.cells({ x, y, width, height })) {
      const from = (cy * this.surface.width + cx) * CHANNELS;
      const to = ((cy - y) * width + (cx - x)) * CHANNELS;
      for (let channel = 0; channel < CHANNELS; channel += 1) out.data[to + channel] = this.pixels.data[from + channel];
    }
    return out;
  }

  createImageData(width: number, height: number): ImageData {
    return new ImageData(width, height);
  }

  putImageData(image: ImageData, dx: number, dy: number): void {
    //: 和浏览器一样:**不缩放**,按它自己的矩形写 —— 尺寸不符时"没覆盖到的那一段保持原样"
    //: (那条零填充的坑就是从这里来的,替身必须照做,不然测试测不出它)。
    for (let y = 0; y < image.height; y += 1) {
      for (let x = 0; x < image.width; x += 1) {
        const tx = dx + x;
        const ty = dy + y;
        if (tx < 0 || ty < 0 || tx >= this.surface.width || ty >= this.surface.height) continue;
        const from = (y * image.width + x) * CHANNELS;
        const to = (ty * this.surface.width + tx) * CHANNELS;
        for (let channel = 0; channel < CHANNELS; channel += 1) this.pixels.data[to + channel] = image.data[from + channel];
      }
    }
  }

  beginPath(): void {
    this.path = null;
    this.ellipsePath = null;
    this.arcPath = null;
  }

  rect(x: number, y: number, width: number, height: number): void {
    this.path = { x, y, width, height };
  }

  ellipse(cx: number, cy: number, rx: number, ry: number): void {
    this.ellipsePath = { cx, cy, rx, ry };
  }

  fill(): void {
    if (this.arcPath) {
      const { cx, cy, r } = this.arcPath;
      this.calls.push(`fill ${String(this.fillStyle)}`);
      const shade = this.fillStyle;
      for (const [x, y] of this.surface.cells({ x: cx - r - 1, y: cy - r - 1, width: r * 2 + 2, height: r * 2 + 2 })) {
        const nx = x + 0.5 - cx;
        const ny = y + 0.5 - cy;
        if (nx * nx + ny * ny > r * r) continue;
        if (shade instanceof FakeGradient) this.surface.put(x, y, shade.at(x, y), this.globalAlpha, this.globalCompositeOperation);
        else this.surface.fill({ x, y, width: 1, height: 1 }, String(shade), this.globalAlpha, this.globalCompositeOperation);
      }
      return;
    }
    if (this.ellipsePath) {
      const { cx, cy, rx, ry } = this.ellipsePath;
      //: 椭圆:逐格判 `((x-cx)/rx)² + ((y-cy)/ry)² <= 1` —— 边界那一圈不追求抗锯齿(断言都取内部点)。
      for (const [x, y] of this.surface.cells({ x: cx - rx - 1, y: cy - ry - 1, width: rx * 2 + 2, height: ry * 2 + 2 })) {
        const nx = (x + 0.5 - cx) / (rx || 1);
        const ny = (y + 0.5 - cy) / (ry || 1);
        if (nx * nx + ny * ny <= 1) this.surface.fill({ x, y, width: 1, height: 1 }, String(this.fillStyle), this.globalAlpha, this.globalCompositeOperation);
      }
      return;
    }
    this.calls.push(`fill ${String(this.fillStyle)}`);
    if (this.path) this.surface.fill(this.path, String(this.fillStyle), this.globalAlpha, this.globalCompositeOperation);
  }

  arc(cx: number, cy: number, r: number): void {
    this.calls.push(`arc ${Math.round(cx)},${Math.round(cy)} r${Math.round(r)}`);
    this.arcPath = { cx, cy, r };
  }

  createRadialGradient(x0: number, y0: number, r0: number, x1: number, y1: number, r1: number): CanvasGradient {
    return new FakeGradient("radial", { x: x0, y: y0, r: r0 }, { x: x1, y: y1, r: r1 }) as unknown as CanvasGradient;
  }

  save(): void {}
  restore(): void {}
}

/**
 * 全局的"这个源对象是什么像素"表。测试里那些**看着像图片**的源(组件画的 `HTMLImageElement` 是
 * 平台给的真元素,测试没法往里塞像素)就靠它 —— `drawImage` 拿到的引用是同一个对象,查得到。
 */
const REGISTERED = new WeakMap<object, PixelImage>();

/** 把一份像素挂到某个源对象上(测试用:`registerPixelImage(imageElement, underlay)`)。 */
export function registerPixelImage(source: object, image: PixelImage): void {
  REGISTERED.set(source, image);
}

function resolveImage(source: unknown, canvas: PixelCanvas): PixelImage | null {
  //: `HTMLCanvasElement` 优先按**元素**去查那张 PixelCanvas(`instanceof` 在跨模块时不可靠)。
  if (source instanceof HTMLCanvasElement) return pixelImageOf(source);
  if (source instanceof PixelCanvas) return source.pixels;
  if (source && typeof source === "object") {
    const mapped = REGISTERED.get(source as object) ?? canvas.images.get(source as object);
    if (mapped) return mapped;
  }
  return null;
}

/**
 * 一个 `<canvas>` 元素的那份像素 —— 由 `pixelCanvasSetup` 在装替身时登记。
 *
 * 走**注册表**而不是 `instanceof PixelCanvas`:`drawImage` 拿到的源是元素,而元素与那份像素的
 * 对应关系只有一处(`pixelOf`),任何"模块有两份实例"的情形都不该让它失配。
 */
let lookup: ((element: HTMLCanvasElement) => PixelImage) | null = null;

export function registerCanvasLookup(fn: (element: HTMLCanvasElement) => PixelImage): void {
  lookup = fn;
}

export function pixelImageOf(element: HTMLCanvasElement): PixelImage | null {
  return lookup ? lookup(element) : null;
}
