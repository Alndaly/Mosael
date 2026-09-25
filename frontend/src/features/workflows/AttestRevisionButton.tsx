import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import { attestWorkflowRevision, type RevisionAttestRequest } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";

/**
 * 「认可这一版」—— 运行因为「这一版是别人改的」停下时,失败现场里带着是哪条工作流的哪一版
 * (后端 domain/authority 的 attest)。按钮点的就是那一版,不是当前版:子流程里那一版、以及定时
 * 任务那次钉住的那一版,都可能不是你正看着的这一条的当前版本。
 *
 * 谁点都能记下,但只对**点的人自己用得了**的东西有用 —— 真正的判断在下次运行用到的那一刻。
 */
export function AttestRevisionButton({ attest, onDone }: { attest: RevisionAttestRequest; onDone?: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const approve = useMutation({
    mutationFn: () => attestWorkflowRevision(attest.workflow_id, attest.revision),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflow-revisions", attest.workflow_id] });
      toast.success(t("wfRevisionAttested").replace("{version}", String(attest.revision)));
      onDone?.();
    },
    onError: (error: Error) => toast.error(t("wfRevisionAttestFailed"), { description: error.message }),
  });
  const label = attest.workflow_name
    ? t("wfRevisionAttestFor").replace("{name}", attest.workflow_name).replace("{version}", String(attest.revision))
    : t("wfRevisionAttest");
  return (
    <Button
      size="sm"
      variant="outline"
      className="shrink-0"
      title={t("wfRevisionAttestHint")}
      loading={approve.isPending}
      onClick={() => approve.mutate()}
    >
      <ShieldCheck size={13} /> {label}
    </Button>
  );
}
