import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";

import { listTasksAwaitingApproval, tasksAwaitingApprovalKey, type TaskAwaitingApproval } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CANVAS_GLASS_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { AttestRevisionButton } from "@/features/workflows/AttestRevisionButton";
import { cn } from "@/lib/utils";

/**
 * 这张图被谁的定时任务绑着、那个任务此刻在等主人认可(ADR 0047 D10):浮在画布顶上说一声。
 *
 * 定时任务到点替主人跑、花主人的 AI 连接;别人改过的那一版,要主人认可之后才会接着花。改图是工作区里的正常操作,
 * **只提醒、不拦**:改图的人看到「要 A 认可」(A 那边另有通知和任务上的「待你确认」),主人自己打开这张图时就地给
 * 「认可这一版」。认可的是任务在等的那一版 —— 可能是这张图调用的子流程,不是这一张的当前版。
 */
export function ScheduledApprovalNotice({ workflowId }: { workflowId: string }) {
  const t = useI18n();
  const waiting = useQuery({
    queryKey: tasksAwaitingApprovalKey(workflowId),
    queryFn: () => listTasksAwaitingApproval(workflowId),
  });
  const rows = waiting.data ?? [];
  if (rows.length === 0) return null;
  return (
    <div
      role="status"
      data-wf-awaiting-approval=""
      className={cn(CANVAS_GLASS_SURFACE_CLASS, "grid max-w-[min(560px,100%)] gap-1.5 rounded-lg py-2 pl-3 pr-2 text-ui-xs text-muted-foreground")}
    >
      {rows.map((row) => (
        <div key={row.task_id} className="flex min-w-0 items-center gap-2">
          <ShieldAlert size={13} className="shrink-0 text-warning" />
          <span className="min-w-0 flex-1">{sentence(row, t)}</span>
          {row.is_mine && <AttestRevisionButton attest={row.awaiting} />}
        </div>
      ))}
    </div>
  );
}

function sentence(row: TaskAwaitingApproval, t: ReturnType<typeof useI18n>): string {
  const filled = (template: string) =>
    template
      .replaceAll("{task}", row.task_name)
      .replaceAll("{workflow}", row.awaiting.workflow_name)
      .replaceAll("{version}", String(row.awaiting.revision))
      .replaceAll("{owner}", row.owner_name);
  return filled(row.is_mine ? t("wfAwaitingYourApproval") : t("wfAwaitingOwnerApproval"));
}
