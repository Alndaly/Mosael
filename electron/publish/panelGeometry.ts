import { EMBED_HEADER_HEIGHT } from "./types";

/**
 * 后台任务的「悬浮面板」几何:卡片多大、能多大多小、拖哪个手柄时哪个点不动。
 *
 * 纯函数,不碰 Electron —— AccountViewManager 拿窗口内容区尺寸来调,测试直接喂数字。
 *
 * 卡片里嵌一个内缩 4px、让出 26px 标题条的原生视图;缩放按「视图宽 / layoutWidth」反算,于是页面
 * **布局视口恒为 1280 宽**,平台页面按桌面版排版,显示只占右下角一小块。这不是美观取舍,是必要
 * 条件:面板若不缩放地做成 384 宽,B 站会渲染窄屏版布局,选择器与整个流程都会变。
 *
 * 为什么要挂进窗口而不是留在后台:只有**参与合成**的视图才有真实布局和可用的命中测试 —— 挂上去
 * 之后真实指针输入(isTrusted=true)才生效,同时画面也是真的,不必再靠截图镜像。实测三个面板
 * 叠放(后加的压住先加的)时,被完全遮挡的那个照样有 1280×800 视口、照样能被可信点击命中。
 */
export const PANEL = {
  /** 卡片(含标题条与边框)的默认宽度。高不单独记:由宽按页面比例算出(见 panelHeightFor)。 */
  width: 384,
  /** React 在卡片顶部画的标题条高度 —— 原生视图从这条下面开始。 */
  header: 26,
  /** 视图四周相对卡片内缩。卡片圆角 R 时,内缩需 ≥ 0.293R 才不让视图的直角戳出圆弧;
   *  R=12 → 3.5px,取 4px。原生 View 没有 setBorderRadius(Electron 32 只有 setBackgroundColor /
   *  setBounds / setVisible),圆角与阴影只能由渲染层画在视图**下方**(子视图永远盖在宿主页面之上)。
   *  这 4px 也是渲染层收得到鼠标的那圈边:缩放手柄的热区就压在它上面。 */
  inset: 4,
  /** 卡片圆角。**只有这一份**:经 IPC 随面板状态下发(见 layout),渲染层用收到的值,
   *  不自己写一个 —— 这里改了前端跟着变,不存在两边要记得一起改的问题。 */
  radius: 12,
  margin: 16,
  stackOffset: 22,
  /** 页面要按这个宽度布局(桌面版)。缩放由「视图实际宽度 / 这个值」反算,而不是写死 0.3 —— 卡片
   *  尺寸一改,写死的比例就会让布局视口偏掉。 */
  layoutWidth: 1280,
  /** 页面布局视口的高。与 layoutWidth 一起定死面板的宽高比 —— 面板里永远是完整的桌面版视口。 */
  layoutHeight: 800,
  /** 面板最大占窗口的比例。它是「边跑边看」的东西,不该把整个应用吞掉(实测拖到几乎满屏,什么都点不了)。 */
  maxWindowFraction: 0.6,
  /** 最小宽度:再小就既看不清、也让标题条上的按钮挤成一团。 */
  minWidth: 240,
} as const;

/**
 * 面板的几何状态。**尺寸是一个标量(宽),不是两个** —— 高按页面比例跟着宽走。
 *
 * 为什么:面板里的页面布局视口恒为 1280 宽,缩放 = 视图宽 / 1280。若高能单独改,改的就不是
 * "多露一截",而是**页面视口本身的高** —— 1280×600 或 1280×1200 的桌面页面:100vh、懒加载、
 * 「元素是否在可视区」全跟着变,而 RPA / 智能体正在这个视口里跑,面板挂不上时的兜底视口又是
 * 固定的 1280×800(publishWorker 的 BACKGROUND_VIEWPORT)。锁住比例之后,面板上的每个手柄都只有
 * 一个含义:这块面板要多大 —— 里面永远是完整的 1280×800 桌面视口,没有"下面空一截"或"底部被切掉"。
 *
 * x/y 为 null 表示「贴右下角」(默认);拖过或缩放过之后记住绝对位置。两者总是同时为 null 或同时有值。
 */
export interface PanelLayout {
  x: number | null;
  y: number | null;
  width: number;
}

/** 窗口内容区尺寸。面板只能落在它里面,且不压住顶部那条工具栏(EMBED_HEADER_HEIGHT)。 */
export interface PanelArea {
  width: number;
  height: number;
}

export interface PanelRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 缩放手柄:四角 + 四边,按罗盘方位命名。 */
export type PanelHandle = "n" | "ne" | "e" | "se" | "s" | "sw" | "w" | "nw";

export const DEFAULT_PANEL_LAYOUT: PanelLayout = { x: null, y: null, width: PANEL.width };

/** 视图区(也就是页面视口)的高宽比。 */
const RATIO = PANEL.layoutHeight / PANEL.layoutWidth;
/**
 * 卡片高 = 视图高 + 标题条 + 底边内缩,视图宽 = 卡片宽 − 两侧内缩;展开就是一条直线
 * 「高 = RATIO · 宽 + CHROME」。拖角时要在这条线上找离指针最近的点,所以把截距单独写出来。
 */
const CHROME = PANEL.header + PANEL.inset - PANEL.inset * 2 * RATIO;

/** 卡片宽 → 卡片高:视图区保持页面视口的比例。 */
export function panelHeightFor(width: number): number {
  return Math.round((width - PANEL.inset * 2) * RATIO) + PANEL.header + PANEL.inset;
}

/** panelHeightFor 的反函数。不取整 —— 调用方按自己的语义取整(上限要向下取,免得反算回去超出)。 */
function widthForHeight(height: number): number {
  return (height - CHROME) / RATIO;
}

/** 这扇窗口里面板最多能多宽:宽、高两条上限都折算成宽,取小的那个。 */
function maxWidthIn(area: PanelArea): number {
  const maxWidth = Math.min(area.width - PANEL.margin * 2, Math.round(area.width * PANEL.maxWindowFraction));
  const maxHeight = Math.min(
    area.height - EMBED_HEADER_HEIGHT - PANEL.margin,
    Math.round(area.height * PANEL.maxWindowFraction),
  );
  return Math.min(maxWidth, Math.floor(widthForHeight(maxHeight)));
}

/**
 * 夹宽度:先按 `room`(缩放时锚点到窗口边还剩的地方),再保最小宽度,最后上限说了算 ——
 * 窗口小到连最小尺寸都放不下时,面板也不能比窗口的上限还大。
 */
function clampWidth(width: number, area: PanelArea, room = Number.POSITIVE_INFINITY): number {
  const wanted = Math.min(Math.round(width), Math.floor(room));
  return Math.min(Math.max(PANEL.minWidth, wanted), maxWidthIn(area));
}

/** 卡片左上角夹进窗口:不出左右边,不压顶部工具栏,不掉出底边。 */
function clampOrigin(x: number, y: number, width: number, area: PanelArea): { x: number; y: number } {
  const height = panelHeightFor(width);
  return {
    x: Math.min(Math.max(0, Math.round(x)), Math.max(0, area.width - width)),
    y: Math.min(
      Math.max(EMBED_HEADER_HEIGHT, Math.round(y)),
      Math.max(EMBED_HEADER_HEIGHT, area.height - height),
    ),
  };
}

/** 面板此刻在窗口里的矩形(默认位置在这里落成绝对坐标)。卡片堆最上面那张就是它。 */
export function panelRect(layout: PanelLayout, area: PanelArea): PanelRect {
  const height = panelHeightFor(layout.width);
  return {
    x: layout.x ?? Math.max(0, area.width - layout.width - PANEL.margin),
    y: layout.y ?? Math.max(EMBED_HEADER_HEIGHT, area.height - height - PANEL.margin),
    width: layout.width,
    height,
  };
}

/**
 * 卡片堆:最上面那张落在 layout 上,下面的每层往上错开 stackOffset,露出各自的标题条 —— 看得出
 * 同时有几路在跑,也点得到它们的关闭。
 *
 * **所有网页(原生视图)都叠在最上面那张的网页区域里**(`page`)。原生视图永远盖在渲染层之上:
 * 下层的网页只要跟着卡片错开、露出一截,就必然压在别的卡片的界面上 —— 此前下层网页从上层卡片的
 * y+4 开始,正好盖住上层标题条的 y+4..y+26,上层的拖动、静音、关闭和上边的缩放手柄全点不到;
 * 更下一层又盖住中间那层露出来的标题条。只有完全藏在最上面那张网页的后面,才哪儿都不压。
 *
 * 藏在后面不等于停掉:被完全遮挡的视图照样参与合成、照样是同样大小的 1280×800 视口、照样能被
 * 可信输入命中(见 PANEL 的说明)—— 此前它们本来就有大半张压在上层下面,现在是整张。
 */
export function panelStack(
  layout: PanelLayout,
  area: PanelArea,
  count: number,
): { cards: PanelRect[]; page: PanelRect } {
  const top = panelRect(layout, area);
  // 错开量有上限:露出来的标题条不能顶进窗口顶部的工具栏。
  const deepest = Math.max(0, Math.floor((top.y - EMBED_HEADER_HEIGHT) / PANEL.stackOffset));
  const cards = Array.from({ length: count }, (_, index) => {
    const depth = Math.min(count - 1 - index, deepest);
    return { ...top, y: Math.max(EMBED_HEADER_HEIGHT, top.y - depth * PANEL.stackOffset) };
  });
  const page = {
    x: top.x + PANEL.inset,
    y: top.y + PANEL.header,
    width: top.width - PANEL.inset * 2,
    height: top.height - PANEL.header - PANEL.inset,
  };
  return { cards, page };
}

/** 把一份(可能来自上次运行的)几何夹进当前窗口 —— 窗口可能比上次小。 */
export function fitPanelLayout(layout: PanelLayout, area: PanelArea): PanelLayout {
  const width = clampWidth(layout.width, area);
  if (layout.x === null || layout.y === null) return { x: null, y: null, width };
  return { ...clampOrigin(layout.x, layout.y, width, area), width };
}

/** 拖标题条:只改位置,尺寸不动。 */
export function movePanel(layout: PanelLayout, to: { x: number; y: number }, area: PanelArea): PanelLayout {
  return { ...clampOrigin(to.x, to.y, layout.width, area), width: layout.width };
}

/**
 * 每个手柄拖动时**不动的那个点**,以它在卡片里的相对位置表示(0 = 左/上,1 = 右/下)。
 * 拖角:对角不动。拖边:对边的**中点**不动 —— 尺寸是一个标量,拖右边时高也在变,它从对边中点
 * 往上下对称地长,而不是偏向某一侧。
 */
const ANCHOR: Record<PanelHandle, { fx: number; fy: number }> = {
  nw: { fx: 1, fy: 1 },
  n: { fx: 0.5, fy: 1 },
  ne: { fx: 0, fy: 1 },
  e: { fx: 0, fy: 0.5 },
  se: { fx: 0, fy: 0 },
  s: { fx: 0.5, fy: 0 },
  sw: { fx: 1, fy: 0 },
  w: { fx: 1, fy: 0.5 },
};

/**
 * 拖手柄缩放。
 *
 * `requested` 是指针把那条边 / 那个角拖到的位置所围成的矩形,**不带任何约束**(渲染层只管
 * 「起手时的卡片 + 指针位移」)。比例、上下限、窗口边界都在这里定 —— 规则只有一份。
 *
 * 锚点从 `requested` 取而不是从当前几何取:前者在整次拖动里恒定(手柄对面那条边 / 那个角
 * 指针没碰过),后者每一步都经过取整,中点锚会一像素一像素地漂。
 */
export function resizePanel(handle: PanelHandle, requested: PanelRect, area: PanelArea): PanelLayout {
  const { fx, fy } = ANCHOR[handle];
  const anchorX = requested.x + fx * requested.width;
  const anchorY = requested.y + fy * requested.height;
  const width = clampWidth(requestedWidth(handle, requested), area, roomFrom(anchorX, anchorY, fx, fy, area));
  const height = panelHeightFor(width);
  return { ...clampOrigin(anchorX - fx * width, anchorY - fy * height, width, area), width };
}

/** 指针要的矩形折算成一个宽度(高随宽)。 */
function requestedWidth(handle: PanelHandle, requested: PanelRect): number {
  switch (handle) {
    case "e":
    case "w":
      return requested.width;
    case "n":
    case "s":
      return widthForHeight(requested.height);
    default:
      // 拖角:卡片的角只能沿「锚点 → 角」那条斜线走(宽高按比例)。取斜线上离指针最近的点 ——
      // 在宽高平面里就是 (requested.width, requested.height) 到直线「高 = RATIO·宽 + CHROME」的垂足。
      // 只看横向或只看纵向都不行:只取较大者时横着往里拖缩不小,只取较小者时横着往外拖放不大。
      return (requested.width + RATIO * (requested.height - CHROME)) / (1 + RATIO * RATIO);
  }
}

/**
 * 从锚点往手柄那一侧,窗口还剩多少地方 —— 折算成宽度上限。锚点不动是对用户的承诺,所以撞到
 * 窗口边时是尺寸停下,而不是把整块卡片推走(推走的话,手柄就不在指针底下了)。
 */
function roomFrom(anchorX: number, anchorY: number, fx: number, fy: number, area: PanelArea): number {
  const limits: number[] = [];
  if (fx > 0) limits.push(anchorX / fx);
  if (fx < 1) limits.push((area.width - anchorX) / (1 - fx));
  if (fy > 0) limits.push(widthForHeight((anchorY - EMBED_HEADER_HEIGHT) / fy));
  if (fy < 1) limits.push(widthForHeight((area.height - anchorY) / (1 - fy)));
  return Math.min(...limits);
}
