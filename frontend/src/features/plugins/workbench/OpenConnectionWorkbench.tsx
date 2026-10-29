import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, LayoutPanelLeft } from "lucide-react";
import { toast } from "sonner";

import { getWorkflowLibrary, type PluginInstance, type PluginPackage } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { explainOpenFailure } from "@/features/plugins/localServiceStatus";
import { connectionAddress, hasWorkflowEditor } from "@/features/plugins/workbench/workbenchAddress";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";

/**
 * 连接工具栏的「打开工作台 / 在 ComfyUI 里打开」:进这台 ComfyUI 的界面(桌面版是内嵌工作台,ADR 0038;
 * 网页版是新标签页)。收起时也在,和刷新、模型库、工作流库同一排:不用先展开就能进。
 *
 * **地址从哪儿来**(不另猜、不拼路径):
 * 1. 插件报的编辑器地址(`workflow_library` 的 `editor.url`,宿主校验过只认 http(s))—— 权威,和工作流库、
 *    「在工作台里打开」、「回到那里」同一份;
 * 2. 工作流库**读不回来**时(目录类回答有输出预算:整份太大就整份不收,见后端 `runtime` 的
 *    `MAX_OUTPUT_BYTES` / `CATALOG_OUTPUT_BYTES`),用**这个连接自己写的地址**(清单的 `summary_field`,宿主 /
 *    用户写进去的那个,原样用)。ComfyUI 的网页和 API 在同一个源上,插件报的 `editor.url` 就是它(`comfy.base`)
 *    —— 所以这不是猜。不这样退一步的话,目录一大这颗按钮就**悄没声地消失**(维护者报的:远端那台没有,
 *    本机 8189 有)。
 *
 * 桌面壳(有 `openComfyWorkbench` 桥)进内嵌工作台;网页版开新标签页 —— 和 `workflowEditor` 里「在 ComfyUI 里
 * 打开」那条(`newTab`)一样:新标签页 + 留一句说开了哪台、哪个地址。
 *
 * 一个地址都拿不到(没写地址、目录也读不回来)时**摆着但点不动**,悬停说清为什么:不能让人以为功能丢了。
 * 认领了工作流库的连接才有编辑界面;插件报的编辑器不是 ComfyUI 时也不摆(那不是这个入口的事)。
 */
export function OpenConnectionWorkbench({
  pkg,
  instance,
  workspaceId,
}: {
  pkg: PluginPackage;
  instance: PluginInstance;
  workspaceId: string;
}) {
  const t = useI18n();
  const embedded = workbenchAvailable();
  //: 认领了工作流库的连接才有编辑界面(ADR 0035),才有「进它的界面」这回事
  const hasEditor = hasWorkflowEditor(pkg);
  const library = useQuery({
    queryKey: ["workflow-library", instance.id, workspaceId],
    queryFn: () => getWorkflowLibrary(instance.id, workspaceId),
    //: 只有桌面壳要为这一颗按钮问工作流库(地址取插件报的 `editor.url`)。网页版用连接自己写的地址 ——
    //: 目录大的那台一次要传 1MB 多,不该为了一个按钮去拉。
    enabled: embedded && hasEditor,
    staleTime: 60_000,
    retry: false,
  });
  const [failure, setFailure] = React.useState("");
  const [opening, setOpening] = React.useState(false);
  //: 本机服务正在起(第一次启动可能要一两分钟):按钮上说一声,不装死
  const [starting, setStarting] = React.useState(false);
  const editor = library.data?.editor;
  if (!hasEditor) return null;
  //: 插件报了别的编辑器(不是 ComfyUI):那颗按钮不归这个入口
  if (editor && editor.kind !== "comfyui") return null;
  //: 地址见文件头:插件报的 `editor.url` 优先,读不回来时用连接自己写的那个,**原样用**
  const address = editor?.kind === "comfyui" ? editor.url : connectionAddress(pkg, instance);
  const hint = address
    ? t(embedded ? "pluginConnOpenWorkbenchHint" : "pluginConnOpenComfyHint")
        .replace("{name}", instance.name)
        .replace("{url}", address)
    : "";
  const open = async () => {
    if (!address) return;
    if (!embedded) {
      //: 网页版没有工作台:新标签页开这台 ComfyUI,留一句说开了哪台、哪个地址(和 workflowEditor 的 newTab 同一条)
      window.open(address, "_blank", "noopener,noreferrer");
      setFailure("");
      toast(t("pluginConnOpenComfyOpened").replace("{name}", instance.name).replace("{url}", address));
      return;
    }
    setFailure("");
    setOpening(true);
    try {
      const result = await openWorkbench(
        { instanceId: instance.id, instanceName: instance.name, workspaceId, url: address },
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
      label={starting ? t("localServiceOpenStarting") : t(embedded ? "pluginConnOpenWorkbench" : "pluginConnOpenComfy")}
      hint={failure || hint}
      disabled={Boolean(instance.blocked_reason) || !address}
      disabledReason={instance.blocked_reason || t("workflowMenuNoEditor")}
      loading={opening}
      onClick={() => void open()}
    >
      {embedded ? <LayoutPanelLeft size={13} /> : <ExternalLink size={13} />}
    </IconButton>
  );
}

