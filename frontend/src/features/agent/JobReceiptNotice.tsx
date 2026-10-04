import { ListChecks } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** 后台任务回执那条消息的形状(后端 host.JOB_RECEIPT_ROLE)。 */
export const JOB_RECEIPT_ROLE = "job_receipt";

type ReceiptPayload = { job_id?: string; undelivered?: boolean } | null | undefined;

/** 还没交给智能体的回执:这一轮结束时一并交出去,在那之前画在正在跑的那一轮下面。 */
export function isWaitingReceipt(message: { role: string; payload?: unknown }): boolean {
  return message.role === JOB_RECEIPT_ROLE && Boolean((message.payload as ReceiptPayload)?.undelivered);
}

/**
 * 后台任务跑完送回来的回执 —— 对话里**一行任务通知**,不是一条用户消息。
 *
 * 此前回执借用户的名义进会话:靠右摆成用户气泡(用户:「这不是我发送的」),会话正忙时还排进输入框上方的
 * 待发消息,带着 Steer 和删除(「全都在消息队列中了」)。它不是谁说的话,只是一件事的结果,所以形状和
 * 「已整理上下文」那道分界同一类:安静的一行,任务 id 只在悬停提示里(那是给查问题的人看的)。
 *
 * 还没交给智能体的那条后面说一句「这一轮结束后交给智能体」—— 不说的话,人看着它躺在那儿而智能体没反应,
 * 会以为它被忽略了。
 */
export function JobReceiptNotice({
  content,
  payload,
  className,
}: {
  content: string;
  payload: unknown;
  className?: string;
}) {
  const t = useI18n();
  const receipt = payload as ReceiptPayload;
  return (
    <Hint label={t("chatFromJob")} hint={receipt?.job_id}>
      <div
        data-job-receipt=""
        className={cn("flex min-w-0 items-start gap-1.5 px-0.5 text-ui-xs leading-[1.6] text-muted-foreground", className)}
      >
        <ListChecks size={12} className="mt-[3px] flex-none" aria-hidden />
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {content}
          {receipt?.undelivered ? <span className="opacity-70"> · {t("chatReceiptWaiting")}</span> : null}
        </span>
      </div>
    </Hint>
  );
}
