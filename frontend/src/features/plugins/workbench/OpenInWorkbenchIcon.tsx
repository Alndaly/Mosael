import React from "react";
import { SquareArrowOutUpRight } from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { useOpenWorkflowInWorkbench } from "@/features/plugins/workbench/useOpenWorkflowInWorkbench";

/**
 * 画板生成节点底栏「参数」旁边那颗「在工作台里打开」:节点选的是一张 ComfyUI 工作流时,一下进工作台整套调这张图
 * (画布 + 模型库、缺失项、表单、运行,ADR 0038)。「参数」弹层只装表单上那几项,要动表单之外的节点就得来这里。
 *
 * 和创作页「引擎参数」里那颗是同一个动作(`useOpenWorkflowInWorkbench`),这里底栏只放得下一个图标:没打开的原因走提示。
 */
export function OpenInWorkbenchIcon({
  instanceId,
  path,
  form,
  workspaceId,
}: {
  instanceId: string;
  path: string;
  /** 表单入口的模型 id:打开后停在「表单」页的那一张 */
  form?: string | null;
  workspaceId: string;
}) {
  const t = useI18n();
  const workbench = useOpenWorkflowInWorkbench({ instanceId, path, form, workspaceId });
  React.useEffect(() => {
    if (workbench.failure) toast.error(workbench.failure);
  }, [workbench.failure]);
  if (!workbench.offered) return null;
  return (
    <IconButton
      size="icon-sm"
      data-board-open-workbench=""
      label={workbench.starting ? t("localServiceOpenStarting") : t("workflowOpenInWorkbench")}
      hint={workbench.hint}
      disabled={Boolean(workbench.blockedReason)}
      disabledReason={workbench.blockedReason}
      loading={workbench.opening}
      onClick={() => void workbench.open()}
    >
      <SquareArrowOutUpRight size={14} />
    </IconButton>
  );
}
