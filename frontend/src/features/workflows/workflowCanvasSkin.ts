/**
 * 工作流画布的皮肤:按连线的**语义**上色(条件分支的真/假、数据线、类型不匹配),以及边标签、
 * 背景、署名这些 React Flow 自带部件的主题色。挂在画布外层容器上,和共用的 `CANVAS_EDGE_CLASS`
 * (线宽、选中/悬停、箭头)叠着用。
 *
 * 这一串此前内联在 WorkflowsView 里,**一条都没生效**:真/假分支始终是和普通线一样的灰,数据线
 * 既不是主色也没有加粗。两个原因叠在一起,任何一个都足以让它失效:
 *
 *  1. 选择器里的 `__` 没转义 —— Tailwind 把任意值里的 `_` 换成空格,`.react-flow__edge-path`
 *     变成 `.react-flow  edge-path`,选不中任何东西。
 *  2. React Flow 的 style.css 当时不在任何层里,不分层的声明压过 `@layer utilities`。
 *     现在它在 `layer(vendor)` 里(见 design/tokens.css 开头),这一条已经从根上解决。
 *
 * **规则**(两道棘轮盯着:design/vendorStyles.test.ts、design/arbitrarySelectors.test.ts):
 *  · 颜色、线宽先找 React Flow 公开的 `--xy-*` 变量 —— 在祖先上设、往下继承,和它自己的规则
 *    (包括选中态读 `--xy-edge-stroke-selected`)一起工作,不和它抢同一个属性。
 *  · 变量够不着的(虚线节奏、字号、描边的动画)才直接写属性。
 *  · 选择器里的下划线一律写 `\_`,整串用 String.raw —— 普通字符串里的 `\_` 会被 JS 吃掉反斜杠。
 *
 * 语义类名(`wf-edge-true` / `wf-edge-false` / `wf-edge-data` / `wf-edge-mismatch`)由
 * workflowCanvasModel 的 `toWorkflowFlowEdges` 挂到每条边上;这里只认类名,不关心边从哪来。
 */
export const WORKFLOW_CANVAS_CLASS = [
  // React Flow 自带部件:背景、边标签、右下角署名。
  "[--xy-background-color:var(--background)]",
  "[--xy-edge-label-background-color:var(--panel)]",
  "[--xy-edge-label-color:var(--muted-foreground)]",
  String.raw`[&_.react-flow\_\_edge-text]:text-[9.5px]`,
  "[--xy-attribution-background-color:color-mix(in_srgb,var(--panel)_70%,transparent)]",
  String.raw`[&_.react-flow\_\_attribution_a]:text-muted-foreground`,
  // 条件分支:真绿、假红 —— 和节点上那两个接点、「真/假」两个字同一个颜色。
  "[&_.wf-edge-true]:[--xy-edge-stroke:var(--success)]",
  "[&_.wf-edge-false]:[--xy-edge-stroke:var(--destructive)]",
  // 数据线:主色、加粗、流动的虚线;类型对不上时换成警示色(软提示,不拦连线)。
  "[&_.wf-edge-data]:[--xy-edge-stroke:var(--primary)]",
  "[&_.wf-edge-data]:[--xy-edge-stroke-width:2]",
  "[&_.wf-edge-data.wf-edge-mismatch]:[--xy-edge-stroke:var(--warning)]",
  //: 多带一个 `.react-flow__edge`:共用那串里「选中加粗到 2.2」是 (0,3,0),同权重时谁赢看
  //: 生成顺序 —— 不赌这个,直接高一级。
  String.raw`[&_.react-flow\_\_edge.wf-edge-data.selected]:[--xy-edge-stroke-width:2.6]`,
  String.raw`[&_.wf-edge-data_.react-flow\_\_edge-path]:[stroke-dasharray:6_5]`,
  String.raw`[&_.wf-edge-data_.react-flow\_\_edge-path]:animate-wf-dash`,
].join(" ");

/**
 * 节点的控制流接点(进 / 出 / 条件的真假两路)。
 *
 * 悬停放大要**连同 React Flow 自己的居中位移一起写**:它用 transform 把接点骑在边线上
 * (`.react-flow__handle-left` 是 translate(-50%,-50%)),只写 scale 会把接点从边线上挪开。
 * 此前这两条选择器没转义下划线,悬停放大从来没发生过。
 *
 * 不再需要 `!`:React Flow 的样式在 vendor 层,工具类本来就压得过它。
 */
export const WORKFLOW_HANDLE_CLASS = String.raw`h-[9px] w-[9px] rounded-full border-[1.5px] border-border-strong bg-panel transition-[border-color,transform] duration-100 after:absolute after:-inset-[7px] after:rounded-full after:content-[''] hover:border-primary group-hover/node:border-primary [&.react-flow\_\_handle-left:hover]:[transform:translate(-50%,-50%)_scale(1.35)] [&.react-flow\_\_handle-right:hover]:[transform:translate(50%,-50%)_scale(1.35)]`;
