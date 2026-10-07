import React from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutPanelLeft } from "lucide-react";

import { getWorkflowLibrary } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { explainOpenFailure } from "@/features/plugins/localServiceStatus";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";

/**
 * AI 工作台里选中的模型旁边的「在工作台里打开」(ADR 0038 §8):这个模型是某个插件连接上存着的一张 ComfyUI 工作流(的一个入口)时
 * 才有。认不认得是看那个连接的工作流库(插件报了 ComfyUI 的编辑器、这张在它的工作流里)—— 宿主不认识哪一家,和工作流库同一个判据。
 * `path` 是那张工作流的路径:表单入口的模型 id 是 `<路径>#<表单 id>`,调用方给的是它的组(`group.id`),不拆模型 id。
 */
export function OpenInWorkbench({
  instanceId,
  instanceName,
  path,
  workspaceId,
}: {
  instanceId: string;
  instanceName: string;
  path: string;
  workspaceId: string;
}) {
  const t = useI18n();
  const available = workbenchAvailable();
  const library = useQuery({
    queryKey: ["workflow-library", instanceId, workspaceId],
    queryFn: () => getWorkflowLibrary(instanceId, workspaceId),
    enabled: available && Boolean(instanceId),
    staleTime: 60_000,
    retry: false,
  });
  const [failure, setFailure] = React.useState("");
  const [opening, setOpening] = React.useState(false);
  //: 连接背后的本机服务正在起(ADR 0041):按钮上写「正在启动…」,第一次启动可能要一两分钟
  const [starting, setStarting] = React.useState(false);
  const editor = library.data?.editor;
  const known = Boolean(editor && editor.kind === "comfyui" && (library.data?.workflows ?? []).some((one) => one.path === path));
  if (!available || !known || !editor) return null;
  const open = async () => {
    setFailure("");
    setOpening(true);
    try {
      const result = await openWorkbench({ instanceId, instanceName, workspaceId, url: editor.url }, { path },
                                         () => setStarting(true));
      // 背后是本机服务、而它此刻用不了(停了、起不来、不应答):按它的状态说,不说「没就绪」「连不上」
      if (!result.ok) setFailure(await explainOpenFailure(instanceId, result.error || t("workflowWorkbenchFailed")));
      else if (result.outcome === "missing") setFailure(t("workflowEditorMissing").replace("{name}", path));
      else if (result.outcome === "notReady") {
        setFailure(await explainOpenFailure(instanceId, t("workflowEditorNotReady").replace("{name}", path)));
      }
    } catch (error) {
      setFailure(await explainOpenFailure(instanceId, errorText(error)));
    } finally {
      setOpening(false);
      setStarting(false);
    }
  };
  return (
    <div className="grid gap-1">
      <Hint label={t("workflowOpenInWorkbenchHint")}>
        <Button variant="outline" size="xs" className="justify-self-start" loading={opening} onClick={() => void open()}>
          <LayoutPanelLeft size={12} />
          {starting ? t("localServiceOpenStarting") : t("workflowOpenInWorkbench")}
        </Button>
      </Hint>
      {failure && <p role="alert" className="m-0 text-ui-xs text-destructive">{failure}</p>}
    </div>
  );
}
