import { MarkerType } from "@xyflow/react";

/**
 * 画布连线的**唯一一套外观**。工作流(主图、循环体/子图里那一层)和创意画板都从这里取。
 *
 * 此前连线的样子散在五处,各说各的:画板吃 xyflow 默认的 1px 灰;工作流在 workflowCanvasSkin
 * 里按语义另写一套颜色和线宽;条件分支的彩色箭头在 workflowCanvasModel 里单造;运行走过的线在
 * WorkflowsView 里用行内 style 写死 success + 2.4px(于是选中它时不变主色);待定的线和拖线途中
 * 那根又各有一份行内样式。线宽 1.5 / 2 / 2.2 / 2.4 / 2.6 五个数,箭头是 4.5×7px 的一粒芝麻。
 *
 * **一张表说完所有变体。** 意思不同的才长得不同;同一件事(线宽档、线帽、箭头大小、悬停、选中)
 * 在每一种上都一样:
 *
 * | 变体            | 类名(`canvasEdgeClass`)              | 意思                                   | 样子                                   |
 * |-----------------|---------------------------------------|----------------------------------------|----------------------------------------|
 * | 引用 / 控制流   | (无)                                  | 画板:上游 → 下游;工作流:执行顺序       | `--canvas-edge` 实线 + 闭合箭头        |
 * | 条件为真        | `canvas-edge-true`                    | 条件节点「真」那一路                     | `--success` 实线 + 箭头 + 「真」标签   |
 * | 条件为假        | `canvas-edge-false`                   | 条件节点「假」那一路                     | `--destructive` 实线 + 箭头 + 「假」标签 |
 * | 数据            | `canvas-edge-data canvas-edge-flow`   | 端口之间传值(不是执行顺序)               | `--primary` 流动虚线,无箭头            |
 * | 类型对不上      | `canvas-edge-mismatch canvas-edge-flow` | 数据线两端类型不兼容(软提示,不拦)      | `--warning` 流动虚线,无箭头            |
 * | 运行走过        | `canvas-edge-taken`(数据线再带 flow) | 上一次运行真的走了这根                   | `--success`,线宽取选中档               |
 * | 待定            | `canvas-edge-pending`                 | 拉线松手在空白处,等你在单子上选一种      | `--primary` 静止虚线 + 箭头            |
 * | 拖线途中        | (xyflow 的 connection line)          | 正在拉                                   | 和「待定」同一个样子                   |
 * | 悬停            | `:hover`                              | 指针在这根线上                           | 本色往 `--foreground` 走一截,线宽 2.5  |
 * | 选中            | `.selected`                           | 选中了这根                               | `--primary`,线宽 2.75                  |
 *
 * 几条定下来的取舍:
 *  · **数据线不画箭头。** 它的方向由流动的虚线说(从出口流向入口);入口是一列挨着的小接点,
 *    每根都挂一个 13px 宽的箭头会在那一列上叠成一团。
 *  · **颜色互斥,图案另算。** 一根线只挂一个颜色类(true/false/data/mismatch/taken/pending 之一),
 *    「流动虚线」是单独的 `canvas-edge-flow`。于是「数据线跑过了」= taken + flow,颜色由调用方
 *    一次定好,不靠两条同权重规则谁后生成谁赢。
 *  · 意思相同的状态色**复用同一个令牌**:「真」和「运行走过」都是 success —— 走过的线靠更粗那一档
 *    和它两头节点的运行状态区分。
 *
 * 怎么接进来:
 *  1. 画布外层容器挂 `CANVAS_EDGE_CLASS`(颜色、线宽、悬停/选中、各变体、拖线途中的样子、点阵)。
 *  2. 每条边带上 `CANVAS_EDGE_OPTIONS`(箭头、命中宽度)—— 工作流经 defaultEdgeOptions,画板在渲染时贴。
 *  3. 有语义的边挂 `canvasEdgeClass(...)` 的类名。**别处不写线色、线宽、箭头、虚线** —— 棘轮见
 *     components/app/canvasEdges.test.ts。
 */

/** 线宽(画布坐标里的 px,跟着缩放)。三档:平时、悬停、选中(以及「运行走过」)。 */
export const CANVAS_EDGE_WIDTH = { rest: 2, hover: 2.5, selected: 2.75 } as const;

/** 一根线的颜色(互斥,见上表)。`reference` 是默认的那种,不挂类。 */
export type CanvasEdgeTone = "reference" | "true" | "false" | "data" | "mismatch" | "taken" | "pending";

/**
 * 一根线该挂的类名。`flow`:流动虚线(数据线)。没有要挂的就回 undefined —— React Flow 的
 * className 是可选的,给空串会在 DOM 上留一个 `class="react-flow__edge "`。
 */
export function canvasEdgeClass(tone: CanvasEdgeTone, { flow = false }: { flow?: boolean } = {}): string | undefined {
  const classes = [tone === "reference" ? null : `canvas-edge-${tone}`, flow ? "canvas-edge-flow" : null].filter(Boolean);
  return classes.length > 0 ? classes.join(" ") : undefined;
}

/**
 * 挂在画布外层容器上的那一串。
 *
 * **颜色和线宽走 xyflow 公开的 CSS 变量**(`--xy-edge-stroke*`):在祖先上设、往下继承,
 * xyflow 自己的规则(包括选中态读 `--xy-edge-stroke-selected`)照常工作;各变体只在自己那根线上
 * 改 `--xy-edge-stroke`。选中态是 xyflow 那条 `.selected .react-flow__edge-path` 规则,它读的是
 * 另一个变量,所以任何颜色的线选中后都是主色,不必每种变体各写一遍。
 *
 * **只有悬停直接写 `stroke`**:它要的是「这根线**自己的**颜色再往前景色走一截」—— 灰线更深,
 * 绿线更绿,语义色不能被一个统一的悬停色盖掉。变量做不到(`--xy-edge-stroke` 引用它自己是个环),
 * 所以写在路径上、拿继承下来的 `--xy-edge-stroke` 混色;带 `:not(.selected)`,选中的线悬停时
 * 还是主色。xyflow 的样式在 vendor 层(见 design/tokens.css 开头),工具类压得过它。
 *
 * 「运行走过」的线宽多带一级 `.react-flow__edges`:悬停/选中改线宽的规则是 (0,3,0),同权重时谁赢
 * 看生成顺序 —— 不赌这个,直接高一级。
 *
 * **每一项都得是字面量。** Tailwind 是从源码文本里扫类名的,`[--xy-edge-stroke-width:${w}]` 这种
 * 插值它看不见、也就不生成规则。线宽的数字和 `CANVAS_EDGE_WIDTH` 对不对得上,由测试核对。
 *
 * 点阵也在这里:线看不看得清是**相对点阵**而言的,两者的颜色一起定(令牌见 tokens.css)。
 *
 * 选择器里的下划线写成 `\_\_`,整串 String.raw:Tailwind 把任意值里的 `_` 换成空格,
 * `.react-flow__edge` 会变成 `.react-flow  edge`;普通字符串里的 `\_` 又会被 JS 吃掉反斜杠。
 */
export const CANVAS_EDGE_CLASS = [
  // 平时:线色、线宽、选中色,拖线途中那根,点阵。
  "[--xy-edge-stroke:var(--canvas-edge)]",
  "[--xy-edge-stroke-width:2]",
  "[--xy-edge-stroke-selected:var(--primary)]",
  "[--xy-connectionline-stroke:var(--primary)]",
  "[--xy-connectionline-stroke-width:2]",
  "[--xy-background-pattern-color:var(--canvas-dot)]",
  // 线帽线角一律圆的;颜色和线宽的变化带一点过渡。
  String.raw`[&_.react-flow\_\_edge-path]:[stroke-linecap:round]`,
  String.raw`[&_.react-flow\_\_edge-path]:[stroke-linejoin:round]`,
  String.raw`[&_.react-flow\_\_edge-path]:[transition:stroke_120ms,stroke-width_120ms]`,
  String.raw`[&_.react-flow\_\_connection-path]:[stroke-linecap:round]`,
  // 悬停、选中。
  String.raw`[&_.react-flow\_\_edge:hover]:[--xy-edge-stroke-width:2.5]`,
  String.raw`[&_.react-flow\_\_edge.selected]:[--xy-edge-stroke-width:2.75]`,
  String.raw`[&_.react-flow\_\_edge:not(.selected):hover_.react-flow\_\_edge-path]:[stroke:color-mix(in_oklab,var(--xy-edge-stroke)_62%,var(--foreground))]`,
  // 各变体的颜色(互斥)。
  "[&_.canvas-edge-true]:[--xy-edge-stroke:var(--success)]",
  "[&_.canvas-edge-false]:[--xy-edge-stroke:var(--destructive)]",
  "[&_.canvas-edge-data]:[--xy-edge-stroke:var(--primary)]",
  "[&_.canvas-edge-mismatch]:[--xy-edge-stroke:var(--warning)]",
  "[&_.canvas-edge-taken]:[--xy-edge-stroke:var(--success)]",
  "[&_.canvas-edge-pending]:[--xy-edge-stroke:var(--primary)]",
  String.raw`[&_.react-flow\_\_edges_.react-flow\_\_edge.canvas-edge-taken]:[--xy-edge-stroke-width:2.75]`,
  // 图案:数据线流动的虚线(周期 11,和 edge-flow 动画的位移一致;减少动态效果时停住);
  // 待定的线和拖线途中那根是静止的虚线 —— 圆线帽让每段两头各长出半个线宽,`4 6` 看上去是 6 实 4 空。
  String.raw`[&_.canvas-edge-flow_.react-flow\_\_edge-path]:[stroke-dasharray:6_5]`,
  String.raw`[&_.canvas-edge-flow_.react-flow\_\_edge-path]:motion-safe:animate-edge-flow`,
  String.raw`[&_.canvas-edge-pending_.react-flow\_\_edge-path]:[stroke-dasharray:4_6]`,
  String.raw`[&_.react-flow\_\_connection-path]:[stroke-dasharray:4_6]`,
  // 边上的字(条件分支的「真/假」)。
  "[--xy-edge-label-background-color:var(--panel)]",
  "[--xy-edge-label-color:var(--muted-foreground)]",
  String.raw`[&_.react-flow\_\_edge-text]:text-[9.5px]`,
].join(" ");

/**
 * 连线末端的闭合箭头:方向一目了然(上游 → 下游)。**所有带箭头的边共用这一个。**
 *
 *  · **颜色是 `context-stroke`**:箭头取「引用它的那条线」此刻的描边色。于是悬停变深、选中变
 *    主色、真绿假红、运行走过、待定的主色,箭头都和线同色 —— 不必再按语义各造一个彩色箭头(此前
 *    条件分支各造了一个,选中时线变主色、箭头还是绿的,成了两截)。xyflow 把它写进箭头的行内
 *    样式;认不得这个值的浏览器丢掉那两条声明,落回 xyflow 自己那条
 *    `.react-flow__arrowhead polyline { stroke: var(--xy-edge-stroke) }`,即中性的线色。
 *  · **尺寸按画布坐标定(`userSpaceOnUse`),不按线宽倍数。** xyflow 默认的 `strokeWidth` 单位让箭头
 *    跟着线宽走:12 × 1.5px 的线,画出来的三角只有 4.5×7px;悬停加粗时它还会一胀一缩。
 *    30 = 20 格的 viewBox 放大 1.5 倍:箭头约 9×13px,是 2px 线宽的四五倍,缩到 0.8 看全图时也还是
 *    一个清楚的三角;悬停/选中时不变。
 *  · 尖端就是线的终点(xyflow 的 refX=0),终点就是接点:画板的接点贴边,尖端正好顶在节点边框上;
 *    工作流的接点是骑在边框上的小圆,尖端顶在圆的外沿。线头的圆帽藏在节点卡片底下。
 */
export const CANVAS_EDGE_MARKER = {
  type: MarkerType.ArrowClosed,
  width: 30,
  height: 30,
  markerUnits: "userSpaceOnUse",
  color: "context-stroke",
} as const;

/**
 * 每条边都带的那几项(工作流经 defaultEdgeOptions,画板在渲染时贴上)。
 *
 * `interactionWidth`:线旁那条看不见的命中带。2px 的线很难瞄准,24 让指针离线 12px 以内就算
 * 悬停/点中。它在连线那一层,节点卡片压在上面,不会抢走接点和卡片的点击。
 */
export const CANVAS_EDGE_OPTIONS = { markerEnd: CANVAS_EDGE_MARKER, interactionWidth: 24 } as const;

/**
 * 列表卡片上那张缩略图里的线(components/layout/CanvasPreview —— 不是 React Flow,是一张静态 SVG)。
 * 和画布上同一个线色;线宽不随缩略图缩放,所以取细一档。
 */
export const CANVAS_PREVIEW_EDGE = {
  stroke: "var(--canvas-edge)",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  vectorEffect: "non-scaling-stroke",
} as const;
