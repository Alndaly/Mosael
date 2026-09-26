import React from "react";

import type { WorkflowNodeType } from "@/api/client";
import type { useI18n } from "@/app/preferences";
import { toPlainText } from "@/components/markdown/inlineSyntax";

/** 通用「插件工具」节点的类型 id。装了插件之后它就从面板上撤掉 —— 见 nodePickerOptions。 */
const GENERIC_PLUGIN_NODE = "plugin_tool";

export interface NodePickerOption {
  value: string;
  label: string;
  description: string;
  group: string;
  keywords?: string[];
}

/**
 * 「添加节点」面板的选项:按后端排好的顺序,分组名就是节点声明的分组。
 *
 * 插件节点跟内置节点走的是**同一份**节点类型清单 —— 它们在这里没有任何特殊处理,因为在画布上
 * 它们本来就不该有区别:同样的表单、同样的输入输出、同样的校验。前端不认识"插件"这个概念,
 * 是这件事做对了的标志。
 *
 * **只给工作流的节点面板用。** 画板上的工具不照这份分组(「流程 / 数据 / AI」是搭流程的人的分法),
 * 按它对内容做什么分 —— 见 features/boards/boardTools。
 *
 * 这里只剩一条与插件有关的规则:装了插件之后,那行泛泛的「插件工具」从面板上撤掉。它能做的
 * 每一件事都已经被具体条目覆盖,留着只是多一个"选完还要在检查器里再选两次"的入口。
 */
export function nodePickerOptions(nodeTypes: WorkflowNodeType[], otherGroup: string): NodePickerOption[] {
  const hasPluginNodes = nodeTypes.some((meta) => meta.type.startsWith("plugin."));
  return nodeTypes
    .filter((meta) => !(hasPluginNodes && meta.type === GENERIC_PLUGIN_NODE))
    .map((meta) => ({
      value: meta.type,
      label: meta.label,
      // 同名工具可能来自不同插件(两个平台的 fetch_one_video),副标题点名是谁提供的。
      // 面板里的副标题只有一行、也参与搜索:用纯文本(节点说明里有 **强调**)。
      description: meta.plugin_name ? `${meta.plugin_name} · ${toPlainText(meta.description)}` : toPlainText(meta.description),
      group: meta.category || otherGroup,
      keywords: meta.tool_name ? [meta.tool_name] : undefined,
    }));
}

export function useNodePicker(nodeTypes: WorkflowNodeType[], t: ReturnType<typeof useI18n>) {
  const options = React.useMemo(() => nodePickerOptions(nodeTypes, t("wfNodeGroupOther")), [nodeTypes, t]);
  return { options };
}
