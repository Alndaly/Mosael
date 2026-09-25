/**
 * 工作流画布的皮肤:React Flow 自带部件(背景、右下角署名)的主题色,以及节点接点的样子。
 * 挂在画布外层容器上,和共用的 `CANVAS_EDGE_CLASS` 叠着用。
 *
 * **连线不在这里。** 线色、线宽、箭头、按语义的变体(条件的真/假、数据线、类型不匹配、运行走过)
 * 连同边上的「真/假」标签,全在 components/app/canvasEdges —— 画板和工作流共用那一张表。
 * 此前按语义上色的那几条写在这儿,和画板那边的线各是各的一套。
 *
 * 选择器里的下划线一律写 `\_`,整串用 String.raw(棘轮:design/arbitrarySelectors.test.ts)。
 */
export const WORKFLOW_CANVAS_CLASS = [
  "[--xy-background-color:var(--background)]",
  "[--xy-attribution-background-color:color-mix(in_srgb,var(--panel)_70%,transparent)]",
  String.raw`[&_.react-flow\_\_attribution_a]:text-muted-foreground`,
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
