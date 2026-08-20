import React from "react";
import { Bot, ChevronDown, CircleAlert, Loader2 } from "lucide-react";

import type { AgentTimelineItem, ToolCall } from "@/components/agent/ToolCalls";
import { AgentTurnContent } from "@/components/agent/ToolCalls";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatElapsedSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 「N 个子代理」:这个会话派出过哪些子智能体,各自干了什么。
 *
 * 子智能体的意义就是**把中间过程留在它自己那里**,主对话只收结论 —— 代价是那段过程默认
 * 不可见:哪个子代理、查了几步、有没有失败,全都折在一张 run_subagent 卡的 JSON 里。
 * 这里按 DSH 的形态补上入口:头部一枚「N 个子代理」,点开列出每个(任务、步数、耗时、状态),
 * 再点进去看它的完整轨迹 —— 它说过的话、每一步工具调用。
 *
 * 轨迹来自 run_subagent 结果里的 `details.subagent`(sidecar 存档,不回填给模型)。
 * 老会话的卡没有这份存档 —— 列表照样列出它们,只是详情里如实说「这次没有留下轨迹」,
 * 而不是把旧记录藏起来装作没派过。
 */

type SubagentArchive = {
  task: string;
  steps: number;
  error: string | null;
  trace: ({ type: "text"; text: string } | { type: "tool"; id: string; name: string; args?: unknown; result?: unknown; isError?: boolean })[];
};

export type SubagentRun = {
  /** run_subagent 那次调用的 ToolCall(状态、耗时都在它身上)。 */
  call: ToolCall;
  archive: SubagentArchive | null;
};

/** 从时间线里挑出所有 run_subagent 调用,并尽力解出各自的存档。 */
export function collectSubagentRuns(timeline: AgentTimelineItem[] | undefined): SubagentRun[] {
  const runs: SubagentRun[] = [];
  for (const item of timeline ?? []) {
    if (item.type !== "tool" || item.tool?.name !== "run_subagent") continue;
    runs.push({ call: item.tool, archive: readArchive(item.tool.result) });
  }
  return runs;
}

function readArchive(result: unknown): SubagentArchive | null {
  if (result == null) return null;
  let value: unknown = result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  const details = (value as { details?: { subagent?: unknown } }).details;
  const archive = details?.subagent as SubagentArchive | undefined;
  if (!archive || !Array.isArray(archive.trace)) return null;
  return archive;
}

/** 子代理在列表里的名字:任务的第一行。id 对人没有意义,任务才是它的身份。 */
function runLabel(run: SubagentRun): string {
  const task = run.archive?.task ?? (run.call.args as { task?: string } | undefined)?.task ?? "";
  return task.split("\n")[0].trim() || run.call.id;
}

export function SubagentButton({ timeline }: { timeline: AgentTimelineItem[] | undefined }) {
  const t = useI18n();
  const runs = React.useMemo(() => collectSubagentRuns(timeline), [timeline]);
  const [openRun, setOpenRun] = React.useState<SubagentRun | null>(null);
  if (runs.length === 0) return null;
  const running = runs.some((run) => run.call.status === "running");
  return (
    <>
      <Popover>
        <PopoverTrigger asChild>
          <Button size="sm" variant="ghost" className="h-7 gap-1 text-ui-xs text-muted-foreground">
            {running ? <Loader2 size={12} className="animate-openstudio-spin" /> : <Bot size={12} />}
            {t("chatSubagents").replace("{n}", String(runs.length))}
            <ChevronDown size={11} />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[340px] p-1">
          <div className="grid max-h-[300px] gap-px overflow-y-auto">
            {runs.map((run, index) => {
              const seconds = run.call.usage?.duration_seconds;
              return (
                <button
                  key={`${run.call.id}-${index}`}
                  type="button"
                  className="grid w-full cursor-pointer gap-0.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-left hover:bg-muted"
                  onClick={() => setOpenRun(run)}
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        run.call.status === "running" && "bg-primary animate-pulse",
                        run.call.status === "done" && "bg-success",
                        run.call.status === "error" && "bg-destructive",
                      )}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate text-ui-xs text-foreground">{runLabel(run)}</span>
                    {typeof seconds === "number" && (
                      <span className="timecode shrink-0 text-ui-2xs text-muted-foreground">{formatElapsedSeconds(seconds)}</span>
                    )}
                  </span>
                  <span className="pl-3 text-ui-2xs text-muted-foreground">
                    {run.archive
                      ? t("chatSubagentSteps").replace("{n}", String(run.archive.steps))
                      : run.call.status === "running"
                        ? t("chatSubagentRunning")
                        : t("chatSubagentNoTrace")}
                    {run.archive?.error ? ` · ${run.archive.error.slice(0, 60)}` : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
      <Dialog open={openRun !== null} onOpenChange={(next) => !next && setOpenRun(null)}>
        <DialogContent className="max-h-[80vh] w-[min(720px,92vw)] max-w-none overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="pr-6 text-ui-md leading-[1.4]">{openRun ? runLabel(openRun) : ""}</DialogTitle>
          </DialogHeader>
          {openRun && <SubagentTrace run={openRun} />}
        </DialogContent>
      </Dialog>
    </>
  );
}

function SubagentTrace({ run }: { run: SubagentRun }) {
  const t = useI18n();
  // 存档 → 时间线形态,直接复用主对话的渲染(工具卡可展开看参数/结果)。
  const timeline = React.useMemo<AgentTimelineItem[]>(() => {
    if (!run.archive) return [];
    return run.archive.trace.map((item) =>
      item.type === "text"
        ? { type: "text", text: item.text }
        : {
            type: "tool",
            tool: {
              id: item.id,
              name: item.name,
              args: item.args,
              result: item.result,
              status: item.isError ? "error" : "done",
            } as ToolCall,
          },
    );
  }, [run.archive]);

  if (!run.archive) {
    return (
      <p className="m-0 flex items-center gap-1.5 text-ui-sm text-muted-foreground">
        <CircleAlert size={13} />
        {run.call.status === "running" ? t("chatSubagentRunning") : t("chatSubagentNoTrace")}
      </p>
    );
  }
  return (
    <div className="grid min-w-0 gap-2">
      <p className="m-0 whitespace-pre-wrap text-ui-xs leading-[1.55] text-muted-foreground">{run.archive.task}</p>
      <AgentTurnContent timeline={timeline} />
    </div>
  );
}
