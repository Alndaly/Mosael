import { CornerDownRight, Send, Trash2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 还没发出去的那几条 —— 输入框上方那一条条。
 *
 * 它们不属于对话记录(还没轮到它们),所以不在滚动区里,而是贴着输入框排在外面;每一条可以
 * 插进正在跑的这一轮(Steer),也可以撤掉。
 *
 * **按了停止,排着的那几条不自己发出去**(D63):它们带着 `held` 留在这里,那一格换成「继续发送」—— 按停止往往是「它跑偏了」,
 * 停之前顺手排的那句多半是基于跑偏的内容写的,该由人看一眼再决定发不发。
 *
 * **和输入框同宽,由调用方给。** 这一条此前在对话页和画布助手里各抄了一遍,两处都写死
 * `w-full max-w-[780px]` —— 而两边的输入框各有各的留边(对话页 `calc(100%-32px)`、画布助手
 * `mx-2`)。窗口一窄,输入框缩进去了,这一条还顶着两侧边缘:同一件事的两个盒子对不齐。
 * 抄一遍就意味着日后改了一处忘了另一处,所以宽度从外面传进来,别的一概共用这一份。
 */
export function QueuedMessages({
  messages,
  className,
  onSteer,
  onResume,
  onCancel,
  steering,
  resuming,
  cancelling,
}: {
  messages: { id: string; content: string; payload?: unknown }[];
  /** 宽度与留边 —— 必须和这个界面的输入框写成同一个值。 */
  className?: string;
  onSteer: (messageId: string) => void;
  /** 「继续发送」:按停止时扣下的那条放回队列。 */
  onResume: (messageId: string) => void;
  onCancel: (messageId: string) => void;
  steering?: boolean;
  resuming?: boolean;
  cancelling?: boolean;
}) {
  const t = useI18n();
  return (
    <>
      {messages.map((message) => (
        <div
          className={cn(
            "mb-1.5 flex items-center gap-2 rounded-lg border border-border bg-control px-2.5 py-[7px] text-xs",
            className,
          )}
          key={message.id}
        >
          <CornerDownRight size={12} className="shrink-0 text-muted-foreground" />
          <Truncate className="flex-1 text-foreground">{message.content}</Truncate>
          {isHeld(message) ? (
            <Hint label={t("chatQueuedResumeHint")}>
              <Button variant="inline" className="shrink-0" disabled={resuming} onClick={() => onResume(message.id)}>
                <Send /> {t("chatQueuedResume")}
              </Button>
            </Hint>
          ) : (
            <Hint label={t("chatSteerHint")}>
              <Button variant="inline" className="shrink-0" disabled={steering} onClick={() => onSteer(message.id)}>
                <CornerDownRight /> {t("chatSteerAction")}
              </Button>
            </Hint>
          )}
          <IconButton
            unstyled
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-[7px] py-[3px] text-ui-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            disabled={cancelling}
            onClick={() => onCancel(message.id)}
            label={t("chatQueuedCancel")}
          >
            <Trash2 size={12} />
          </IconButton>
        </div>
      ))}
    </>
  );
}

/** 按停止时扣下的那一条(后端 host._hold_queue 打的标):等人点「继续发送」,不会自己发出去。 */
function isHeld(message: { payload?: unknown }): boolean {
  return Boolean((message.payload as { held?: boolean } | null | undefined)?.held);
}
