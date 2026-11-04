import React from "react";
import { useMutation } from "@tanstack/react-query";
import { Film } from "lucide-react";
import { toast } from "sonner";

import { createWorkflow, listWorkflows, runWorkflow, type Workflow } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ModalShell, ModalSubmit } from "@/components/app/modals";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

const LONG_TAKE_TEMPLATE = "long_take_video";
/** 拆段按这么长估上限:模板的段长由模型定,这里只给「最多几段」留够。 */
const SHORTEST_SEGMENT_SECONDS = 5;

function templateOf(workflow: Workflow): string | undefined {
  return (workflow.graph as { meta?: { template_id?: string } } | undefined)?.meta?.template_id;
}

/**
 * 「更长的视频」:一次生成最多十几秒,要更长就走「任意长度的连续视频」模板。这里只是它的入口 ——
 * 工作区里已经有这张工作流就用它,没有就从模板建一份,填好想法和时长开跑。段怎么接、费用怎么估都在模板里。
 */
export function LongTakeButton({ workspaceId, prompt }: { workspaceId: string; prompt: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [idea, setIdea] = React.useState("");
  const [seconds, setSeconds] = React.useState("60");
  const [maxSpend, setMaxSpend] = React.useState("");
  const start = useMutation({
    mutationFn: async () => {
      const existing = (await listWorkflows(workspaceId)).find((one) => templateOf(one) === LONG_TAKE_TEMPLATE);
      const workflow = existing ?? await createWorkflow({
        workspace_id: workspaceId, name: t("genLongTakeName"), description: "", template_id: LONG_TAKE_TEMPLATE,
      });
      return runWorkflow(workflow.id, {
        idea: idea.trim(),
        target_seconds: Number(seconds),
        max_segments: Math.ceil(Number(seconds) / SHORTEST_SEGMENT_SECONDS),
        max_spend: Number(maxSpend) || 0,
      });
    },
    onSuccess: () => {
      setOpen(false);
      toast.success(t("genLongTakeStarted"));
    },
    onError: (error: Error) => toast.error(errorText(error)),
  });
  const ready = idea.trim() !== "" && Number(seconds) > 0;
  return (
    <>
      <IconButton
        variant="ghost"
        size="icon-xs"
        label={t("genLongTake")}
        onClick={() => {
          setIdea(prompt);
          setOpen(true);
        }}
      >
        <Film size={14} />
      </IconButton>
      <ModalShell
        open={open}
        onOpenChange={setOpen}
        title={t("genLongTake")}
        onSubmit={() => ready && start.mutate()}
        footer={<ModalSubmit loading={start.isPending} disabled={!ready}>{t("genLongTakeStart")}</ModalSubmit>}
      >
        <div className="grid gap-3">
          <p className="m-0 text-ui-xs text-muted-foreground">{t("genLongTakeHint")}</p>
          <Textarea aria-label={t("genLongTakeIdea")} placeholder={t("genLongTakeIdea")} rows={4} value={idea} onChange={(event) => setIdea(event.target.value)} />
          <label className="grid gap-1 text-ui-xs">
            {t("genLongTakeSeconds")}
            <Input type="number" min={1} value={seconds} onChange={(event) => setSeconds(event.target.value)} />
          </label>
          <label className="grid gap-1 text-ui-xs">
            {t("genLongTakeMaxSpend")}
            <Input type="number" min={0} value={maxSpend} onChange={(event) => setMaxSpend(event.target.value)} />
          </label>
        </div>
      </ModalShell>
    </>
  );
}
