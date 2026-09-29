import type { QueryClient } from "@tanstack/react-query";

import { CANVAS_EDGE_OPTIONS } from "@/components/app/canvasEdges";
import { MarkerPin } from "@/features/markers/MarkerPin";
import { WORKFLOW_NODE_TYPES } from "@/features/workflows/WorkflowNode";

//: 工作流页各模块(列表、编辑器、检查器)共用的几样常量和小函数。

/** 主画布的节点类型。标记不是工作流节点(它不执行、不连线),但它在 React Flow 里得有个
 *  渲染器 —— 所以它加在这里,而不是加进 WORKFLOW_NODE_TYPES(那张表是"能跑的节点")。
 *  子图画布也用这张表:那里没有加标记的入口,但一份手写进来的子图里若有 markers,
 *  少了渲染器就是一块空白 —— 注册一个渲染器比在投影里再筛一遍便宜。 */
export const WORKFLOW_CANVAS_NODE_TYPES = { ...WORKFLOW_NODE_TYPES, marker: MarkerPin };

/** 这个画布节点是标记吗?(标记的 id 带前缀,复制 / 折叠 / 层级那些操作都要绕开它。) */
export const isMarkerNode = (node: { type?: string }): boolean => node.type === "marker";

/** 「添加」菜单里代表标记的那一项。用一个不可能撞上节点类型的值,免得和插件节点重名。 */

export const AGENT_MODES = ["docked", "floating"] as const;

/** 助手面板的开合记忆。 */
export const AGENT_PANEL_KEY = "mosael:workflow-agent-open";

/** 贴靠面板的几何:宽度固定,高度自适应但封顶;与节点之间留 10px 间隙,离窗口边至少 12px。 */

/** 连线统一带闭合箭头、同一条命中带。长什么样见 components/app/canvasEdges,怎么走(贝塞尔/折线)见 canvasEdgeShape。 */
export const DEFAULT_EDGE_OPTIONS = CANVAS_EDGE_OPTIONS;
export const EMPTY_SCOPE_VARIABLES: string[] = [];

/** 删了工作流:列表要刷新;绑着它的定时任务也被后端当场停用了(见后端 scheduler.stop_tasks_bound_to_workflow),
 *  定时任务页的开关不刷新就还亮着。 */
export function refreshAfterWorkflowDelete(qc: QueryClient, workspaceId: string) {
  void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
  void qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspaceId] });
}
