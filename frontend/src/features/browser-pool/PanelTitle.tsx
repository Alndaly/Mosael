import { useQuery } from "@tanstack/react-query";

import { getBrowserSession, isNotFound } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { gotoRecord, OPEN_WORKFLOW_RUN, workflowRunLink } from "@/lib/deepLink";
import { formatShortDate, parseServerTime } from "@/lib/time";

/** 「10-04 14:32」:同一张卡片堆里分得出是哪一次就够了,年份和秒都不要。 */
function runTime(iso: string): string {
  const at = parseServerTime(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${formatShortDate(iso)} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

/**
 * 悬浮卡片标题条上的那一行字。
 *
 * 工作流运行开的浏览器:写明是**哪个工作流的哪一次运行**,点一下跳到那次运行(编辑器的执行历史停在那一次)。
 * 几条工作流同时跑时,右下角叠着几张卡片 —— 此前它们都没有标题,分不出哪张是谁的。
 * 别的卡片(发布任务、智能体、手动打开的档案)照旧显示执行器报来的步骤名;卡片 id 不是会话的,后端回 404,就不问第二次。
 */
export function PanelTitle({ id, label }: { id: string; label: string }) {
  const t = useI18n();
  const owner = useQuery({
    queryKey: ["browser-session", id],
    queryFn: async () => {
      try {
        return await getBrowserSession(id);
      } catch (error) {
        if (isNotFound(error)) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: Infinity,
  });
  const run = owner.data?.run;
  if (!run) return <span className="min-w-0 flex-1 truncate">{label}</span>;
  const title = t("livePanelRunTitle").replace("{workflow}", run.workflow_name).replace("{time}", runTime(run.started_at));
  return (
    <button
      type="button"
      title={t("livePanelOpenRun")}
      // 标题条整条是拖动把手;按在标题上是要跳过去,不是要拖。
      onPointerDown={(event) => event.stopPropagation()}
      onClick={() => gotoRecord("/workflows", OPEN_WORKFLOW_RUN, workflowRunLink(run.workflow_id, run.job_id))}
      className="pointer-events-auto min-w-0 flex-1 cursor-pointer truncate border-0 bg-transparent p-0 text-left text-inherit hover:text-foreground hover:underline"
    >
      {title}
    </button>
  );
}
