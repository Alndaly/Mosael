import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { listPluginPackages } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { explainOpenFailure } from "@/features/plugins/localServiceStatus";
import { hasWorkflowEditor, workbenchAddress } from "@/features/plugins/workbench/workbenchAddress";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";

/**
 * 「在工作台里打开这张工作流」的状态与动作(ADR 0038 §8)。创作页的「引擎参数」和画板生成节点用同一份。
 *
 * **摆不摆只看静态事实**:桌面壳有工作台桥、这个连接认领了工作流库、手上有那张工作流的路径。**不为了一颗按钮去现问整份
 * 工作流库** —— 那是一次随工作流数线性变大的插件调用,ComfyUI 没起、目录太大超出预算、超时,按钮就悄悄消失(维护者报的
 * 「有时候不显示」就是这个)。地址点下去时再取(`workbenchAddress`,读不回来退到连接自己写的地址);那张工作流在不在,
 * 由工作台打开时回答(`missing`),按它说话。
 *
 * `path` 是那张工作流的路径:表单入口的模型 id 是 `<路径>#<表单 id>`,调用方给的是它的组(`group.id`),不拆模型 id。
 * `form` 是表单入口的模型 id(不是表单入口就不给):工作台打开后直接到「表单」页、选中那一张。
 */
export function useOpenWorkflowInWorkbench({
  instanceId,
  path,
  form,
  workspaceId,
}: {
  instanceId: string | null | undefined;
  path: string;
  form?: string | null;
  workspaceId: string;
}) {
  const t = useI18n();
  const queryClient = useQueryClient();
  const embedded = workbenchAvailable();
  const packages = useQuery({
    queryKey: ["plugins"],
    queryFn: () => listPluginPackages(),
    enabled: embedded && Boolean(instanceId),
    staleTime: 60_000,
  });
  const owner = packages.data?.find((pkg) => (pkg.instances ?? []).some((one) => one.id === instanceId));
  const instance = owner?.instances?.find((one) => one.id === instanceId);
  const [failure, setFailure] = React.useState("");
  const [opening, setOpening] = React.useState(false);
  //: 连接背后的本机服务正在起(ADR 0041):按钮上写「正在启动…」,第一次启动可能要一两分钟
  const [starting, setStarting] = React.useState(false);

  const offered = embedded && Boolean(path) && Boolean(owner && instance && hasWorkflowEditor(owner));

  const open = async () => {
    if (!owner || !instance) return;
    setFailure("");
    setOpening(true);
    try {
      const url = await workbenchAddress(queryClient, owner, instance, workspaceId);
      if (!url) {
        setFailure(t("workflowMenuNoEditor"));
        return;
      }
      const result = await openWorkbench({ instanceId: instance.id, instanceName: instance.name, workspaceId, url }, { path, form },
                                         () => setStarting(true));
      // 背后是本机服务、而它此刻用不了(停了、起不来、不应答):按它的状态说,不说「没就绪」「连不上」
      if (!result.ok) setFailure(await explainOpenFailure(instance.id, result.error || t("workflowWorkbenchFailed")));
      else if (result.outcome === "missing") setFailure(t("workflowEditorMissing").replace("{name}", path));
      else if (result.outcome === "notReady") {
        setFailure(await explainOpenFailure(instance.id, t("workflowEditorNotReady").replace("{name}", path)));
      }
    } catch (error) {
      setFailure(await explainOpenFailure(instance.id, errorText(error)));
    } finally {
      setOpening(false);
      setStarting(false);
    }
  };

  return {
    offered,
    blockedReason: instance?.blocked_reason ?? "",
    open,
    opening,
    starting,
    failure,
  };
}
