import React from "react";

import type { WorkflowNodeType } from "@/api/client";
import type { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { entryOrigin, formedGroups } from "@/lib/entryNames";

/** 通用「插件工具」节点的类型 id。装了插件之后它就从面板上撤掉 —— 见 nodePickerOptions。 */
const GENERIC_PLUGIN_NODE = "plugin_tool";

export interface NodePickerOption {
  value: string;
  label: string;
  description: string;
  group: string;
  keywords?: string[];
  /** 同一张工作流的表单入口挂在它的完整工作流下面(ADR 0045)。 */
  indent?: boolean;
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
export function nodePickerOptions(
  nodeTypes: WorkflowNodeType[],
  otherGroup: string,
  t: (key: MessageKey) => string,
): NodePickerOption[] {
  const hasPluginNodes = nodeTypes.some((meta) => meta.type.startsWith("plugin."));
  //: 有表单的那几张工作流:完整工作流的副名写「完整工作流」(ADR 0045)
  const formed = formedGroups(nodeTypes);
  return nodeTypes
    .filter((meta) => !(hasPluginNodes && meta.type === GENERIC_PLUGIN_NODE))
    .map((meta) => {
      //: 两层名字的副名(ADR 0045):这个工具是哪张工作流的哪个入口。节点按插件聚合、不分连接,不写连接名。
      const origin = entryOrigin(meta.group, formed, t);
      // 同名工具可能来自不同插件(两个平台的 fetch_one_video),副标题点名是谁提供的。
      // 面板里的副标题只有一行、也参与搜索:用纯文本(节点说明里有 **强调**)。
      const source = [origin, meta.plugin_name].filter(Boolean).join(" · ");
      return {
        value: meta.type,
        label: meta.label,
        description: source ? `${source} · ${toPlainText(meta.description)}` : toPlainText(meta.description),
        group: meta.category || otherGroup,
        //: 按调用名、工作流名、文件路径都搜得到
        keywords: [meta.tool_name, meta.group?.label, meta.group?.id].filter((one): one is string => Boolean(one)),
        indent: meta.group?.entry === "form",
      };
    });
}

export function useNodePicker(nodeTypes: WorkflowNodeType[], t: ReturnType<typeof useI18n>) {
  const options = React.useMemo(() => nodePickerOptions(nodeTypes, t("wfNodeGroupOther"), t), [nodeTypes, t]);
  return { options };
}
