import { CornerDownRight, Trash2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/**
 * 还没发出去的那几条 —— 输入框上方那一条条。
 *
 * 它们不属于对话记录(还没轮到它们),所以不在滚动区里,而是贴着输入框排在外面;每一条可以
 * 插进正在跑的这一轮(Steer),也可以撤掉。
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
  onCancel,
  steering,
  cancelling,
}: {
  messages: { id: string; content: string }[];
  /** 宽度与留边 —— 必须和这个界面的输入框写成同一个值。 */
  className?: string;
  onSteer: (messageId: string) => void;
  onCancel: (messageId: string) => void;
  steering?: boolean;
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
          <span className="min-w-0 flex-1 truncate text-foreground" title={message.content}>
            {message.content}
          </span>
          <button
            type="button"
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-[7px] py-[3px] text-ui-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            disabled={steering}
            onClick={() => onSteer(message.id)}
            title={t("chatSteerHint")}
          >
            <CornerDownRight size={11} /> {t("chatSteerAction")}
          </button>
          <button
            type="button"
            className="inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent px-[7px] py-[3px] text-ui-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            disabled={cancelling}
            onClick={() => onCancel(message.id)}
            aria-label={t("chatQueuedCancel")}
          >
            <Trash2 size={12} />
          </button>
        </div>
      ))}
    </>
  );
}
