import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { getSkill, setSkillEnabled } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { skillKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { SkillContent } from "@/features/agent/skills/SkillContent";

/**
 * 开一个**没人看过**的技能之前,先把全文摊开(ADR 0040 §6):插件带的、有人直接扔进数据目录的。
 * 启用之后这个工作区里每个人的智能体都会照它做事;它拿不到新权限,但里面写了什么得有人看过。
 */
export function SkillReviewDialog({
  workspaceId,
  skillRef,
  onClose,
}: {
  workspaceId: string;
  /** null = 关着。 */
  skillRef: string | null;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: skillKeys.detail(workspaceId, skillRef ?? ""),
    queryFn: () => getSkill(workspaceId, skillRef ?? ""),
    enabled: skillRef !== null,
  });
  const enable = useMutation({
    mutationFn: () => setSkillEnabled(workspaceId, skillRef!, true),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: skillKeys.all(workspaceId) });
      onClose();
    },
    onError: (error) => toast.error(errorText(error)),
  });
  const skill = detail.data;
  return (
    <ModalShell
      open={skillRef !== null}
      onOpenChange={(next) => !next && !enable.isPending && onClose()}
      title={t("agentSkillsReviewTitle").replace("{name}", skill?.title ?? skillRef ?? "")}
      className="w-[720px] max-w-[calc(100vw-32px)]"
      footer={
        <>
          <Button variant="outline" disabled={enable.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={!skill || Boolean(skill.problem)} loading={enable.isPending} onClick={() => enable.mutate()}>
            {t("agentSkillsReviewEnable")}
          </Button>
        </>
      }
    >
      {skill ? (
        <div className="grid gap-3">
          <p className="m-0 text-ui-sm text-muted-foreground" data-slot="skill-review-hint">
            {t("agentSkillsReviewHint").replace("{source}", skill.source_label)}
          </p>
          <SkillContent head={skill} files={skill.files ?? []} />
        </div>
      ) : null}
    </ModalShell>
  );
}
