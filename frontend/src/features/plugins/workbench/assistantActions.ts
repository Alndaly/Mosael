/**
 * 「助手」页签里那几张卡要做的事(ADR 0042 §5),由页签给:在画布上定位一个节点、把一条诊断交给智能体「照这个改」、
 * 去「缺失项」那一页下载缺的模型。卡画在对话里(工具结果、确认卡),够不着页签的状态,所以经这一层。
 *
 * context 单独一个模块:只依赖 React 和类型(见 app/contextIdentity.test)。
 */
import React from "react";

/**
 * 诊断里的一条(插件 check_graph 的问题单,见 diagnose.py):节点按画布摘要的写法(`12`、子图里的 `12:5`)。
 *
 * `pack`:缺的那种节点**图里自己写着的出处**(`properties.cnr_id` / `aux_id` / `ver`)—— 插件离线归因出来的:
 * 包名、来源、要哪一版、包页面。`core`:它是 ComfyUI 的核心节点(`cnr_id` 写着 `comfy-core`),那不是缺插件,是
 * 这台 ComfyUI 太老。两者的文案插件都写好了(`cause` / `fix`),这里只多给一个能点的页面。
 */
export interface AssistantFinding {
  ref: string;
  type?: string;
  title?: string;
  severity: string;
  kind: string;
  input?: string;
  cause: string;
  fix?: string;
  core?: boolean;
  pack?: AssistantFindingPack;
}

export interface AssistantFindingPack {
  id: string;
  /** `registry`(注册表上的节点包)/ `git`(git 仓库) */
  source: string;
  page: string;
  repository?: string;
  wanted_version?: string;
  wanted_is_commit?: boolean;
  installed?: boolean;
  installed_version?: string;
}

export interface WorkbenchAssistantActions {
  /** 在画布上选中、移到中间(子图里的先打开那一层)。成了回空串,没成回一句给人看的原因。 */
  locate: (ref: string) => Promise<string>;
  /** 「照这个改」:替用户发一句,让智能体把这一条转成一次 comfy_canvas_edit 的提议。 */
  fix: (finding: AssistantFinding) => void;
  /** 「去下载」:换到「缺失项」那一页。 */
  showMissing: () => void;
}

export const WorkbenchAssistantContext = React.createContext<WorkbenchAssistantActions | null>(null);
