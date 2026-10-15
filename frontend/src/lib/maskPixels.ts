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
 * 半径类参数的取整:**半数进位**,`floor(x + 0.5)`(和 `Math.round` 同一条规则,负数也一样)。
 * 扩张和羽化都走它,后端 `media/masks._half_up` 是同一句 —— 契约 contracts/mask-cases.json 钉着。
 */
export const halfUp = (value: number) => Math.floor(value + 0.5);

/**
 * 圆盘结构元拆出来的一趟 1-D 膨胀:`(dx, dy)` 是方向(分量 ∈ {−1, 0, 1},不同时为 0),
 * `reach` 是这一趟的**半长**(沿线取 `[i-reach, i+reach]`)。
 */
export type DiscSegment = readonly [dx: number, dy: number, reach: number];

/** 整数平方根,向下取整。`Math.sqrt` 在完全平方附近可能差一格 → 落地前校正回来。 */
function isqrt(value: number): number {
  let root = Math.floor(Math.sqrt(value));
  if ((root + 1) * (root + 1) <= value) root += 1;
  while (root > 0 && root * root > value) root -= 1;
  return root;
}

/**
 * 数字圆盘 `dx² + dy² ≤ r²` 里 `|dx| + |dy|` 的最大值 —— 八边形的对角边至少要有这么大,才盖得住圆盘。
 *
 * 整数循环(每步一次整数开方),**不含浮点**:后端 `media/masks._disc_diagonal_floor` 是同一段,
 * 两侧算出的是同一个整数。
 */
function discDiagonalFloor(reach: number): number {
  let best = 0;
  for (let dx = 0; dx <= reach; dx += 1) {
    const dy = isqrt(reach * reach - dx * dx);
    if (dx + dy > best) best = dx + dy;
  }
  return best;
}

/**
 * 半径 `reach`(已取整、已按长边封顶、≥ 1)的**圆盘结构元**,拆成一组 1-D 线段:
 * **组内按顺序各做一趟**(= 结构元是这些线段的闵可夫斯基和),组与组之间取**并**。
 *
 * | r | 结构元 | 为什么 |
 * | --- | --- | --- |
 * | 1 | 十字(4 邻)`{(0,0),(±1,0),(0,±1)}` | 半径 1 的数字圆盘**就是**十字;四向八边形做不出它(十字不是凸的) |
 * | 2 | 菱形 `|dx| + |dy| ≤ 2`(3×3 的方 ∪ 两条对角) | 整数上 `dx² + dy² ≤ 4` 与 `|dx| + |dy| ≤ 2` 等价 —— 半径 2 的数字圆盘**就是**这个菱形 |
 * | ≥ 3 | 八边形 `{\|dx\| ≤ r, \|dx ± dy\| ≤ M}` | 四段线段的闵可夫斯基和;`M` 见下 |
 *
 * 1 / 2 两档单独写出来,是因为八边形**表示不了**它们:r = 1 的整数解退化成一个点或 3×3 的方,
 * r = 2 的整数解要么是 3×3 的方、要么大出一圈。小半径是维护者最容易看见的一档(一个点扩出去
 * 就是那个小点),这两档必须是**精确**的圆盘。
 *
 * r ≥ 3 的八边形 = 四段线段(轴向两条 + 对角两条)的闵可夫斯基和,整数参数
 * `axis = M - r`(轴向半长)、`diagonal = r - M / 2`(对角半长),其中
 * `M` 是**能盖住数字圆盘的最小偶数** —— 偶数这条约束来自闵可夫斯基和本身:它给出来的八边形
 * 恒有 `M = 2 × (两条线段的半长之和)`。取"能盖住"的那一侧 ⇒ **扩张半径 r 从不欠账**
 * (结果一定含住半径 r 的真圆盘),代价是八个顶点方向上多出去一点(见 `growMask`)。
 *
 * 后端 `media/masks._disc_segments` 是同一段整数规则(契约 contracts/mask-cases.json 逐字节钉着)。
 */
export function discSegments(reach: number): DiscSegment[][] {
  if (reach <= 1) return [[[1, 0, 1]], [[0, 1, 1]]];
  if (reach === 2) return [[[1, 0, 1], [0, 1, 1]], [[1, 1, 1], [1, -1, 1]]];
  const diagonalFloor = discDiagonalFloor(reach);
  const even = diagonalFloor + (diagonalFloor % 2);
  const axis = even - reach;
  const diagonal = reach - even / 2;
  return [[[1, 0, axis], [0, 1, axis], [1, 1, diagonal], [1, -1, diagonal]]];
}

/**
 * 扩张(`radius` > 0)/ 收缩(`radius` < 0)`|radius|` 个像素,**形态学**:结构元是**圆盘**。
 * 灰的(羽化过的软边)照灰的取最大 / 最小,不先二值化。
 *
 * ## 为什么不是正方形
 *
 * 此前这里的窗口是 `(2r+1)×(2r+1)` 的**正方形**,于是一个圆点扩张之后是一个**带直角的方块**。
 * 现在窗口是圆盘:一个点扩出去还是圆的,只是更大。
 *
 * ## 怎么算(圆盘不可分离)
 *
 * 正方形可分离(横一趟 + 竖一趟),圆盘不行。所以圆盘走「**若干 1-D 线段的闵可夫斯基和**」:
 * 沿 0° / 45° / 90° / 135° 各做一趟一维膨胀,**顺序复合**起来是一个数字八边形。
 * 「凸结构元的膨胀 = 它各条边的 1-D 膨胀按顺序复合」—— 八条边、四个方向 ⇒ 四趟;
 * 每趟是沿一条线的滑动窗口极值(单调队列,每像素进出队列各一次),**和半径无关**:4096 的文档、
 * 半径 256 拖一下也就是四趟。
 *
 * 注意不是「四趟取**并**」:四趟的并是一个点被扩成米字形的星(每趟只加粗一个方向);
 * **顺序复合**(闵可夫斯基和)才是那个多边形。
 *
 * ## 形状与语义(契约里也写着)
 *
 * 结构元是数字圆盘 `dx² + dy² ≤ r²` 的八向近似:r ≤ 2 时**精确**(十字 / 菱形),
 * r ≥ 3 时是"内切半径 r 的八边形"(见 `discSegments` 的 M 规则)。于是
 * 「扩张 r」的结果**一定含住**半径 r 的真圆盘(不欠账),八个顶点方向上最多多出 ~8%
 * (r = 4 / 5 因为 M 只能取偶数,最多 ~17%;大半径稳定在 ~5%–10%)。
 *
 * 剩下的语义照旧:**半径半数进位**;半径按图像长边封顶(扩半张图和扩整张图是同一张图);
 * 边界**夹取**(越界的取样点取边上那个像素,贴边那一圈不会自己缩掉);取整后为 0 原样返回;
 * 负半径是收缩。
 *
 * ## 边界:整组**先补边**,组内每一趟都不夹取
 *
 * 「越界的取样点取边上那个像素」说的是**结构元的每一个取样点**:先夹取、再取极值。这跟"每一趟各自
 * 夹取、再把结果串起来"**不是**同一件事 —— 夹取会打断平移不变性:`clamp(clamp(y+2)+(-3))` 可能
 * 回到图里,而 `clamp(y+2-3)` 不会。正方形的两轴各管一个坐标、互不干扰,差别看不出来;圆盘的
 * 对角两趟同时动两个坐标,贴着边就会差出来。
 *
 * 所以每一组先按"这一组所有趟的偏移之和"在四周补上**夹取边**(就是把边上那些像素重复出去),
 * 组内每一趟都在补好的图上跑、不再夹取 —— 补出来的位置正是那些"夹回去"的取样点,取回的中间那块
 * 就恰好是"每个取样点各自夹取"的结果。契约里那几条贴着边的用例钉着这条。
 *
 * 和后端 `media/masks.grow_mask` 逐字节相同(contracts/mask-cases.json 两侧跑同一份语料)。
 */
export function growMask(data: MaskPixels, width: number, height: number, radius: number): void {
  const signed = halfUp(radius);
  if (signed === 0 || width < 1 || height < 1 || data.length !== width * height * CHANNELS) return;
  const reach = Math.min(Math.abs(signed), Math.max(width, height));
  if (reach < 1) return;
  const pick = signed > 0 ? Math.max : Math.min;
  const keepFirst = signed > 0 ? (a: number, b: number) => a >= b : (a: number, b: number) => a <= b;
  const count = width * height;
  //: 这一组的裁剪结果先落这儿;单组时它就是最终结果。
  const scratch = new Uint8ClampedArray(count);
  const groups = discSegments(reach);
  //: 组与组取并 —— 只有 r ≤ 2 会分成两组(十字 / 菱形);r ≥ 3 只有一组(八边形)。
  const merged = groups.length > 1 ? new Uint8ClampedArray(count) : null;
  for (let index = 0; index < groups.length; index += 1) {
    const group = groups[index];
    //: 这一组最远能取到多远:各趟偏移的和(补这么多圈就够,组内每一趟都不必再夹取)。
    let padX = 0;
    let padY = 0;
    for (const [dx, dy, step] of group) {
      padX += Math.abs(dx) * step;
      padY += Math.abs(dy) * step;
    }
    const pw = width + padX * 2;
    const ph = height + padY * 2;
    //: 从 `data` 直接取灰度铺进补好边的图里(上一组的缓冲已经不能用了,所以每组都重来)。
    let source = new Uint8ClampedArray(pw * ph);
    replicateGray(data, source, width, height, padX, padY, pw);
    let target = new Uint8ClampedArray(pw * ph);
    const queue = new Int32Array(Math.max(pw, ph));
    for (const [dx, dy, step] of group) {
      extremumAlong(source, target, pw, ph, step, dx, dy, keepFirst, queue);
      //: 这一趟的输出是下一趟的输入;两张缓冲轮着用。
      const swap = source;
      source = target;
      target = swap;
    }
    //: 取回中间那块(边上那几圈是补出来的,不写回)。
    for (let y = 0; y < height; y += 1) {
      const at = (y + padY) * pw + padX;
      scratch.set(source.subarray(at, at + width), y * width);
    }
    if (!merged) continue;
    if (index === 0) merged.set(scratch);
    else for (let i = 0; i < count; i += 1) merged[i] = pick(merged[i], scratch[i]);
  }
  const result = merged ?? scratch;
  for (let at = 0, i = 0; at < data.length; at += CHANNELS, i += 1) {
    const value = result[i];
    data[at] = value;
    data[at + 1] = value;
    data[at + 2] = value;
    data[at + 3] = 255;
  }
}

/**
 * 沿一条线求滑动窗口极值:**线**由 `base`(起点下标)、`step`(沿线走一步的下标增量)、
 * `length`(这条线有几个像素)给出;窗口是线上的 `[i-reach, i+reach]`,夹在这条线内。
 *
 * 队列里存**线上的位置**,对应的值从队头到队尾按「谁更该留下」单调:新来的比队尾更该留下,队尾就
 * 再也当不上极值了;窗口右端推进时进队、左端越过时出队,每个像素进出各一次 ⇒ 一条线 O(length),
 * 整趟 O(n),**和半径无关**。
 */
function slidingExtremum(
  from: Uint8ClampedArray,
  to: Uint8ClampedArray,
  base: number,
  step: number,
  length: number,
  reach: number,
  keepFirst: (a: number, b: number) => boolean,
  queue: Int32Array,
): void {
  let head = 0;
  let tail = 0;
  let next = 0;
  for (let i = 0; i < length; i += 1) {
    //: 窗口右端推进到 i + reach。
    const right = Math.min(length - 1, i + reach);
    for (; next <= right; next += 1) {
      const value = from[base + next * step];
      while (tail > head && keepFirst(value, from[base + queue[tail - 1] * step])) tail -= 1;
      queue[tail] = next;
      tail += 1;
    }
    //: 窗口左端之外的出队。
    while (queue[head] < i - reach) head += 1;
    to[base + i * step] = from[base + queue[head] * step];
  }
}

/**
 * 从 `data`(RGBA)取红通道(= 灰度,见文件头)铺进一张**四周补了夹取边**的图:
 * 越界的取样点取边上那个像素,就是把最外那一行 / 一列重复出去。
 *
 * `padded` 的宽是 `pw = width + 2·padX`、高是 `height + 2·padY`;中间那几行逐像素取(源是四通道、
 * 抽不出连续的一段),左右两圈用这一行两端的值铺开,上下两圈整行复制贴边的行。
 */
function replicateGray(
  data: MaskPixels,
  padded: Uint8ClampedArray,
  width: number,
  height: number,
  padX: number,
  padY: number,
  pw: number,
): void {
  for (let y = 0; y < height; y += 1) {
    const at = (y + padY) * pw + padX;
    for (let x = 0, source = y * width * CHANNELS; x < width; x += 1, source += CHANNELS) {
      padded[at + x] = data[source];
    }
    padded.fill(padded[at], at - padX, at);
    padded.fill(padded[at + width - 1], at + width, at + width + padX);
  }
  const top = padY * pw;
  const bottom = (height + padY) * pw;
  for (let y = 0; y < padY; y += 1) {
    padded.set(padded.subarray(top, top + pw), y * pw);
    padded.set(padded.subarray(bottom - pw, bottom), bottom + y * pw);
  }
}

/**
 * 沿方向 `(dx, dy)` 取一条线上 `[i-reach, i+reach]` 的极值 —— 一维膨胀 / 腐蚀。
 *
 * 传进来的图是**已经补好夹取边**的那一张(见 `growMask` 那段):所有取样点都落在图内,
 * 所以这里只把窗口夹在这条线内 —— 那是**补边之后**的边界,不是原来那张图的边界,补出来的那些
 * 位置已经代表了"夹回去的取样点"。(补边为什么是整组一次、而不是每一趟各夹各的,见 `growMask`。)
 *
 * 方向只有四种:横、竖、两条对角。窗口对 `i-reach` 与 `i+reach` 是对称的,所以方向的正负号不影响
 * 结果 —— 四个方向正好四趟(对着 `(1,1)` 再跑一趟 `(-1,-1)` 是同一张图)。
 */
function extremumAlong(
  from: Uint8ClampedArray,
  to: Uint8ClampedArray,
  width: number,
  height: number,
  reach: number,
  dx: number,
  dy: number,
  keepFirst: (a: number, b: number) => boolean,
  queue: Int32Array,
): void {
  if (dy === 0) {
    for (let y = 0; y < height; y += 1) slidingExtremum(from, to, y * width, 1, width, reach, keepFirst, queue);
    return;
  }
  if (dx === 0) {
    for (let x = 0; x < width; x += 1) slidingExtremum(from, to, x, width, height, reach, keepFirst, queue);
    return;
  }
  if (dx === dy) {
    //: 线 x − y = c:起点落在左列或首行,沿线一步是 (1,1)。
    for (let c = 1 - height; c <= width - 1; c += 1) {
      const x0 = c > 0 ? c : 0;
      const y0 = c > 0 ? 0 : -c;
      slidingExtremum(from, to, x0 + y0 * width, width + 1, Math.min(width - x0, height - y0), reach, keepFirst, queue);
    }
    return;
  }
  //: 线 x + y = s:起点取右上角那一端,沿线一步是 (−1,+1)(下标 +width−1)。
  for (let s = 0; s <= width + height - 2; s += 1) {
    const x0 = Math.min(s, width - 1);
    const y0 = s - x0;
    slidingExtremum(from, to, x0 + y0 * width, width - 1, Math.min(x0, height - 1 - y0) + 1, reach, keepFirst, queue);
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
  const reach = halfUp(radius);
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
    const value = halfUp(channel[i]);
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
 * ## 蒙版画布的**唯一写入口** —— 「蒙版编辑只动蒙版」这条不变量钉在这里
 *
 * 维护者报过四次,都是同一个形状:「清空之后底图也没了、整块全黑」「撤销 / 反选 / 形状之后变成灰白
 * (画布上显示的就是蒙版自己)」「橡皮把底图擦掉了」。能把它踩坏的路只有三条,三条都在这里收口
 * —— **每一个写蒙版的动作都必须走 `MaskWriter`,没有第二条路**:
 *
 * | 踩法 | 后果 |
 * | --- | --- |
 * | 蒙版里漏出 `alpha 0` 的像素(尺寸或坐标系不对,`createImageData` 零填充、只写回覆盖得到的那一段) | 合成那两层(`difference` / `multiply`)遇透明像素**保持底色** ⇒ 没画过的地方不再等于原图、**整块被蒙版色糊住** = "变灰" |
 * | 写蒙版时让**底图那一层**从层表里掉出去 | 屏幕上只剩蒙版自己 = 一张灰度图(看上去"底图没了") |
 * | 把动作写到了**错的缓冲**(可见那张、底图那张) | 底图被改掉 = "底图也没了" |
 *
 * 这里管得住全部三条:
 *
 * - `MaskWriter` **自己发画布**,交出去的只有下面那个 `MaskContext` —— 调用方拿不到原始
 *   `CanvasRenderingContext2D`,也就没有第二条路能往蒙版上写(想绕开就得先改这个文件);
 * - 每一次写先过 `partialAllowed`:覆盖不满整张的**默认拒绝**,只有声明过的那几种笔迹例外;
 * - 写完的下一微任务**逐像素验一遍不透明**,破了就记进 `refused` —— 于是"哪一步把它写透明的"
 *   永远有答案,不用再从屏幕上的颜色反推;
 * - `paste` 是这里唯一的 `drawImage`(源图什么色就是什么色),所以它画完读回来**归一成灰度**
 *   (`normalizeGray`)—— 「蒙版逐像素 `r = g = b`」不只管 alpha:漏了它,彩色会一直躺在蒙版里,
 *   直到第一次 `snapshot` / `restore` 把它**静默换成红通道那份灰度**(彩色照片忽然变成黑白)。
 *
 * 为什么"整张写"是硬要求:`putImageData` 的 `ImageData` 是**零填充**的,`fillRect` 只碰它那一块矩形
 * —— 两者都不会把"没碰到的那些像素"补成不透明。而蒙版一旦出现透明像素,损坏是**静默**的:屏幕上
 * 只是"变灰",导出的 PNG 却带上 alpha 通道,ComfyUI 那条 `LoadImageMask(channel="red")` 读出来
 * 整块不透明、**什么都不重绘**(见文件头那条契约)。
 *
 * ## 「橡皮」为什么是写黑
 *
 * 蒙版按契约**没有 alpha 通道可用**(灰度、白 = 要改、每个像素都不透明)⇒ "擦掉"在数据上只可能是
 * **写黑**(= 这块不改)。它在语义上和"擦掉"是同一件事,屏幕上的表现正是**底图重新露出来** ✓ ——
 * 所以那个"擦完应该看见原图、而不是黑"的期待由**底图那一层**负责,不由蒙版负责。别为了"看起来像擦"
 * 去动契约(不许给蒙版引入 alpha)。
 */

/** 这份像素是不是**每个像素都不透明** —— 蒙版契约的那一条。 */
export function isOpaque(data: MaskPixels): boolean {
  for (let at = 3; at < data.length; at += CHANNELS) if (data[at] !== 255) return false;
  return true;
}

/**
 * `paste` 的来源标签 —— 只进诊断信息(`refused` 里那几条),不给人看。
 *
 * 写成常量而不是各处传中文串:`design/uiTextIsTranslated` 那道棘轮扫的是**代码行里的中文**
 * (用来保证界面文字都走文案表),而这几条是给下一个改这个文件的人看的诊断,不是界面文字。
 */
export const PASTE_DRAFT = "draft";
export const PASTE_PREVIOUS = "previous mask";
export const PASTE_THRESHOLD = "threshold-from-source";

/** 蒙版画布上的一次写。`rect` 是这次写要碰的那块矩形(pixel 坐标)。 */
export type MaskWrite =
  | { kind: "fill"; rect: Rect; color: string }
  | { kind: "put"; rect: Rect; image: ImageData }
  | { kind: "paste"; rect: Rect; label: string };

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const covers = (rect: Rect, width: number, height: number) =>
  rect.x <= 0 && rect.y <= 0 && rect.x + rect.width >= width && rect.y + rect.height >= height;

const whole = (width: number, height: number): Rect => ({ x: 0, y: 0, width, height });

/**
 * 这次写允不允许**只覆盖一部分**。默认拒绝;两处例外,判据是"它写进去的值**本身就不透明**"——
 * 整张铺一层不透明色,没碰到的那些像素保持原样,而原样按构造就是全不透明的(蒙版从 `clear()` 的
 * 黑底起,之后每一次写都过这一关)。
 *
 * - `fill` 用 `#ffffff` / `#000000` 两个字面量:画笔、橡皮、形状提交 —— 形状每帧 `putImageData` 的
 *   是**整张**(从快照来),所以它连例外都不需要;
 * - `paste` 是"整张归一"的那些(底稿、上一张蒙版、形状预览快照),调用方给的就是整张。
 *
 * 加新动作时**先问这一句**:"这次写有没有可能让某个像素的 alpha 不再是 255?"答不上来就别加例外。
 */
export function partialAllowed(write: MaskWrite, width: number, height: number): boolean {
  if (covers(write.rect, width, height)) return true;
  if (write.kind === "fill") return write.color === "#ffffff" || write.color === "#000000";
  return false;
}

export function describeWrite(write: MaskWrite): string {
  const at = `${write.rect.x},${write.rect.y} ${write.rect.width}×${write.rect.height}`;
  if (write.kind === "fill") return `fill ${write.color} @ ${at}`;
  if (write.kind === "put") return `put ${write.image.width}×${write.image.height} @ ${at}`;
  return `paste(${write.label}) @ ${at}`;
}

/** 写入口拒绝一次写时抛的东西。消息里带上**为什么**,别让下一个人从头猜。 */
export class MaskWriteRefused extends Error {
  constructor(
    readonly write: MaskWrite,
    readonly size: { width: number; height: number },
    readonly reason: string,
  ) {
    super(`mask write refused (${reason}): ${describeWrite(write)} / document ${size.width}x${size.height}`);
    this.name = "MaskWriteRefused";
  }
}

/**
 * 蒙版那张画布上**唯一**被允许用的上下文。
 *
 * 故意**没有** `putImageData` / `fillRect` / `getContext`:要写就调下面这几个**语义方法**,
 * 而它们都先过守卫。`stroke` / `preview` 交出去的才是原始 ctx —— 那是**画笔**用的,它只画
 * 不透明的白或黑(见 partialAllowed),碰不到"整张"这条线。
 */
export interface MaskContext {
  /** 蒙版文档的尺寸(不是可见画布的尺寸 —— 两者在 contain 之后不相等)。 */
  readonly size: { width: number; height: number };
  /** 取一份像素(反选 / 羽化 / 阈值 / 撤销快照都从它起手)。 */
  read(): ImageData;
  /** 把一份(改过的)像素**整张**写回去。尺寸和文档不符就直接拒绝。 */
  write(image: ImageData): void;
  /** 铺满整张的一层不透明色(黑底 / 清空)。 */
  clear(color?: string): void;
  /** 把一张源图刻度到整张铺上去(底稿 / 上一张蒙版 / 形状预览的基准)。 */
  paste(source: CanvasImageSource, label: string): void;
  /** 一份单通道快照(撤销栈按它存,见 grayscaleOf)。 */
  snapshot(): Uint8ClampedArray;
  /** 把一份单通道快照整张写回去;尺寸和文档对不上就**整张不动**,返回是否写了。 */
  restore(channel: Uint8ClampedArray): boolean;
  /** 一笔画上去(画笔 / 橡皮 / 形状提交)。`shade` 里自由用原始 ctx。 */
  stroke(shade: (ctx: CanvasRenderingContext2D) => void): void;
  /** 按下形状工具:取基准快照。拖到一半文档换尺寸就再调一次(见组件 onPointerMove)。 */
  beginStroke(): void;
  /** 松手 / 离开。 */
  endStroke(): void;
  /** 形状预览的每一帧:先回到基准快照,再画这一帧的形状。 */
  preview(shade: (ctx: CanvasRenderingContext2D) => void): void;
}

export interface MaskWriter {
  /** 文档尺寸(和蒙版画布的位图尺寸永远一致 —— 它就是在这里设的)。 */
  readonly size: { width: number; height: number };
  /**
   * **蒙版内容**改到第几版了。每一次真正写蒙版(`write` / `clear` / `paste` / `restore` / `stroke` /
   * `preview`)都 +1,读(`read` / `snapshot`)不算。
   *
   * 谁要:显示层那份"边缘待应用"的**预览副本**。它是对蒙版的某个版本算出来的,蒙版一变(用户又画了
   * 一笔、撤销了、清空了)那份副本就过期了 —— 靠这个数字判断,而不是靠"记得在每一处写完之后喊一声"
   * (喊漏一处的表现是屏幕上停着一份旧蒙版,极难查)。放在这里是因为**写蒙版只有这一条路**,
   * 版本号也就只有这里说得准。
   */
  readonly revision: number;
  /** 当前那张蒙版画布(导出用;除此之外不要碰它)。 */
  canvas(): HTMLCanvasElement | null;
  context(): MaskContext | null;
  /** 换文档尺寸:重铺一张黑底画布,`carry` 给的是"要按新尺寸铺上去的上一张"。 */
  resize(width: number, height: number, carry?: HTMLCanvasElement | null): MaskContext;
  /** 被拒绝的那些写 —— 诊断用;生产上它们本来就不该发生。 */
  readonly refused: MaskWriteRefused[];
}

const MASK_BLACK = "#000000";

/**
 * 发一张蒙版画布,并把它的上下文包成**唯一**的写入口。
 *
 * 只有这里 `document.createElement("canvas")` —— 蒙版那张画布的所有权也在这里,所以"写到了别的
 * 缓冲上"这件事在类型上就做不到(拿不到别的 ctx)。
 */
export function createMaskWriter(): MaskWriter {
  let canvas: HTMLCanvasElement | null = null;
  let context: MaskContext | null = null;
  let size = { width: 0, height: 0 };
  /** 蒙版内容的版本号(见 `MaskWriter.revision`):每一次真正写都 +1。 */
  let revision = 0;
  const refused: MaskWriteRefused[] = [];
  /** 蒙版内容动了一下。读那几条(`read` / `snapshot`)不算。 */
  const wrote = () => {
    revision += 1;
  };

  const admit = (write: MaskWrite) => {
    if (!partialAllowed(write, size.width, size.height)) {
      const error = new MaskWriteRefused(
        write,
        { ...size },
        "does not cover the whole surface — untouched pixels stay as they were",
      );
      refused.push(error);
      throw error;
    }
    verifyLater(write);
  };

  /** 写完的下一微任务逐像素验一遍:破了就记下来(哪一步、写的是什么、第一个坏像素在哪)。 */
  const verifyLater = (write: MaskWrite) => {
    const target = canvas;
    if (!target) return;
    queueMicrotask(() => {
      try {
        const raw = target.getContext("2d") as CanvasRenderingContext2D | null;
        if (!raw) return;
        const data = raw.getImageData(0, 0, target.width, target.height).data as MaskPixels;
        if (isOpaque(data)) return;
        let first = -1;
        for (let at = 3; at < data.length; at += 4) {
          if (data[at] !== 255) {
            first = at >> 2;
            break;
          }
        }
        refused.push(
          new MaskWriteRefused(
            write,
            { width: target.width, height: target.height },
            `pixel #${first} ended up with alpha ${data[first * 4 + 3]}`,
          ),
        );
      } catch {
        //: 读不回来(画布被污染 / 已经 detached)不是这条不变量的事 —— 别把别的错吞成这一条。
      }
    });
  };

  const install = (element: HTMLCanvasElement, ctx: CanvasRenderingContext2D): MaskContext => {
    canvas = element;
    size = { width: element.width, height: element.height };
    let base: Uint8ClampedArray | null = null;

    /** 原始 ctx 交出去之前把状态复位:上一次留下的 `difference` / 透明 alpha 会让这一笔少画。 */
    const neutral = () => {
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };

    const instance: MaskContext = {
      get size() {
        return { ...size };
      },
      read: () => ctx.getImageData(0, 0, size.width, size.height),
      write(image) {
        admit({ kind: "put", rect: whole(image.width, image.height), image });
        if (image.width !== size.width || image.height !== size.height) {
          //: 尺寸不符的 `ImageData` 会让"没覆盖到的那一段"保持原样 —— 那条路上面已经拒了,这里只是兜底。
          throw new MaskWriteRefused({ kind: "put", rect: whole(image.width, image.height), image }, { ...size }, "size differs from the document");
        }
        neutral();
        ctx.putImageData(image, 0, 0);
        wrote();
      },
      clear(color = MASK_BLACK) {
        admit({ kind: "fill", rect: whole(size.width, size.height), color });
        neutral();
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, size.width, size.height);
        wrote();
      },
      paste(source, label) {
        //: 归一之后就是整张 —— 唯一的例外是"文档比源图大的那几帧",那时底色(黑)本来就不透明。
        admit({ kind: "fill", rect: whole(size.width, size.height), color: MASK_BLACK });
        neutral();
        ctx.drawImage(source, 0, 0, size.width, size.height);
        //: `drawImage` **照抄**源图:源图不是灰的(底稿 = 用户传进蒙版槽的一张照片)就把颜色
        //: 留在了蒙版画布上,而契约是逐像素 `r = g = b`。少了这一下,颜色会一直躺在那儿,直到
        //: 第一次 `snapshot` / `restore`(撤销、形状预览、反选、应用边缘)把它**静默换成红通道那份
        //: 灰度** —— 屏幕上就是"彩色照片忽然变成黑白"(维护者报的那个,画笔/橡皮不走这条路所以没事)。
        //: 读回来 → 归一 → 整张写回,和 `write` / `transform` 是同一套动作。
        const image = ctx.getImageData(0, 0, size.width, size.height);
        normalizeGray(image.data as MaskPixels);
        neutral();
        ctx.putImageData(image, 0, 0);
        wrote();
        void label;
      },
      snapshot: () => grayscaleOf(ctx.getImageData(0, 0, size.width, size.height).data),
      restore(channel) {
        if (channel.length !== size.width * size.height) return false;
        const image = ctx.createImageData(size.width, size.height);
        writeGrayscale(channel, image.data);
        this.write(image);
        return true;
      },
      stroke(shade) {
        neutral();
        shade(ctx);
        wrote();
      },
      beginStroke() {
        base = grayscaleOf(ctx.getImageData(0, 0, size.width, size.height).data);
      },
      endStroke() {
        base = null;
      },
      preview(shade) {
        //: 每帧从按下时那份重来:看到的是"松手后会是这样",不是一层层叠上去的边。基准快照的尺寸
        //: 和文档不符(拖到一半底图读进来)时 `restore` 整张不动 —— 调用方要重取一份。
        if (base) this.restore(base);
        neutral();
        shade(ctx);
        //: 形状拖动的每一帧**确实**改了蒙版内容(下一条 `preview` 会把它抹掉),所以也算一版。
        wrote();
      },
    };
    context = instance;
    return instance;
  };

  return {
    get size() {
      return { ...size };
    },
    get revision() {
      return revision;
    },
    canvas: () => canvas,
    context: () => context,
    refused,
    resize(width, height, carry) {
      const next = document.createElement("canvas");
      next.width = width;
      next.height = height;
      const ctx = next.getContext("2d");
      if (!ctx) throw new Error("no 2D context for the mask canvas");
      const instance = install(next, ctx);
      //: 黑底不是装饰:导出的 PNG 要每个像素都不透明(带 alpha 的图在插件那条路上读出来是空的)。
      instance.clear();
      if (carry) instance.paste(carry, PASTE_PREVIOUS);
      return instance;
    },
  };
}

/**
 * 一份像素的**单通道**灰度 —— 撤销栈按它存。
 *
 * 一步一份四通道的像素在 2048² 上是 16MB,三十步就是五百兆;蒙版本身是灰的,一像素一个字节就够。
 * 还原走 writeGrayscale。
 *
 * 按 **Rec.601 亮度**取(不是红通道):蒙版本该逐像素 `r = g = b`(那时两种取法完全一样),但
 * "本该"不是"一定" —— `normalizeGray` 会把漏进来的彩色归一,而它用的就是这一条。两处同一条,
 * 一次 `snapshot` → `restore` 对一张已经归一的蒙版才是**逐字节不变**的。
 */
export function grayscaleOf(data: MaskPixels): Uint8ClampedArray {
  const count = Math.floor(data.length / CHANNELS);
  const channel = new Uint8ClampedArray(count);
  for (let at = 0, i = 0; i < count; at += CHANNELS, i += 1) channel[i] = halfUp(gray(data[at], data[at + 1], data[at + 2]));
  return channel;
}

/**
 * 把一份像素**就地归一成灰度**:`r = g = b = Rec.601 亮度`,alpha 填满(见文件头那两条契约)。
 *
 * 蒙版的每一条写路径本来只会写出灰的:`clear` 的黑、`stroke` 的白 / 黑、`write` 那边全是纯函数 ——
 * 只有 `paste` 是 `drawImage`,**源图什么色就是什么色**。而底稿就是用户自己传的那张图(蒙版那一格
 * 的 `accept` 是 `image/*`):传一张照片进去,颜色就这么进了蒙版画布。
 *
 * 代价不是"看着不对"那么轻:下一次 `snapshot` / `restore`(撤销、形状的每一帧预览、反选、应用边缘)
 * 会把整张换成单通道那一份 —— 彩色照片**忽然变成黑白**,而不碰整张的画笔 / 橡皮看着一切正常。
 *
 * 用 Rec.601 亮度而不是红通道:后端把蒙版落成 `L` 模式走的正是这条(PIL 的 `L`),`thresholdMask`
 * 也是这条(见文件头的 `LUMA_*`)。
 */
export function normalizeGray(data: MaskPixels): void {
  for (let at = 0; at < data.length; at += CHANNELS) {
    const value = halfUp(gray(data[at], data[at + 1], data[at + 2]));
    data[at] = value;
    data[at + 1] = value;
    data[at + 2] = value;
    data[at + 3] = 255;
  }
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
