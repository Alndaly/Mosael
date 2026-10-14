import React from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutPanelLeft } from "lucide-react";

import { getWorkflowLibrary, type PluginInstance } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { explainOpenFailure } from "@/features/plugins/localServiceStatus";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";

/**
 * 连接工具栏的「打开工作台」:直接跳到这台 ComfyUI 的内嵌工作台(画布 + Mosael 的模型库、表单、运行结果,ADR 0038)。
 *
 * 只在桌面壳(有 `openComfyWorkbench` 桥)、且这个连接是 ComfyUI 编辑器时摆 —— 编辑器地址和工作流库、「回到那里」
 * 同一份(工作流库的 `editor.url`),不另猜。收起时也在,和刷新、模型库、工作流库同一排:不用先展开就能进工作台。
 * 背后是宿主起停的本机服务(ADR 0041)时,`openWorkbench` 会先请宿主起好、等它就绪,按钮上摆「正在启动…」。
 */
export function OpenConnectionWorkbench({
  instance,
  workspaceId,
}: {
  instance: PluginInstance;
  workspaceId: string;
}) {
  const t = useI18n();
  const available = workbenchAvailable();
  const library = useQuery({
    queryKey: ["workflow-library", instance.id, workspaceId],
    queryFn: () => getWorkflowLibrary(instance.id, workspaceId),
    enabled: available,
    staleTime: 60_000,
    retry: false,
  });
  const [failure, setFailure] = React.useState("");
  const [opening, setOpening] = React.useState(false);
  //: 本机服务正在起(第一次启动可能要一两分钟):按钮上说一声,不装死
  const [starting, setStarting] = React.useState(false);
  const editor = library.data?.editor;
  if (!available || !editor || editor.kind !== "comfyui") return null;
  const open = async () => {
    setFailure("");
    setOpening(true);
    try {
      const result = await openWorkbench(
        { instanceId: instance.id, instanceName: instance.name, workspaceId, url: editor.url },
        {},
        () => setStarting(true),
      );
      if (!result.ok) setFailure(await explainOpenFailure(instance.id, result.error || t("workflowWorkbenchFailed")));
    } catch (error) {
      setFailure(await explainOpenFailure(instance.id, errorText(error)));
    } finally {
      setOpening(false);
      setStarting(false);
    }
  };
  return (
    <IconButton
      variant="outline"
      size="default"
      className="px-3 text-muted-foreground"
      label={starting ? t("localServiceOpenStarting") : t("pluginConnOpenWorkbench")}
      hint={failure || t("pluginConnOpenWorkbenchHint")}
      disabled={Boolean(instance.blocked_reason)}
      disabledReason={instance.blocked_reason}
      loading={opening}
      onClick={() => void open()}
    >
      <LayoutPanelLeft size={13} />
    </IconButton>
  );
}
