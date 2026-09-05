/**
 * 一个任务派生出的子任务。
 *
 * **两个消费方**:任务中心的任务详情,和工作流的运行历史。同一份清单画两遍的话,迟早会在
 * 某一处漏掉一种状态或者一种 kind —— 而那时两个界面会对同一次运行给出不同的说法
 * (`runSteps.ts` 当初就是为这个抽出来的)。
 *
 * **为什么工作流那边也需要它。** 运行历史按 task_events 画每个节点的状态,而循环体里的节点
 * **不发事件**(子图不带 job,见 workflows/engine.execute_graph)。于是一次跑六镜的运行,
 * 历史上只有「逐镜生成」一个条目在转圈,十几分钟不动 —— 看起来像卡死了。
 *
 * 而那六次出片其实各自都建了任务,`parent_job_id` 指着这次运行(create_job 按上下文自动打的标)。
 * 数据一直在,只是工作流这一侧从没去取。所以不必发明新的事件类型,把已有的子任务摆出来就行。
 */

import { useQuery } from "@tanstack/react-query";

import { listJobChildren, type Job } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running", "pending"]);

/** job.kind → 文案键的后缀。认不出来的归到「其它」,而不是把裸 kind 摆到界面上。 */
function kindKey(kind: string): string {
  const map: Record<string, string> = {
    render: "Render",
    transcribe: "Transcribe",
    ai_generation: "Generation",
    scheduled: "Scheduled",
    workflow: "Workflow",
    publish: "Publish",
  };
  return map[kind] ?? "Other";
}

export function JobChildrenList({ children: rows }: { children: Job[] }) {
  const t = useI18n();
  if (rows.length === 0) return null;
  return (
    <ul className="m-0 grid list-none gap-0 p-0">
      {rows.map((child) => {
        const active = ACTIVE.has(child.status);
        const statusKey = active
          ? "running"
          : child.status === "succeeded" || child.status === "failed"
            ? child.status
            : null;
        return (
          <li
            className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-2 py-[5px] [&+&]:border-t [&+&]:border-border"
            key={child.id}
          >
            <div className="grid min-w-0 gap-px">
              <span className="text-ui-xs text-foreground">{t(`jobKind${kindKey(child.kind)}` as never)}</span>
              {child.message && <small className="truncate text-ui-xs text-muted-foreground">{child.message}</small>}
            </div>
            <span
              className={cn(
                "shrink-0 text-ui-2xs",
                active ? "text-primary" : child.status === "succeeded" ? "text-success" : "text-destructive",
              )}
            >
              {statusKey ? t(`runStatus_${statusKey}` as never) : child.status}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** 拉某个任务的子任务。跑着的时候跟着刷,停了就不刷 —— 和详情弹窗同一条规矩。 */
export function useJobChildren(jobId: string | null, active: boolean) {
  return useQuery({
    queryKey: ["job-children", jobId],
    queryFn: () => listJobChildren(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: active ? 1500 : false,
  });
}
