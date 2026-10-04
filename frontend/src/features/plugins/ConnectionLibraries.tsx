import React from "react";
import { FolderTree, Library } from "lucide-react";

import type { PluginInstance } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import type { Focused, ModelFocus, WorkflowFocus } from "@/features/plugins/libraryLinks";
import { ModelLibraryDialog } from "@/features/plugins/ModelLibrary";
import { WorkflowLibraryDialog } from "@/features/plugins/WorkflowLibrary";

/** 开着的一层:哪个库、停到哪一项。 */
type Layer =
  | { kind: "model"; focus: Focused<ModelFocus> | null }
  | { kind: "workflow"; focus: Focused<WorkflowFocus> | null };

/**
 * 一个连接的「模型库」「工作流库」两颗按钮和它们的窗口(连接认领了哪个就有哪个)。
 *
 * 两个库能互相跳:工作流详情里点用到的模型 → 模型库停在那一项(缺的就打开下载框);模型详情里点在用的工作流 → 工作流库
 * 停在那一张。另一个库没开就叠在上面开,关掉回到原来那一项;已经开着(在下面)就把上面这个关掉、让它停到那一项 ——
 * 来回点不会越叠越多。窗口按开的先后叠:后开的挂在后面,也就在上面。
 */
export function ConnectionLibraries({
  instance,
  workspaceId,
  models = false,
  workflows = false,
  onCheckSettings,
}: {
  instance: PluginInstance;
  workspaceId: string;
  /** 连接认领了模型库 / 工作流库。 */
  models?: boolean;
  workflows?: boolean;
  /** 读不出来时「去检查连接设置」:插件页给的(展开这个连接、定位到服务器地址)。不给就不摆那颗按钮。 */
  onCheckSettings?: () => void;
}) {
  const t = useI18n();
  const [layers, setLayers] = React.useState<Layer[]>([]);

  const show = (next: Layer) =>
    setLayers((now) => {
      const at = now.findIndex((one) => one.kind === next.kind);
      return at < 0 ? [...now, next] : [...now.slice(0, at), next];
    });
  const close = (kind: Layer["kind"]) =>
    setLayers((now) => {
      const at = now.findIndex((one) => one.kind === kind);
      return at < 0 ? now : now.slice(0, at);
    });
  const checkSettings = onCheckSettings
    ? () => {
        setLayers([]);
        onCheckSettings();
      }
    : undefined;
  const blocked = Boolean(instance.blocked_reason);

  return (
    <>
      {models && (
        <IconButton
          variant="outline"
          size="default"
          className="px-3 text-muted-foreground"
          label={t("modelLibraryOpen")}
          hint={t("modelLibraryDesc")}
          disabled={blocked}
          disabledReason={instance.blocked_reason}
          onClick={() => show({ kind: "model", focus: null })}
        >
          <Library size={13} />
        </IconButton>
      )}
      {workflows && (
        <IconButton
          variant="outline"
          size="default"
          className="px-3 text-muted-foreground"
          label={t("workflowLibraryOpen")}
          hint={t("workflowLibraryDesc")}
          disabled={blocked}
          disabledReason={instance.blocked_reason}
          onClick={() => show({ kind: "workflow", focus: null })}
        >
          <FolderTree size={13} />
        </IconButton>
      )}
      {layers.map((layer) =>
        layer.kind === "model" ? (
          <ModelLibraryDialog
            key="model"
            open
            onOpenChange={(open) => !open && close("model")}
            instance={instance}
            workspaceId={workspaceId}
            focus={layer.focus}
            onShowWorkflow={workflows ? (path) => show({ kind: "workflow", focus: { path, at: Date.now() } }) : undefined}
            onCheckSettings={checkSettings}
          />
        ) : (
          <WorkflowLibraryDialog
            key="workflow"
            open
            onOpenChange={(open) => !open && close("workflow")}
            instance={instance}
            workspaceId={workspaceId}
            focus={layer.focus}
            onShowModel={models ? (focus) => show({ kind: "model", focus: { ...focus, at: Date.now() } }) : undefined}
            onCheckSettings={checkSettings}
          />
        ),
      )}
    </>
  );
}
