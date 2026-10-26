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
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
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
 * ## 蒙版槽里的**彩色图**是参考底图,不是底稿
 *
 * 「蒙版」那一格(`lib/sourceFrames.ts` 的 `mask`)是 `image/*`,用户能传一张彩色照片进去。那张图
 * 打开时读进来(`initial`),按**它是灰还是彩**分两条路(判据 `isGrayscaleImage`,容差 2):
 *
 * | 蒙版槽里那张图 | 当什么 | 蒙版画布 | 屏幕上 |
 * | --- | --- | --- | --- |
 * | 灰度(每个像素 r ≈ g ≈ b)| **已有的蒙版**(底稿):铺进蒙版,接着在上面画 | 那张图 | 那张图 |
 * | 彩色(有像素差 > 2)| **参考底图**:和 `source` 同一个槽位,只画在看得见的那张上 | 空白黑底 | **原始彩色** |
 *
 * 「传进来的彩色照片就看着是彩色、蒙版从空白开始画」是维护者拍板要的行为。优先级:`source`(参考图 /
 * 首帧那一格)在的时候**它就是**底图 —— 彩色 initial 不抢底图,只被忽略成底稿。存回去的仍然是灰度蒙版
 * (见上一节,契约没变)。
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
 *
 * ## 五个参数,各管一件事(维护者最终定义)
 *
 * | 参数 | 管什么 | 落在哪 |
 * | --- | --- | --- |
 * | 笔刷大小 | 笔尖直径 | `paintLine` 的半径;形状那条过渡带的尺度也按它算(见 `edgeBand`) |
 * | **笔刷硬度** | **每一笔的边缘过渡**(100% = 一刀切;越低边缘越软) | 画笔:径向渐变的内半径 `半径 × 硬度` → 外半径 `半径`;矩形 / 椭圆:从外沿往里一条 `半径 × (1 − 硬度)` 宽的斜坡;指针那个圈 |
 * | **不透明度** | **画进蒙版的灰度值** = 蒙版的透明度 / 改动强度 | `inkGray(不透明度) = round(不透明度 × 255)`(`inkColor`),画笔 / 矩形 / 椭圆共用 |
 * | 扩张 | 整张蒙版边缘外扩 / 内缩(**圆盘**结构元,见 `lib/maskPixels`) | 显示层那份预览副本,点「应用到蒙版」才写真蒙版 |
 * | 羽化 | 整张蒙版边缘的过渡宽度 | 同上 |
 *
 * ### 浓度靠**颜色**承载、软边靠 **alpha**
 *
 * 不透明度定的那个灰度就是这一笔的**颜色**:`rgb(v v v)`(v = `round(不透明度 × 255)`),
 * `globalAlpha` 保持 1。硬度定的那条软边是**同一个颜色**的 alpha 从 1 到 0(画笔的径向渐变;
 * 形状那条是分层内缩 + 递增 `globalAlpha`)。两件事因此互不重叠:
 *
 * - **不叠加**:同色的 dab 重叠是"同一个不透明色再铺一次",颜色不变 ⇒ 整条笔迹的值就是 v
 *   (0.5 → `128`),来回蹭多少趟都停在 v —— 若改成"白 + alpha = 不透明度",重叠处会
 *   `1 − (1 − 不透明度)ⁿ` 一路饱和到 255(上一版就是那样,再叠上径向渐变);
 * - **不外溢**:软边那一段颜色始终是 v、只有 alpha 走 1 → 0 ⇒ 边缘是 `v → 0` 的斜坡,不会在边上
 *   混出别的浓度。
 *
 * 不透明度 1 → `255`、0.5 → `128`、**0 → `0`**(滑块最左直接涂不上:写进蒙版的 0 就是"这块不改")。
 *
 * 指针圈**只跟硬度走**(`brushRingFill` / `ringInk`:越低越透,维护者那句「应该和透明度有关系」
 * 落的就是这里),和不透明度无关 —— 它是"这笔的边有多软"的提示,不是一张浓度色卡。
 * 圈上**没有**常量边框:上一版留着 `border border-white` + 一圈 `shadow`,那道硬白圈把渐变整个盖住
 * —— 拖硬度屏幕上一动不动(维护者第二次报的就是它)。现在圈的观感只由那一串填充给。
 *
 * ## 「橡皮」**不**吃不透明度(擦除力度保持满强度)
 *
 * 维护者给的是二选一("擦除强度也跟不透明度"或"论证为什么它该保持满强度"),这里选了后者:
 *
 * 1. 蒙版是**没有 alpha 的灰度图**,"擦掉"在数据上只能是写黑(`0` = 这块不改,见 `lib/maskPixels`
 *    文件头那条)。橡皮的落点值只有**一个**目标,**没有"半浓的黑"可言** —— 而不透明度那条说的是
 *    "往蒙版里**加**多浓",橡皮不加东西;
 * 2. 想让擦除吃不透明度的唯一表达是拿 `globalAlpha = 不透明度` 去混(`v ← v × (1 − 不透明度)`)。
 *    可 dab 的间距是半径的 0.4 倍 ⇒ 同一个像素会被同一笔打中五到九次:`(1 − 0.5)⁵ ≈ 0.03` ——
 *    笔迹**中间照样擦干净、只有边缘留一点**,连"擦除力度"都算不上(0% 还会变成"擦不动",比涂不上
 *    更难解释);
 * 3. 于是**唯一**那个浓度定义(`inkGray`)橡皮不消费它 —— 这条决定由
 *    `MaskEditor.pixels.dom.test.tsx` 里那条"橡皮不吃不透明度"钉着。
 *
 * 橡皮**吃硬度**:那是"每一笔的边缘过渡",和擦除力度是两件事(维护者那张表里硬度那一行写着
 * "画笔/橡皮 + 形状工具都吃它")。所以橡皮的 dab 中心照旧是纯 `0`,边上才淡出去。
 *
 * 预览那份副本是**一张按显示分辨率算的画布**(`edgePreviewRef`):把当前蒙版按 `previewScale` 缩进
 * 副本自己的画布、在**那份缩过的像素**上跑 `growMask` + `featherMask`(半径同比缩)、`putImageData`
 * 进它自己那张画布 —— 真蒙版那张从头到尾没人写。它只喂给 `drawMaskView` 的 `mask` 层,所以
 * 「待应用」时用户看到的就是点下那个按钮会得到的样子(测试里两者逐字节相等)。三条判据管着它:
 *
 * - **过期**:副本的 `key` 里有 `MaskWriter.revision`(内容)+ 参数 + 分辨率 —— 蒙版内容一变
 *   (又画了一笔、撤销了、清空了)那份副本就作废,`displayedMask` 当场回到真蒙版,绝不让旧副本
 *   冒充新的那一版;
 * - **两条触发分开**(维护者第三次报的「设置扩张以后 绘制、画笔过程都会非常卡顿」):
 *   **参数变**(grow / feather 滑块)在**那一次 `paint()`** 里当场重算(`refreshEdgesPreview`,
 *   一个计时器都不等 —— 维护者要的实时手感);**内容变**(正在画)则**不每帧算**:落笔期间显示层
 *   直接喂真蒙版(当帧可见、不卡),`EDGE_PREVIEW_TRAILING_MS` 之后才把预览追上去
 *   (`catchUpEdgesPreview`)。病根是上一版把内容版本号也塞进了"要不要重算"的判据里,而画笔
 *   每一帧都在 +1 ⇒ 每帧一次约 90ms 的重算;
 * - **已经写进去了**:点过「应用到蒙版」的那一组参数在这一版蒙版上不再算"待应用"(`appliedEdgesRef`)
 *   —— 少了这一条,应用之后屏幕会把它**再预览一遍**(又扩张 4 个像素,一眼看得出)。
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

/**
 * 这个模块**发出去的那张预览副本画布**(见 `renderEdgesPreview`)。同样只给测试用:像素级回归要能
 * 认出"屏幕上那份预览是按多大的分辨率算的"(文档 96×120、盒子 48×60 时它该是 48×60)。
 */
const EDGE_PREVIEW_CANVASES = new WeakSet<HTMLCanvasElement>();

/** 这张画布是不是「待应用的扩张 / 羽化」那份预览副本。 */
export function isEdgePreviewCanvas(element: HTMLCanvasElement): boolean {
  return EDGE_PREVIEW_CANVASES.has(element);
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
/**
 * 硬度到了这一档以上就算"硬边"(一刀切、没有渐隐那一段)。
 *
 * **三处共用这一个数**:画笔(`paintLine` 走实心那一条)、矩形 / 椭圆(`paintShape` 只填一次)、
 * 指针那个圈(`brushRingFill` 整块平铺)。各写一个 0.99 迟早会分叉,而分叉的表现正是「圈看着是硬的、
 * 画出来是软的」—— 那比没有圈更糟。
 */
const HARD_EDGE = 0.99;
/**
 * 形状 / 画笔那条软边**往里铺几层**(见 `paintShape`)。
 *
 * 层数就是那条斜坡的**分辨率**:每一层往里缩 `过渡带 ÷ 32`。半径 24 的笔刷上那是一格七五 ——
 * 屏幕上那条斜坡看不出台阶;再密只是白算(形状拖动时每一帧都要重铺一遍)。
 */
const SOFT_STEPS = 32;
const TAU = Math.PI * 2;
const BLACK = "#000000";
const WHITE = "#ffffff";
/** 橡皮的墨那一端(写黑 = `0` = 这块不改):它**不吃不透明度**,见文件头那一节。 */
const ERASER_FADE = "rgba(0, 0, 0, 0)";
/**
 * 笔画停下来之后多久把扩张 / 羽化的预览追上去(尾随,见 `catchUpEdgesPreview`)。
 *
 * 依据:副本按显示分辨率算,维护者那张 4432×1904 上重算一趟约 90ms(真 Chromium 实测,含画布读回,
 * 见 `previewScale`)—— 那比一帧(60Hz 的 16.7ms)长五倍,落在笔迹中间就是"每帧一次 90ms"的幻灯片
 * (维护者第三次报的「设置扩张以后 绘制、画笔过程都会非常卡顿」)。120ms 是"手停下一小会儿"的量级:
 * 比一趟 90ms 宽出三成,落笔期间不会排上第二次;停手之后人几乎察觉不到这一下。
 */
export const EDGE_PREVIEW_TRAILING_MS = 120;
/**
 * 指针那个圈里的**两层墨**:一深一浅,叠在同一块圆盘上。
 *
 * 只涂一层的话,蒙版画布上总有一半看不见它:底下是白(没画过的白蒙版、亮底图)时白墨没了,是黑时
 * 黑墨没了。两层一起淡出去,那条软边在**任何底色**上都读得出来 —— 而"看得见"正是这个圈存在的理由。
 * 两层都是低透明度:圈的**形状**才是信息,它自己不喧宾夺主。
 */
const RING_DARK_RGB = "0, 0, 0";
const RING_LIGHT_RGB = "255, 255, 255";
const RING_DARK_ALPHA = 0.35;
const RING_LIGHT_ALPHA = 0.45;
const RING_DARK_FADE = "rgba(0, 0, 0, 0)";
const RING_LIGHT_FADE = "rgba(255, 255, 255, 0)";
/**
 * 软的圈里那两层墨最少留到原来的几成(`hardness` = 0 那一档)。
 *
 * 维护者那句「应该和透明度有关系」就落在这一条上:硬度在屏幕上说的本来就是**透明度** —— 软笔是墨
 * 一点点淡出去,硬笔是一刀切。所以让硬度同时管住两件事:硬核到哪一格(`hardness × 半径`)和墨整体
 * 多浓。于是 10% 与 100% 的圈不只是"渐隐那一段宽窄不同",**浓度**也一眼看得出不一样。
 * 0.55 是下限:再淡圈就快看不见了,而圈的存在正是为了让人看见笔刷落在哪。
 */
const RING_INK_FLOOR = 0.55;

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

/**
 * 判灰度时**任意两个通道**允许的最大差。本应用导出的蒙版逐字节 `r = g = b`(差 0),而灰度 JPEG
 * 解码后各通道会差个 1(色度子采样 + 取整)—— 留 2 才不会把一张灰度照片误判成彩色照片。
 */
const GRAY_TOLERANCE = 2;

/**
 * 这一份像素是不是一张**灰度图**:每一个像素都 `r ≈ g ≈ b`(任意两通道相差 ≤ `tolerance`)。
 *
 * 蒙版槽那一格的 `accept` 是 `image/*`(`lib/sourceFrames.ts` 的 `mask`),用户能传两种图进去,
 * 这张判据是它们**唯一**的分别(见文件头「蒙版槽里的彩色图是参考底图,不是底稿」):
 * 灰度的 = 用户已有的那张蒙版(当底稿,接着在上面画);彩色的 = 一张参考图(当底图,蒙版从空白画起)。
 *
 * 扫全部像素、发现第一个明显彩色的就返回 —— 近灰的图要扫到底,但它只有一遍、一次打开一遍。
 */
export function isGrayscaleImage(data: MaskPixels, tolerance = GRAY_TOLERANCE): boolean {
  for (let at = 0; at < data.length; at += 4) {
    const r = data[at];
    const g = data[at + 1];
    const b = data[at + 2];
    if (Math.abs(r - g) > tolerance || Math.abs(g - b) > tolerance || Math.abs(r - b) > tolerance) return false;
  }
  return true;
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

/**
 * 「待应用」的扩张 / 羽化在屏幕上预览的那份副本,按多大的分辨率算(1 = 原样,不缩)。
 *
 * 显示层那张位图本来就封在 `MAX_VIEW_EDGE` 里(见那个常量),蒙版尺寸再大,屏幕上也只有这么多像素
 * —— 在文档全分辨率上跑形态学 + 三遍盒式模糊,多出来的细节屏幕上根本看不见,代价却是拖动时每一帧
 * 几百毫秒(维护者那张 4432×1904 是八百四十万像素:一次 `read()` 加形态学加模糊,几百毫秒 → 拖滑块
 * 时屏幕一动不动)。这里把副本压到**和显示层同一个分辨率**:
 *
 * - 长边不超过 `MAX_VIEW_EDGE` —— 显示层位图的上限,同一个常量,不另造一个分辨率魔法数;
 * - 也不超过可见那张位图:画布区小的时候没必要按 2048 算(盒子 600 宽时那 2048 是白算的);
 * - 文档本来就够小 ⇒ 返回 1,原样算(小文档的预览因此逐字节不变,和其它断言一样严)。
 *
 * 半径按同一个比例缩(`grow × scale` / `feather × scale`):屏幕上长出来的方向与幅度,和点下
 * 「应用到蒙版」时写进真蒙版的那一下一致 —— 差的只是降采样带来的亚像素。
 */
export function previewScale(doc: Size, view: Size): number {
  const longest = Math.max(doc.width, doc.height);
  if (longest < 1) return 1;
  let scale = Math.min(1, MAX_VIEW_EDGE / longest);
  if (doc.width > 0 && doc.height > 0 && view.width > 0 && view.height > 0) {
    scale = Math.min(scale, view.width / doc.width, view.height / doc.height);
  }
  return scale;
}

/**
 * `HARD_EDGE` 那个判据(见常量):硬度到这一档以上就是一刀切 —— 画笔走实心那一条、形状只填一次、
 * 圈整块平铺。**三处共用**(不会分叉)。
 */
function isHardEdge(hardness: number): boolean {
  return unit01(hardness) >= HARD_EDGE;
}

/**
 * 边缘那条过渡带的宽度 = **笔刷半径 × (1 − 硬度)**(硬度 1 时是 0 = 一刀切)。
 *
 * 这是"硬度 = 每一笔的边缘过渡"那一条的**唯一**尺度,**画笔和形状共用**:
 *
 * - 画笔:`paintLine` 的径向渐变内半径 = `半径 − edgeBand(半径, 硬度)` —— 剩下那一段正是渐隐带;
 * - 矩形 / 椭圆:`paintShape` 从外沿往里铺这么宽的一条斜坡。
 *
 * 抽成一个函数、而不是两处各写一遍 `× (1 − 硬度)`:那正是"画笔的软边和形状的软边不是一个尺度"的
 * 来源(测试里"过渡带宽度 = 笔刷半径 × (1 − 硬度)"量的是它)。
 */
export function edgeBand(radius: number, hardness: number): number {
  return Math.max(0, radius * (1 - unit01(hardness)));
}

/**
 * ## 不透明度 → 这一笔涂进蒙版的**灰度**(维护者最终定义,一处定义在这里)
 *
 * 蒙版是灰度图、白 = 要改(见 `lib/maskPixels` 文件头),所以"画进去多浓"就是那个灰度本身:
 * `round(不透明度 × 255)`。1 → 255、0.5 → 128、**0 → 0**(= 写黑 = 这块不改,滑块最左直接涂不上)。
 *
 * 三处**画**的地方共用它:画笔的每个 dab、矩形、椭圆。橡皮**不**消费它(理由见文件头
 * 「橡皮不吃不透明度」)。
 */
export function inkGray(opacity: number): number {
  return Math.round(unit01(opacity) * 255);
}

/**
 * 那个灰度写成画布认的**实心**颜色(空格分隔:同样合法,但字符串更短、测试里的正则更好读)。
 *
 * **浓度靠颜色承载、`globalAlpha` 保持 1**,这是"密集重叠不叠到 255"的关键:同一笔的每个 dab
 * 铺的是**同一个不透明色**,叠上去是"再铺一次同色"(逐像素结果还是那个色);若改成"白色 + alpha =
 * 不透明度",重叠处会 `1 − (1 − 不透明度)ⁿ` 一路饱和到 255 —— 上一版就是那样。
 */
function inkColor(opacity: number): string {
  const value = inkGray(opacity);
  return `rgb(${value} ${value} ${value})`;
}

/**
 * 同一个浓度的**透明端** —— 软边渐变的外圈那一端:颜色还是那个浓度色,只有 alpha 到 0。
 *
 * 颜色必须跟着 `inkColor` 走(不能写死白):渐变外圈混出来的要是"同一个灰的淡版本",不然软边会
 * 带出别的浓度(见文件头「浓度靠颜色承载、软边靠 alpha」)。
 */
function inkFade(opacity: number): string {
  const value = inkGray(opacity);
  return `rgba(${value}, ${value}, ${value}, 0)`;
}

/**
 * 一笔画上去:沿 from→to 按间距盖圆点,**每一个 dab 都是同一个浓度色**。间距取半径的四成
 * —— 比半径密,笔迹才不显颗粒。
 *
 * 每一笔的软边:内半径到 `半径 × 硬度` 是实心硬核,外面渐隐到半径那一圈,alpha 从 1 到 0
 * (颜色自始至终是那一个浓度色)。于是:
 *
 * - 重叠的 dab 把同一个不透明色再铺一遍 ⇒ 整条笔迹的值就是那个浓度,来回描也停在它(**不会 255**);
 * - 笔迹的外缘就是硬度给的软边(硬度 ≥ `HARD_EDGE` 或半径 ≤ 1 时走实心那一条)。
 *
 * 真浏览器里 `fill()` 在圆盘边上还会带一圈亚像素抗锯齿 —— 那是栅格化的常态,不是"软化"。
 */
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
  const soft = !isHardEdge(hardness) && radius > 1;
  //: 硬核那一段 = 半径 − 过渡带(和形状同一条尺度,见 edgeBand)。
  const core = radius - edgeBand(radius, hardness);
  for (let step = 1; step <= steps; step += 1) {
    const at = { x: from.x + ((to.x - from.x) * step) / steps, y: from.y + ((to.y - from.y) * step) / steps };
    ctx.beginPath();
    ctx.arc(at.x, at.y, radius, 0, TAU);
    if (!soft) {
      ctx.fillStyle = ink;
      ctx.fill();
      continue;
    }
    const gradient = ctx.createRadialGradient(at.x, at.y, core, at.x, at.y, radius);
    gradient.addColorStop(0, ink);
    gradient.addColorStop(1, fade);
    ctx.fillStyle = gradient;
    ctx.fill();
  }
}

/**
 * 指针那个圈的**填充**:内圈到 `radius × hardness` 是实心硬核,外面渐隐到半径那一圈(和
 * `paintLine` 那条软边是同一条曲线);那两层墨的**浓度**也随硬度走(见 `ringInk`)。
 *
 * 它**只跟硬度走**:硬度 = 这一笔的边缘过渡,圈说的就是这件事 —— **不透明度**(画进蒙版的浓度)
 * 不进来(维护者最终定义里那是两根不同的滑块,见文件头那张表)。
 *
 * 这个 div 上**没有**常量边框:上一版留了一道写死的 `border border-white` + 一圈 `shadow`,那道硬白圈
 * 盖在渐变上面,于是拖硬度屏幕上一动不动 —— 维护者第二次报的「还是没体现」正是它。现在圈的观感
 * 只由这一串填充给。深浅两层一起给(理由见上面那两个常量);整串当 `background` 一次写进 DOM
 * —— 只换一层的话,底色一变就会剩下一半看不见。
 */
export function brushRingFill(hardness: number): string {
  const level = unit01(hardness);
  //: 三位小数足矣:再多的位数只是让 DOM 里的字符串更长(0.35 × 0.775 = 0.27125 那种)。
  const ink = (rgb: string, alpha: number) => `rgba(${rgb}, ${Number((alpha * ringInk(level)).toFixed(3))})`;
  const dark = ink(RING_DARK_RGB, RING_DARK_ALPHA);
  const light = ink(RING_LIGHT_RGB, RING_LIGHT_ALPHA);
  //: 硬边:两层都铺满,没有渐变可看(`linear-gradient(ink, ink)` 就是一整块纯色,只是能跟另一层并排写)。
  if (isHardEdge(level)) {
    return `linear-gradient(${dark}, ${dark}), linear-gradient(${light}, ${light})`;
  }
  const core = Math.round(level * 100);
  //: `closest-side`:这个盒子是正圆(宽高都由 placeRing 写成同一个直径),所以它就是"到边的距离"。
  const soft = (color: string, fade: string) => `radial-gradient(closest-side, ${color} 0%, ${color} ${core}%, ${fade} 100%)`;
  return `${soft(dark, RING_DARK_FADE)}, ${soft(light, RING_LIGHT_FADE)}`;
}

/**
 * 参数收进 `0..1`(**硬度和不透明度都是这一档**);不是有限数时按满那一档(硬边 / 满浓度)。
 */
function unit01(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(1, Math.max(0, value));
}

/**
 * 圈的墨在硬度 `hardness` 上留多少(1 = 原样)。
 *
 * 维护者那句「应该和透明度有关系」:硬度越低,圈的墨越淡(下限见 `RING_INK_FLOOR`)—— 和那条
 * "硬核越窄、渐隐越宽"的曲线说的是同一件事:软笔的边是淡出去的。
 */
export function ringInk(hardness: number): number {
  return RING_INK_FLOOR + (1 - RING_INK_FLOOR) * unit01(hardness);
}

/** 形状往里缩 `inset` 之后填一次(矩形 / 椭圆各一条路;缩没了就什么都不填)。 */
function fillInset(
  ctx: CanvasRenderingContext2D,
  tool: Tool,
  left: number,
  top: number,
  width: number,
  height: number,
  inset: number,
): void {
  const inner = { left: left + inset, top: top + inset, width: width - inset * 2, height: height - inset * 2 };
  if (inner.width <= 0 || inner.height <= 0) return;
  if (tool === "rect") {
    ctx.fillRect(inner.left, inner.top, inner.width, inner.height);
    return;
  }
  ctx.beginPath();
  ctx.ellipse(inner.left + inner.width / 2, inner.top + inner.height / 2, inner.width / 2, inner.height / 2, 0, 0, TAU);
  ctx.fill();
}

/**
 * 矩形 / 椭圆:一次填一块**浓度色**的图形,边缘按硬度铺一条软边(拖动时每帧重画,所以看到的就是
 * 松手后的样子)。
 *
 * 浓度和画笔**同一条定义**(`inkColor` → `inkGray`):不透明度 1 → 255、0.5 → 128、0 → 0(涂不上)。
 * 边缘那条斜坡的宽度是 `edgeBand(笔刷半径, 硬度)` —— **和画笔共用同一个尺度**:
 *
 * - 从外沿往里一层层缩:第 m 层缩 `过渡带 × m / SOFT_STEPS`、`globalAlpha = 1 / (SOFT_STEPS − m)`;
 * - 累计起来正好是 `m / SOFT_STEPS`(每一层把剩下的差距补掉一格)⇒ 外缘是 `浓度 → 0` 的一条直线
 *   斜坡,而**最里面那一层 alpha 1 把内部按在浓度色上**(不会"层数越多越亮",也不会停在某个
 *   比浓度小的值);
 * - 颜色自始至终是那一个浓度色 ⇒ 内部停在 v、外缘是 `v → 0`(见文件头)。
 *
 * `isHardEdge`(硬度 ≥ `HARD_EDGE`)/ 过渡带为 0 时只填一次:边缘逐格是 `0 / v` 的跳变。
 *
 * 外沿就是拖出来的那个框(`from` → `to`):软硬不改形状的大小。真浏览器里 `fillRect` /
 * `ellipse().fill()` 在分数坐标上会有一像素的抗锯齿 —— 那不是"软边",是像素栅格化的常态。
 */
function paintShape(
  ctx: CanvasRenderingContext2D,
  tool: Tool,
  from: Point,
  to: Point,
  ink: string,
  hardness: number,
  radius: number,
): void {
  const left = Math.min(from.x, to.x);
  const top = Math.min(from.y, to.y);
  const width = Math.abs(to.x - from.x);
  const height = Math.abs(to.y - from.y);
  //: 点一下没拖(0×0 的框):什么都不画(松手那边也不记一步,见 onPointerUp)。
  if (width <= 0 || height <= 0) return;
  ctx.fillStyle = ink;
  const band = edgeBand(radius, hardness);
  if (isHardEdge(hardness) || band <= 0) {
    fillInset(ctx, tool, left, top, width, height, 0);
    return;
  }
  //: 缩到只剩一格就停:再往里缩形状就没了,而**最后一层 alpha 1** 保证内部仍是浓度色。
  const deepest = Math.max(0, Math.min(width, height) / 2 - 0.5);
  for (let layer = 0; layer < SOFT_STEPS; layer += 1) {
    ctx.globalAlpha = 1 / (SOFT_STEPS - layer);
    fillInset(ctx, tool, left, top, width, height, Math.min((band * layer) / SOFT_STEPS, deepest));
  }
  //: 复位:这个 ctx 是写入口交出来的(它每次进来也 `neutral()`),这里不留脏状态给下一个人。
  ctx.globalAlpha = 1;
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
  /**
   * 蒙版槽那一格现在有的一张图。**灰度的** = 已有的蒙版:当底稿铺进蒙版,接着在上面画
   * (ADR 0056 决定 5);**彩色的** = 一张参考图:当底图(蒙版从空白开始),`source` 在的时候不抢它。
   * 见文件头「蒙版槽里的彩色图是参考底图,不是底稿」。
   */
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
  /** 指针**上一次**在画布上的哪一点(CSS 像素):拖硬度 / 大小滑块时圈就在原地重画,不用等下次移动。 */
  const ringPointRef = React.useRef<Point | null>(null);
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
  /**
   * 「待应用」的扩张 / 羽化在屏幕上用的那份**预览副本**:`key` 说它是按哪一版蒙版、哪一组参数算的
   * (见 `edgesKey`)。真蒙版那张从头到尾没人写它 —— 它只喂给 `drawMaskView` 的 `mask` 层。
   */
  const edgePreviewRef = React.useRef<{ canvas: HTMLCanvasElement; key: string } | null>(null);
  /**
   * 哪一组扩张 / 羽化**已经写进**这一版蒙版了(`applyEdges` 之后记下来)。滑块还是那几个数,但屏幕上
   * 不该再预览一遍 —— 否则"应用"之后会看到又扩张一次。
   */
  const appliedEdgesRef = React.useRef<{ revision: number; grow: number; feather: number } | null>(null);
  /** `paint()` 是终身不变的那个函数(只读 ref),所以这三件事只能从 ref 里拿到最新那几个闭包。 */
  const ringSyncRef = React.useRef<() => void>(() => undefined);
  /** 预览副本这一帧该怎么更新(两条触发分开,见 `syncEdgesPreview`)。 */
  const edgesSyncRef = React.useRef<() => void>(() => undefined);
  /** 底图像素(按亮度 / 按 alpha 初始化读的就是它)和那张图(画在看得见的画布上)。 */
  const underlayRef = React.useRef<Loaded | null>(null);
  /** 底稿:打开时已经有的那张蒙版 —— **灰度**的那种才会走到这里(见 isGrayscaleImage)。 */
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
  /**
   * **画进蒙版的浓度**(蒙版的透明度 / 改动强度),默认满(`round(1 × 255)` = 纯白)。
   *
   * 和硬度是两件事:这个数是**颜色**(`inkColor`),硬度是那条软边的**宽度**(见文件头)。
   */
  const [opacity, setOpacity] = React.useState(1);
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
  /**
   * 扩张 / 羽化的当前值。`paint()` / `displayedMask()` 是终身不变的那个闭包(见下面),它们只能从
   * ref 里读到**这一刻**的参数 —— 直接读 state 的话拿到的是第一次渲染那一份。
   */
  const growRef = React.useRef(grow);
  const featherRef = React.useRef(feather);

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
   * 这一刻的扩张 / 羽化**还没有写进蒙版**吗(即"待应用")。
   *
   * 滑块非 0 只说明"参数不是空的";点过「应用到蒙版」的那一组参数已经在**这一版**蒙版里了
   * (`appliedEdgesRef`),那时再预览一遍就是多余的 —— 屏幕上该回到真蒙版。
   * 只读 ref:它是从 `paint()` 那条终身不变的闭包里被调的。
   */
  const edgesPending = () => {
    const grow = growRef.current;
    const feather = featherRef.current;
    if (grow === 0 && feather === 0) return false;
    const applied = appliedEdgesRef.current;
    return !(applied && applied.revision === writer().revision && applied.grow === grow && applied.feather === feather);
  };

  /**
   * 那份副本这一刻该按多大的分辨率算(当前文档 + 当前可见位图,见 `previewScale`)。
   *
   * 只在 ref 上读:它是从 `paint()` 那条终身不变的闭包里被调的。
   */
  const edgesScale = () => {
    const doc = writer().size;
    const view = viewRef.current;
    return previewScale(doc, { width: view?.width ?? 0, height: view?.height ?? 0 });
  };

  /**
   * 那份预览副本是"按哪一版蒙版 + 哪一组参数 + 哪一个分辨率"算的。任意一样变了,它就该重算。
   *
   * 分辨率也进 key:盒子换了大小(窗口变了)、位图尺寸还没量到时就画了一笔 —— 这两种情形下参数和
   * 蒙版版本都没变,可副本该按另一个分辨率算,不进 key 就会一直停在旧分辨率上(放大之后看着糊)。
   */
  const edgesKey = () => `${writer().revision}|${growRef.current}|${featherRef.current}|${edgesScale()}`;

  /**
   * 显示层该用哪张蒙版:**待应用**且副本就是**这一版**蒙版算的,才用它;否则用真蒙版。
   *
   * 这里**一个字都不写蒙版** —— 副本是另算的一张画布(见 `renderEdgesPreview`),真蒙版要等
   * 「应用到蒙版」才动。`key` 里带着 `MaskWriter.revision`,所以内容一变那份副本**当场作废** ——
   * 于是落笔期间屏幕上走的就是这一条:显示层直接喂真蒙版(当帧可见、不卡),预览等
   * `catchUpEdgesPreview` 追上来(见文件头「两条触发分开」)。宁可显示真蒙版,也不显示一份旧的。
   */
  const displayedMask = (): CanvasImageSource | null => {
    const preview = edgePreviewRef.current;
    if (!preview || !edgesPending() || preview.key !== edgesKey()) return writer().canvas();
    return preview.canvas;
  };

  /**
   * 算一份"边缘已经应用过"的副本,喂给显示层(真蒙版**只读**)。
   *
   * 蒙版那张画布**只读**(和显示层 `displayedMask` 拿它是同一条路):按**显示分辨率**(见 `previewScale`)
   * 把它缩进副本自己的画布 —— 缩放交给浏览器的原生重采样,比 `read()` 整张读回来(4432×1904 是
   * 33MB 的一份 `ImageData`)再自己抽稀便宜得多 —— 然后在**这份缩过的像素**上跑 `growMask` +
   * `featherMask`(纯函数,和「应用到蒙版」用的是同两条,半径按同一个比例缩)→ `putImageData`。
   *
   * 真蒙版那张从头到尾没人写:出口(`save()`)读的、写入口(`MaskContext`)发的,始终是它。
   */
  const renderEdgesPreview = () => {
    const ctx = maskContext();
    const source = writer().canvas();
    if (!ctx || !source || !edgesPending()) return;
    const doc = ctx.size;
    const scale = edgesScale();
    const width = Math.max(1, Math.round(doc.width * scale));
    const height = Math.max(1, Math.round(doc.height * scale));
    const canvas = edgePreviewRef.current?.canvas ?? document.createElement("canvas");
    if (canvas.width !== width || canvas.height !== height) {
      //: 改尺寸 = 换一张清空的位图(浏览器语义),下面重铺一遍。
      canvas.width = width;
      canvas.height = height;
    }
    const raw = canvas.getContext("2d");
    if (!raw) return;
    raw.globalAlpha = 1;
    raw.globalCompositeOperation = "source-over";
    //: 往小缩要平滑采样(默认就是开的,写明是因为缩得太狠时它决定了预览的软硬);
    raw.imageSmoothingEnabled = true;
    raw.clearRect(0, 0, width, height);
    raw.drawImage(source, 0, 0, doc.width, doc.height, 0, 0, width, height);
    const image = raw.getImageData(0, 0, width, height);
    //: 半径跟着降采样一起缩 —— 不缩的话 4 个**文档**像素会变成屏幕上的 4 个**副本**像素(放大后 8 个)。
    growMask(image.data, width, height, growRef.current * scale);
    featherMask(image.data, width, height, featherRef.current * scale);
    raw.putImageData(image, 0, 0);
    EDGE_PREVIEW_CANVASES.add(canvas);
    edgePreviewRef.current = { canvas, key: edgesKey() };
  };

  /**
   * 该算就**当场**算:参数或蒙版一变,这一帧画上屏的就是新副本。
   *
   * 谁调它:**参数变**(grow / feather 滑块那个 effect)直接调 —— 维护者要的实时手感,一个计时器
   * 都不等;内容变(画了一笔、撤销、清空)走 `syncEdgesPreview`,落笔期间不调它(见那个函数)。
   *
   * 副本按**显示分辨率**算(见 `previewScale`):维护者那张 4432×1904 上一次重算从 365ms(文档全
   * 分辨率)降到 90ms 上下(真 Chromium 实测,含画布读回)—— 即便如此也是一帧的五倍多,所以它
   * **不能**每帧都算。
   */
  const refreshEdgesPreview = () => {
    if (!edgesPending()) return;
    if (edgePreviewRef.current?.key === edgesKey()) return;
    renderEdgesPreview();
  };

  /**
   * 把当前状态画到看得见的那张画布上:底图原样在下面,要改的地方压暗 + 着蒙版色叠上去。
   *
   * **只读 ref** —— 所以这个函数在整个生命周期里是同一个,几个 effect 不会因为它的身份变化而重跑。
   * 两件"要从最新那几个闭包里拿"的事(圈的位置、预览副本该不该重算)走 ref 里的回调,见上面那两个 ref。
   */
  const paint = React.useCallback(() => {
    const view = viewRef.current;
    const ctx = view?.getContext("2d") ?? null;
    if (!view || !ctx) return;
    //: 画之前先把"待应用"的那份副本弄对:参数变当场算、正在画就**不**算(见 syncEdgesPreview)。
    edgesSyncRef.current();
    const underlay = underlayRef.current?.image ?? null;
    const scratch = scratchRef.current ?? (scratchRef.current = document.createElement("canvas"));
    const camera = cameraRef.current;
    const box = boxRef.current;
    drawMaskView(ctx, {
      plan: maskViewLayers({ hasUnderlay: Boolean(underlay), showUnderlay: showUnderlayRef.current, tint: tintRef.current }),
      mask: displayedMask(),
      underlay,
      scratch,
      width: view.width,
      height: view.height,
      place: camera && box ? placement(camera, writer().size, view.width / box.width) : undefined,
    });
    //: 相机、笔刷、文档边框的显示都挂在 `paint()` 上:它们只有 ref,不会自己发现变化(圈的大小尤其
    //: —— 缩放之后它还按上一个比例画)。
    placeFrame();
    ringSyncRef.current();
  }, [placeFrame]);

  /** 尾随那个定时器(`catchUpEdgesPreview` 排的)。null = 没有在等。 */
  const edgesTrailRef = React.useRef<number | null>(null);

  /** 撤掉尾随 —— 参数一变就当场算,不能让一个旧定时器回头再算一遍。 */
  const cancelEdgesTrail = () => {
    if (edgesTrailRef.current === null) return;
    clearTimeout(edgesTrailRef.current);
    edgesTrailRef.current = null;
  };

  /**
   * **笔迹告一段落**之后把预览追上去(尾随 `EDGE_PREVIEW_TRAILING_MS`)。
   *
   * 每一次落笔期间的 `paint()` 都重排一次(尾随 debounce):手不停就一次都不算,手停下来
   * (或松开)之后才追上。追上这一下自己再 `paint()` 一次 —— 松手之后没有别的东西会重画,
   * 不主动画的话屏幕上就永远停在真蒙版那一份上了。
   */
  const catchUpEdgesPreview = () => {
    cancelEdgesTrail();
    edgesTrailRef.current = window.setTimeout(() => {
      edgesTrailRef.current = null;
      refreshEdgesPreview();
      paint();
    }, EDGE_PREVIEW_TRAILING_MS);
  };

  /**
   * ### 扩张 / 羽化预览的**两条触发分开**(维护者:「设置扩张以后 绘制、画笔过程都会非常卡顿」)
   *
   * 病根:重算的判据里含**内容版本号**(`MaskWriter.revision`),而画笔**每一帧**都在 +1 ⇒ 预览每一帧
   * 都重算一次(显示分辨率下约 90ms)→ 画笔卡成幻灯片。现在:
   *
   * | 什么变了 | 怎么做 |
   * | --- | --- |
   * | **参数**(grow / feather 滑块) | **立刻**重算(那个 effect 直接调 `refreshEdgesPreview`),一个计时器都不等 |
   * | **内容**(正在画 / 撤销 / 清空) | 不每帧算:这一帧显示层用真蒙版(`displayedMask` 的 revision 判据已经保证了"旧副本不冒充"),笔画告一段落再追上(`catchUpEdgesPreview`) |
   *
   * "旧副本不再冒充"那条**没有被放松**:副本的 `key` 里仍然有 `revision`,内容一变它当场作废
   * —— 只是**追**得晚一点(尾随),不是让旧的那份继续顶包。
   */
  const syncEdgesPreview = () => {
    if (!edgesPending()) return;
    //: 正在画:这一帧不算,排一次尾随(手一停就追上)。
    if (drawingRef.current) {
      catchUpEdgesPreview();
      return;
    }
    //: 刚松手、还在尾随窗口里:别抢跑(参数变那条走的是 effect,不经过这里)。
    if (edgesTrailRef.current !== null) return;
    refreshEdgesPreview();
  };

  //: `paint()` 只读 ref(见它的说明),这三个回调得挂进 ref 里给它用。
  React.useEffect(() => {
    ringSyncRef.current = placeRing;
    edgesSyncRef.current = syncEdgesPreview;
  });

  /**
   * 卸载时撤掉还在等的那次尾随。
   *
   * 不撤的话,那个定时器会在**一个已经不在了的组件**上算一份没人看的预览(约 90ms 白算),
   * 而且它读的旧蒙版画布会被重新登记进测试的画布表 —— 下一条用例按尺寸找"蒙版那张"时可能
   * 摸到它(实测踩过:下一条用例摸到一张全黑的旧蒙版,断言全打在它上面)。
   */
  React.useEffect(
    () => () => {
      if (edgesTrailRef.current === null) return;
      clearTimeout(edgesTrailRef.current);
      edgesTrailRef.current = null;
    },
    [],
  );

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
      //: 文档换了 —— 上一份预览副本是按**上一张**蒙版算的,连同"哪一组参数已经应用过"一起作废,
      //: 还在等的那次尾随也撤掉(它算出来的会是旧文档那份分辨率/参数)。
      cancelEdgesTrail();
      edgePreviewRef.current = null;
      appliedEdgesRef.current = null;
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
    if (!open) {
      //: 关掉编辑器之后不再为一份没人看的预览算那 90ms(尾随只有这里和下面那条参数 effect 会撤)。
      cancelEdgesTrail();
      return;
    }
    paint();
  }, [open, showUnderlay, paint]);

  /**
   * 扩张 / 羽化滑块动了 = **参数变**:把当前值搬进 ref(那几条终身不变的闭包只读得到 ref),
   * 然后**当场**重算那份副本并重画一次 —— 一个计时器都不等(维护者要的实时手感)。
   *
   * 这里必须**直接**调 `refreshEdgesPreview`、不能只靠 `paint()`:拖动这类滑块时指针在右栏上、
   * 多半没有"正在画"这件事,但**万一**刚松手还在尾随窗口里,`syncEdgesPreview` 会让位给那个定时器
   * —— 参数变绝不能被内容那条的尾随挡住,所以先把尾随撤掉再当场算。
   *
   * 蒙版**内容**变(用户又画了一笔、撤销了)走的是 `paint()` 开头那条路(`syncEdgesPreview`),
   * 不在这里:那件事每一次画布刷新都要问一遍,而不只是滑块动的时候。
   */
  React.useEffect(() => {
    growRef.current = grow;
    featherRef.current = feather;
    if (!open) return;
    cancelEdgesTrail();
    refreshEdgesPreview();
    paint();
  }, [open, grow, feather, paint]);

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
      const [reference, slot] = await Promise.all([
        source ? loadImage(assetPreviewUrl(source.assetId)) : Promise.resolve(null),
        initial ? loadImage(assetPreviewUrl(initial.assetId)) : Promise.resolve(null),
      ]);
      if (!alive) return;
      //: 蒙版槽里那张图按**灰还是彩**分两条路(见文件头那一节):灰度的 = 已有的蒙版(底稿),
      //: 彩色的 = 一张参考图(底图)。判据在 `isGrayscaleImage`。
      const colorSlot = slot && !isGrayscaleImage(slot.data) ? slot : null;
      const draft = colorSlot ? null : slot;
      //: 优先级:参考图那一格(`source`,取参考图 / 首帧)在的时候**它就是**底图 —— 彩色 initial
      //: 不抢,只被忽略成底稿(不铺进蒙版,也不覆盖 source)。
      const underlay = reference ?? colorSlot;
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
   *
   * 写完之后把这一组参数记成"已经在这一版蒙版里了"(`appliedEdgesRef`):否则屏幕会把它**再预览一遍**
   * —— 应用完看到的比自己点下去时又扩张一次,正是"这一步到底写进去没有"说不清的那种画面。
   */
  const applyEdges = () => {
    transform((data, size) => {
      growMask(data, size.width, size.height, grow);
      featherMask(data, size.width, size.height, feather);
    });
    appliedEdgesRef.current = { revision: writer().revision, grow, feather };
    paint();
  };

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

  /**
   * 笔刷那个圈:屏幕上的真实大小(直径 × 相机缩放)+ **硬度那条曲线**,只有画笔和橡皮有。
   *
   * 位置取指针**上一次**在画布上的那一点(`ringPointRef`)而不是事件本身 —— 拖笔刷大小 / 硬度滑块时
   * 指针在右栏上,圈得在画布上原地跟着变(`paint()` 和那个 effect 都会调这里)。
   *
   * 它画的曲线和 `paintLine` 的软边是同一条(见 `brushRingFill`):内圈到 `radius × hardness` 是
   * 硬核,外面渐隐到半径那一圈。所以"拖硬度滑块"和"这一笔的边有多软"说的是同一件事。
   * **不透明度不进这里** —— 那是"画进蒙版多浓",和圈的形状/浓淡是两根滑块(见文件头那张表)。
   */
  const placeRing = React.useCallback(() => {
    const ring = ringRef.current;
    if (!ring) return;
    const local = ringPointRef.current;
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
    ring.style.background = brushRingFill(hardness);
  }, [brushSize, hardness, tool, panMode]);

  /** 指针动了 / 离开画布(`null`):记住它在哪,圈跟着走(或收起来)。 */
  const moveRing = (event: React.PointerEvent<HTMLCanvasElement> | null) => {
    ringPointRef.current = event ? localPoint(event) : null;
    placeRing();
  };

  //: 拖笔刷大小 / 硬度滑块、换工具、开始平移 —— 指针没动也要当场重画那个圈(它就是这两根滑块的反馈)。
  React.useEffect(() => {
    placeRing();
  }, [placeRing]);

  /**
   * 一笔的墨 —— **整笔一个颜色,浓度就是它**(见 `inkGray` / `inkColor`),软边那端见 `inkFade`。
   *
   * - 画笔、矩形、椭圆:**不透明度**那个灰度(1 → `rgb(255 255 255)`、0.5 → `rgb(128 128 128)`、
   *   0 → 黑 = 涂不上)—— **形状和画笔共用同一条定义**;
   * - 橡皮:写黑(`0` = 这块不改),**不吃不透明度**(理由见文件头「橡皮不吃不透明度」);
   *   它照样吃**硬度** —— 那是边缘过渡,不是擦除力度。
   *
   * 颜色算在**这一笔**上(而不是每个 dab 各算一次),所以整条笔迹 —— 包括来回描的那几趟 —— 都是
   * 同一个值,重叠的 dab 只是把同一个不透明色再铺一遍。
   */
  const inkOf = (kind: Tool, opacity: number) =>
    kind === "eraser" ? { ink: BLACK, fade: ERASER_FADE } : { ink: inkColor(opacity), fade: inkFade(opacity) };

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
      const { ink, fade } = inkOf(tool, opacity);
      ctx.stroke((raw) => paintLine(raw, at, at, brushSize / 2, hardness, ink, fade));
    } else {
      ctx.beginStroke();
      ctx.preview((raw) => paintShape(raw, tool, at, at, inkOf(tool, opacity).ink, hardness, brushSize / 2));
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
      const { ink, fade } = inkOf(drag.tool, opacity);
      ctx.stroke((raw) => paintLine(raw, drag.last, at, brushSize / 2, hardness, ink, fade));
    } else {
      //: 形状工具每一帧都从按下时那份像素重来:看到的是「松手后会是这样」,不是一层层叠上去的边。
      ctx.preview((raw) => paintShape(raw, drag.tool, drag.from, at, inkOf(drag.tool, opacity).ink, hardness, brushSize / 2));
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
            {/*: 文档的边框与笔刷圈:纯显示,不接指针(事件全落在画布上)。位置由相机写(placeFrame / moveRing)。
                那个圈的**填充**就是硬度(内圈硬核、外面渐隐,连墨的浓淡一起,见 brushRingFill / ringInk);
                **不透明度不进这里** —— 它管的是画进蒙版多浓,不是圈的软硬。
                className 里**不放** border / shadow —— 写死的边会把那份填充盖住,拖硬度就什么也看不出来
                (维护者两次报的都是这一条,第一次是"没写填充",第二次是"填充被硬边盖着")。 */}
            <div
              ref={frameRef}
              data-mask-doc-frame=""
              hidden
              aria-hidden
              className="pointer-events-none absolute left-0 top-0 origin-top-left rounded-[1px] outline outline-1 outline-border-strong"
            />
            <div
              ref={ringRef}
              data-mask-brush-ring=""
              hidden
              aria-hidden
              className="pointer-events-none absolute left-0 top-0 rounded-full"
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
              {/*: 浓度那一根**紧跟**在硬度下面(维护者定的面板顺序):硬度管边缘过渡,这根管画进蒙版多浓。 */}
              <SliderField label={t("maskBrushOpacity")} value={opacity} min={0} max={1} step={0.05} format={percent} onChange={setOpacity} />
              <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("maskBrushOpacityHint")}</p>
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
                {/* 标签窄了就省略号 + 悬停给全文(Button 基类 whitespace-nowrap 会直接切掉);禁用时 Hint 靠 disabledReason
                    套一层壳才收得到悬停。 */}
                <Hint label={t("maskFromLuminance")} disabledReason={hasUnderlay ? undefined : t("maskFromNeedsImage")}>
                  <Button variant="outline" className="w-full min-w-0" disabled={!hasUnderlay} onClick={() => pressFromSource("luminance")}>
                    <SunMedium />
                    <Truncate>{t("maskFromLuminance")}</Truncate>
                  </Button>
                </Hint>
                <Hint label={t("maskFromAlpha")} disabledReason={hasUnderlay ? undefined : t("maskFromNeedsImage")}>
                  <Button variant="outline" className="w-full min-w-0" disabled={!hasUnderlay} onClick={() => pressFromSource("alpha")}>
                    <Droplets />
                    <Truncate>{t("maskFromAlpha")}</Truncate>
                  </Button>
                </Hint>
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
