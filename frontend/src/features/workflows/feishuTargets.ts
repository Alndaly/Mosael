import React from "react";
import { useQueries } from "@tanstack/react-query";

import { fetchWorkflowFieldOptions, type WorkflowGraph } from "@/api/client";
import type { FeishuTargetNamer } from "@/features/workflows/feishuChannel";

/**
 * 画布卡片上「收件人那一格里的值叫什么」—— 那一格的**选项目录**,和检查器同一个现查接口
 * (`GET /api/workflows/field-options` 的 `feishu_targets`,见后端 field_options)。
 *
 * 为什么非要多问一次:节点上存的是 `ou_…` / `oc_…` —— **某个飞书应用眼里的编号**。坐在这张画布前的人
 * 在下拉里挑的是「张三 · 机器人 A」那一行,目录之外没有任何地方把那串 id 和人名对得上(open_id 按
 * 应用隔离,连"猜一个名字"都不成立)。模型那一行早就是这么做的(现查生成选项),这里是同一条。
 *
 * 目录里没有的值照样写 id(见 feishuChannel 的 targetLabel)—— 查不到就说查不到,不编名字。
 */

/** 「收件人」那一格的两个档各是一次现查(`channel` 是 depends_on 的那个父字段)。 */
export type FeishuTargetParents = { user: boolean; chat: boolean };

const SOURCE = "feishu_targets";

/** 哪几档**这一张图真的用得上**:没有节点配成那一档就不问 —— 群那一档在后端是现问飞书的。 */
export function feishuTargetParents(graph: WorkflowGraph): FeishuTargetParents {
  const parents: FeishuTargetParents = { user: false, chat: false };
  for (const node of graph.nodes ?? []) {
    if (node.type !== "await_approval" && node.type !== "feishu_message") continue;
    const config = node.config ?? {};
    const channel = String(config.channel ?? "").trim();
    const target = String(config.to ?? "").trim();
    //: `to` 空着或是一段 `{{…}}` 引用时卡上写的是「发起人」,查目录没用。
    if (!target || target.includes("{{")) continue;
    if (channel === "user") parents.user = true;
    if (channel === "chat") parents.chat = true;
  }
  return parents;
}

/** 值 → 目录里的名字(查不到空串)。 */
export function useFeishuTargetNames(
  workspaceId: string,
  parents: FeishuTargetParents,
): FeishuTargetNamer {
  const used = [parents.user ? "user" : "", parents.chat ? "chat" : ""].filter(Boolean);
  const results = useQueries({
    queries: used.map((parent) => ({
      //: 查询键的根和检查器那一路相同(`workflow-field-options`):插件/设置的失效一整片带走它。
      //: 后面三格(node_type / workflow_id / 字段名)这一路都没有意义 —— 收件人的目录与它们无关,
      //: 所以留空,不假装是「某个节点的某一格」。
      queryKey: ["workflow-field-options", SOURCE, workspaceId, parent, "", "", ""],
      queryFn: () => fetchWorkflowFieldOptions(SOURCE, workspaceId, parent),
      enabled: Boolean(workspaceId),
      staleTime: 30_000,
    })),
  });
  //: 查询结果每次渲染都是一只新数组 —— 直接进依赖会让下游的画布投影每帧重算。指纹按**内容**取。
  const catalog = results
    .flatMap((result) => result.data ?? [])
    .map((option) => `${option.value}\u0000${option.label}`)
    .join("\u0001");
  return React.useMemo(() => {
    const names = new Map<string, string>();
    for (const pair of catalog.split("\u0001")) {
      const at = pair.indexOf("\u0000");
      if (at >= 0) names.set(pair.slice(0, at), pair.slice(at + 1));
    }
    return (value: string) => names.get(value.trim()) ?? "";
  }, [catalog]);
}
