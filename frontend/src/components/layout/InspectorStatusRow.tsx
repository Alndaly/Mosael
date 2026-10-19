import type { ReactNode } from "react";
import { Ban, Circle, CircleCheck, CircleDot, CircleX } from "lucide-react";

import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

/**
 * 检查器里「一行」的语法 —— **任务计划与后台任务共用这一份**。
 *
 * 维护者截图:同一个面板里,上面「任务计划」每行是 状态圈 + 文字,右侧什么都没有;
 * 下面「后台任务」每行却多一个类型图标(🎤/🔗)、右侧还写一遍「成功」。两块并排(上下),
 * 每一行说的都是同一件事 —— 这一条做到哪了 —— 长得不一样,眼睛就要为每块重新学一次。
 *
 * 统一成:
 *
 *     圈  文字                        ← 状态**只在左边这一处**;主行右侧只放动作(取消、前往结果)
 *     └─ 说明行(进度、用时、失败原因) ← 次要信息留在主行下方,和文字同一左缘
 *
 * 类型图标两边都不画:计划那侧没有,任务这侧也不该多一个。这一整块只有一种"行",没有第二种。
 *
 * 状态词也在这里归一:计划说 `done` / `in_progress`,任务说 `succeeded` / `cancelled` / `queued`,
 * 到这一行都变成同一个 `AgentStatus`。**只有这一张表**,计划、任务、最近工具都从这里取。
 */
export type AgentStatus = "done" | "running" | "error" | "pending" | "cancelled";

export function toAgentStatus(raw: string | null | undefined): AgentStatus {
  if (raw === "done" || raw === "succeeded") return "done";
  if (raw === "running" || raw === "in_progress") return "running";
  if (raw === "error" || raw === "failed") return "error";
  if (raw === "cancelled" || raw === "canceled") return "cancelled";
  //: `queued` 也是这一列:排队 = 还没开始,和计划里「未开始」同一颗空心圈,不是"正在做"。
  return "pending";
}

const ICONS = {
  done: { Icon: CircleCheck, className: "text-success" },
  running: { Icon: CircleDot, className: "animate-pulse text-primary" },
  error: { Icon: CircleX, className: "text-destructive" },
  //: 停下不是失败:灰色的一道斜杠,和失败的红色叉分开。
  cancelled: { Icon: Ban, className: "text-muted-foreground" },
  pending: { Icon: Circle, className: "text-muted-foreground/60" },
} as const;

/**
 * 「这一条现在怎么样了」的图标 —— **只有这一种**。
 *
 * 计划步骤、后台任务、最近工具调用说的是同一件事(做完了 / 正在做 / 失败了 / 还没开始),
 * 此前各画各的:计划用 12px 的 lucide 圆圈,任务用 Loader2 + 实心绿勾 + 7px 红点,工具用 7px 色点。
 * 并排放在同一个面板里,眼睛会以为它们是几类东西。
 */
export function AgentStatusIcon({
  status,
  className,
  size = 12,
}: {
  status: AgentStatus;
  className?: string;
  size?: number;
}) {
  const { Icon, className: tone } = ICONS[status];
  return (
    //: 外面这层只为两件事:保证格子不收缩,以及给测试/样式一个稳定的状态标记
    //: (`data-agent-status`)—— 直接挂在 svg 上要过 lucide 的 props 类型,不值当。
    <span className={cn("inline-flex shrink-0", tone, className)} data-agent-status={status}>
      <Icon size={size} aria-hidden />
    </span>
  );
}

/** 主行:左缘一个状态圈,右边文字。和「任务计划」的每一行是同一份几何。 */
const ROW_CLASS =
  "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-1.5 text-ui-xs leading-[1.5]";

/** 能点的那一行:圈 + 文字整块都是热区。负外边距 + 等量内边距,只把悬停底色向外扩一圈,文字不动。 */
const ACTIVATABLE_ROW_CLASS =
  "-mx-1 -my-0.5 cursor-pointer rounded-md px-1 py-0.5 transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * 检查器里的一行。
 *
 * @param status 归一过的状态(见 `toAgentStatus`)—— 圈画在左缘,别处不再表达状态。
 * @param note 主行下方那一行:进度、用时、失败原因。**不要**把这类信息塞进 `trailing`。
 * @param trailing 主行右缘只放动作(取消、前往结果);它不参与"这行是什么状态"。
 * @param onActivate 给了就是可点的整行(后台任务点开详情);仍然保留键盘 Enter / 空格。
 */
export function InspectorStatusRow({
  status,
  children,
  note,
  trailing,
  onActivate,
  className,
}: {
  status: AgentStatus;
  children: ReactNode;
  note?: ReactNode;
  trailing?: ReactNode;
  onActivate?: () => void;
  className?: string;
}) {
  const content = (
    <>
      <AgentStatusIcon status={status} className="mt-[3px]" />
      <div className="min-w-0">{children}</div>
    </>
  );

  return (
    <div className={cn("grid min-w-0 gap-0.5", className)}>
      <div className={cn("grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start", trailing && "gap-1")}>
        {onActivate ? (
          <div
            role="button"
            tabIndex={0}
            data-inspector-row=""
            className={cn(ROW_CLASS, ACTIVATABLE_ROW_CLASS)}
            onClick={onActivate}
            onKeyDown={(event) => {
              if (isImeKeystroke(event)) return;
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              onActivate();
            }}
          >
            {content}
          </div>
        ) : (
          <div data-inspector-row="" className={ROW_CLASS}>
            {content}
          </div>
        )}
        {trailing ? <div className="-my-1 flex shrink-0 items-center gap-1">{trailing}</div> : null}
      </div>
      {note ? (
        //: 缩进 = 圈的 12px + 间距 6px:说明和上面的文字同一个左缘,而不是挂在主行右边。
        <div
          data-inspector-note=""
          className="grid min-w-0 gap-0.5 pl-[18px] text-ui-2xs leading-normal text-muted-foreground"
        >
          {note}
        </div>
      ) : null}
    </div>
  );
}
