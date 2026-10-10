/**
 * 某一页认得的工具结果(ADR 0042 §5):工作台的「助手」把 `comfy_check` 的诊断画成一条条带「定位」「照这个改」的问题、把开好的
 * 新标签页画成一份带「去下载」的结果。工具行(ToolCalls)先问这一页认不认得这次的结果,认得就把它放进该调用的展开明细;
 * 不认得照通用的画。没有这一层的地方(AI 工作台)一切照旧。
 *
 * context 单独一个模块:只依赖 React 和类型(见 app/contextIdentity.test)。
 */
import React from "react";

export interface AgentPageViews {
  /** 这一次工具调用的结果画成什么;不认得回 null。`data` 是拆过包的结构化结果(toolResultData)。 */
  toolResult: (tool: string, data: unknown) => React.ReactNode;
}

export const AgentPageViewsContext = React.createContext<AgentPageViews | null>(null);
