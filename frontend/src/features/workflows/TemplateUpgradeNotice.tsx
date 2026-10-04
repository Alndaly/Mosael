import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import React from "react";
import { toast } from "sonner";

import { rebuildWorkflowFromTemplate, type WorkflowGraph } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CANVAS_GLASS_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { useWorkflowTemplates } from "@/features/workflows/WorkflowCommunityDialog";
import { emitOpenEvent } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

/**
 * 这张图是从**旧版**官方模板建出来的:浮在画布顶上说一声,点一下按新版重建一张(旧图原样保留)。
 *
 * 旧版模板建的图不迁移 —— 图一落库就是用户的数据,他可能改过,不替他悄悄改写。可 1.8.0 时建的那几张里有注定失败的
 * (上身图动起来必败、混剪没旁白的那段必败、带货只念钩子),而用户看不出来,只会在付完钱之后看到失败。版本号是图上的
 * meta.template_version,和模板目录里的现行版本比(后端 templates.current_template_versions)。
 *
 * 点叉是**按版本**收起的(localStorage 记「这张图的提示我看到了第几版」):旧图原样保留,不点重建它就一直在,
 * 每次都浮出来是骚扰而不是提醒;模板再出新版时重新出现 —— 那是另一件该知道的事。存本机而不是写进图:
 * 这是"我在这个屏幕上不想看了",不是图的内容,不该进修订历史。
 */

//: localStorage 键。值:{ [workflowId]: 已收起的最新的模板版本 }。
const DISMISS_KEY = "mosael.wfTemplateNoticeDismissed";

function readDismissed(workflowId: string): number {
  try {
    const raw = localStorage.getItem(DISMISS_KEY);
    const map = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    return Number(map[workflowId] ?? 0) || 0;
  } catch {
    return 0;
  }
}

function writeDismissed(workflowId: string, version: number): void {
  try {
    const raw = localStorage.getItem(DISMISS_KEY);
    const map = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    map[workflowId] = version;
    localStorage.setItem(DISMISS_KEY, JSON.stringify(map));
  } catch {
    //: 隐私模式之类写不进去时,收起只对这一次会话生效 —— 不报错,提示还在,是最诚实的退路。
  }
}

export function TemplateUpgradeNotice({ workflowId, meta }: { workflowId: string; meta: WorkflowGraph["meta"] }) {
  const t = useI18n();
  const qc = useQueryClient();
  const templates = useWorkflowTemplates();
  const [dismissed, setDismissed] = React.useState(false);
  const rebuild = useMutation({
    mutationFn: () => rebuildWorkflowFromTemplate(workflowId),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ["workflows", created.workspace_id] });
      toast.success(t("wfTemplateRebuilt").replace("{name}", created.name));
      emitOpenEvent("mosael:open-workflow", created.id);
    },
    onError: (error: Error) => toast.error(t("wfTemplateRebuildFailed"), { description: error.message }),
  });
  const current = templates.data?.find((one) => one.id === meta?.template_id);
  if (!meta || meta.source !== "official" || !current || Number(meta.template_version ?? 0) >= current.version) return null;
  if (dismissed || readDismissed(workflowId) >= current.version) return null;
  return (
    <div
      role="status"
      data-wf-template-outdated=""
      className={cn(CANVAS_GLASS_SURFACE_CLASS, "flex min-h-[42px] max-w-[min(560px,100%)] items-center gap-2 rounded-lg py-1 pl-3 pr-1 text-ui-xs text-muted-foreground")}
    >
      <Sparkles size={13} className="shrink-0 text-primary" />
      <span>{t("wfTemplateOutdated").replace("{name}", current.name)}</span>
      <Button size="sm" variant="secondary" loading={rebuild.isPending} onClick={() => rebuild.mutate()}>
        {t("wfTemplateRebuild")}
      </Button>
      <IconButton
        size="sm"
        label={t("wfTemplateNoticeDismiss")}
        hint={t("wfTemplateNoticeDismissHint")}
        onClick={() => {
          writeDismissed(workflowId, current.version);
          setDismissed(true);
        }}
      >
        <X size={13} />
      </IconButton>
    </div>
  );
}
