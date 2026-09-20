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
 *
 * **每一行都能就地展开看过程。** 此前一行只有「AI 生成 / 成功 / 生成完成」三个词:那一步到底
 * 做了什么、失败时模型原样返回了什么,一概看不到 —— 而那条子任务自己的执行记录一直都在库里。
 * 就地展开而不是另开一层弹窗:你看的自始至终是同一次运行,叠一层会把这件事推到背景里。
 */

import React from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { listJobChildren, listJobEvents, type Job } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { JobEventList } from "@/components/layout/JobEvents";
import { useJobKinds } from "@/components/layout/jobKinds";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running", "pending"]);

export function JobChildrenList({ children: rows }: { children: Job[] }) {
  if (rows.length === 0) return null;
  return (
    <ul className="m-0 grid list-none gap-0 p-0">
      {rows.map((child) => (
        <ChildRow key={child.id} child={child} />
      ))}
    </ul>
  );
}

function ChildRow({ child }: { child: Job }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const { kindOf } = useJobKinds();
  const [open, setOpen] = React.useState(false);
  const active = ACTIVE.has(child.status);

  // **展开了才去取。** 一次运行可以派生几十条子任务,进详情就把每一条的执行记录都拉一遍,
  // 代价全落在「我只想看一眼状态」的那种用法上。
  const events = useQuery({
    queryKey: ["job-events", child.id],
    queryFn: () => listJobEvents(child.id),
    enabled: open,
    refetchInterval: open && active ? 1500 : false,
  });
  const grandchildren = useQuery({
    queryKey: ["job-children", child.id],
    queryFn: () => listJobChildren(child.id),
    enabled: open,
    refetchInterval: open && active ? 1500 : false,
  });

  const statusKey = active
    ? "running"
    : child.status === "succeeded" || child.status === "failed"
      ? child.status
      : null;

  return (
    <li className="min-w-0 py-[5px] [&+&]:border-t [&+&]:border-border">
      <button
        type="button"
        className="grid w-full min-w-0 cursor-pointer grid-cols-[12px_minmax(0,1fr)_auto] items-baseline gap-2 border-0 bg-transparent p-0 text-left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronRight
          size={11}
          className={cn("mt-[3px] shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <div className="grid min-w-0 gap-px">
          <span className="text-ui-xs text-foreground">{kindOf(child.kind).label}</span>
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
      </button>
      {open && (
        <div className="ml-5 mt-1.5 grid min-w-0 gap-2 pb-1">
          {/* 失败原因先说。它此前整条藏在钻不进去的那一层里,行上只剩一个红色的「失败」。 */}
          {child.error && (
            <p className="m-0 min-w-0 whitespace-pre-wrap text-ui-xs text-destructive [overflow-wrap:anywhere]">
              {child.error}
            </p>
          )}
          {events.isPending ? (
            <span className="inline-flex items-center gap-1.5 text-ui-2xs text-muted-foreground">
              <Loader2 size={11} className="animate-mosael-spin" /> {t("wfHistoryLoading")}
            </span>
          ) : (events.data ?? []).length === 0 ? (
            <span className="text-ui-2xs text-muted-foreground">{t("jobDetailNoEvents")}</span>
          ) : (
            <JobEventList events={events.data ?? []} locale={locale} compact />
          )}
          {/* 子任务自己还能有子任务(逐镜生成里每一镜又排了代理转码)。同一个组件往下套一层。 */}
          {(grandchildren.data ?? []).length > 0 && (
            <div className="grid min-w-0 gap-1 border-t border-border pt-1.5">
              <span className="text-ui-2xs font-semibold text-muted-foreground">{t("jobDetailChildren")}</span>
              <JobChildrenList>{grandchildren.data ?? []}</JobChildrenList>
            </div>
          )}
        </div>
      )}
    </li>
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
