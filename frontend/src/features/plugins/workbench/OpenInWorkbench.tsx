import { LayoutPanelLeft } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { useOpenWorkflowInWorkbench } from "@/features/plugins/workbench/useOpenWorkflowInWorkbench";

/**
 * AI 工作台「引擎参数」里选中的模型下面那颗「在工作台里打开」(ADR 0038 §8):这个模型是某个插件连接上存着的一张 ComfyUI
 * 工作流(的一个入口)时才有。摆不摆、地址怎么取见 `useOpenWorkflowInWorkbench`。
 */
export function OpenInWorkbench({
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
  if (!workbench.offered) return null;
  return (
    <div className="grid gap-1">
      <Hint label={workbench.blockedReason || t("workflowOpenInWorkbenchHint")}>
        <Button
          variant="outline"
          size="xs"
          className="justify-self-start"
          disabled={Boolean(workbench.blockedReason)}
          loading={workbench.opening}
          onClick={() => void workbench.open()}
        >
          <LayoutPanelLeft size={12} />
          {workbench.starting ? t("localServiceOpenStarting") : t("workflowOpenInWorkbench")}
        </Button>
      </Hint>
      {workbench.failure && <p role="alert" className="m-0 text-ui-xs text-destructive">{workbench.failure}</p>}
    </div>
  );
}
