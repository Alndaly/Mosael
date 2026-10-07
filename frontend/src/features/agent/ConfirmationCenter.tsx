import { FLOATING_SURFACE } from "@/components/ui/floating";
import { confirmationKeys } from "@/api/queryKeys";
import { cn } from "@/lib/utils";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";

import { approveConfirmation, listConfirmations, rejectConfirmation } from "@/api/client";
import { approveLabel } from "@/features/agent/approveLabels";
import { invalidateAfterDecision } from "@/features/agent/confirmationCaches";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { useCardChoices } from "@/features/agent/cardChoices";
import { ConfirmationCard, useSettledCards } from "@/features/agent/ConfirmationCard";
import { useInlineConfirmSessions } from "@/features/agent/confirmSurface";


/**
 * Global confirmation cards (plan §16.2): external agents propose mutations,
 * nothing runs until the user approves here.
 *
 * 只拉**我能拍板**的卡(`decidable`)。这里每张卡都只有「批准 / 拒绝」两个按钮,列一张我批不了的卡就是一张
 * 点了回 403、又永远消不掉的卡:同事共享给我的对话里的卡正是这样 —— 我看得见,拍板只有主人。那种卡留在它自己的
 * 对话里就地摆着(InlineConfirmations 的只读样子,写着「等对话的主人拍板」),这里不再冒出来。
 */
export function ConfirmationCenter({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const pending = useQuery({
    queryKey: confirmationKeys.toDecide(workspaceId),
    queryFn: () => listConfirmations({ workspaceId, status: "pending", decidable: true }),
    refetchInterval: 2500,
    refetchOnWindowFocus: true,
  });

  const settled = useSettledCards(workspaceId);
  const settle = useMutation({
    mutationFn: ({ id, action, choices }: { id: string; action: "approve" | "reject"; choices?: Record<string, boolean> }) =>
      action === "approve" ? approveConfirmation(id, choices) : rejectConfirmation(id),
    onSuccess: (card) => {
      // **拍板之后卡就走**,只有一种例外:外部智能体(没有对话)的卡执行失败了。
      //  - 对话里的卡:结果收在那次对话里那次工具调用的一行里(见 ToolCalls),这里再留一张是第二份;
      //  - 执行成了 / 拒了:那件事本身就是结果,一张「✓ 已执行」挂在右上角只是要人再点一次 × 的东西
      //    (用户:「智能体审批通过后那个卡片不需要继续保留着的」);
      //  - 外部智能体的卡执行失败:原因只有这里看得到(它没有对话可收),留着等人读完移走。
      if (!card.session_id && card.status === "failed") settled.remember(card);
      invalidateAfterDecision(qc, workspaceId);
    },
  });

  // 在我能拍板的卡里,再按**归属**分工,而不是「有内联面就整体让位」:
  //  - 卡属于某个正开着的对话 → 那边内联显示,这里跳过(否则同一张卡出现两份);
  //  - 卡没有会话(MCP / 飞书等外部智能体)或它那次对话没开着 → 这里兜底,否则没人显示,
  //    智能体会一直干等。
  // 旧写法是「只要有任何内联面就整体返回 null」,于是一开聊天面板,外部智能体的卡也跟着被藏掉。
  const handledSessions = useInlineConfirmSessions();

  // 此刻在飞的是哪一张卡的哪一档 —— 同 InlineConfirmations。直接读 `settle.isPending` 的话,
  // 屏上每张卡的每个按钮会一起转:转圈的意思是"我正在做这件事",而它们没有。
  const busy = settle.isPending ? settle.variables : null;

  const settledIds = new Set(settled.cards.map((card) => card.id));
  const items = (pending.data ?? []).filter(
    (item) => (!item.session_id || !handledSessions.includes(item.session_id)) && !settledIds.has(item.id),
  );
  if (items.length === 0 && settled.cards.length === 0) return null;

  return (
    // 高度有界、自己滚:卡多了不能从窗口底下溢出去,最后那张的按钮就点不到了。
    <div
      className="fixed right-4 top-14 z-[60] grid max-h-[calc(100vh-4.5rem)] w-[360px] max-w-[calc(100vw-2rem)] grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-y-auto"
      role="region"
      aria-label={t("confirmTitle")}
    >
      {items.map((item) => (
        <ConfirmationCard
          key={item.id}
          item={item}
          eyebrow={`${t("confirmTitle")} · ${item.requested_by}`}
          className={cn(FLOATING_SURFACE, "animate-confirm-in")}
          actions={
            <SettleButtons
              tool={item.tool}
              busyAction={busy?.id === item.id ? busy.action : null}
              onSettle={(action, choices) => settle.mutate({ id: item.id, action, choices })}
            />
          }
        />
      ))}
      {settled.cards.map((card) => (
        <ConfirmationCard
          key={card.id}
          item={card}
          eyebrow={`${t("confirmTitle")} · ${card.requested_by}`}
          className={FLOATING_SURFACE}
          onDismiss={() => settled.dismiss(card.id)}
        />
      ))}
    </div>
  );
}

/**
 * 全局中心卡底的两个按钮。转的只有被点的那一个;同一张卡的另一个禁掉 —— 一张卡只能有一个结论。
 * 卡上拨过的开关(「建好就启用」,useCardChoices)批准时一起带走。
 */
function SettleButtons({
  tool,
  busyAction,
  onSettle,
}: {
  /** 卡的工具:有的卡上「批准」有更贴切的说法(见 approveLabels) */
  tool: string;
  busyAction: "approve" | "reject" | null;
  onSettle: (action: "approve" | "reject", choices: Record<string, boolean>) => void;
}) {
  const t = useI18n();
  const { values } = useCardChoices();
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-divider pt-2.5">
      <Button size="sm" loading={busyAction === "approve"} disabled={busyAction !== null} onClick={() => onSettle("approve", values)}>
        <Check /> {t(approveLabel(tool, "confirmApprove"))}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="ml-auto text-muted-foreground hover:text-destructive"
        loading={busyAction === "reject"}
        disabled={busyAction !== null}
        onClick={() => onSettle("reject", values)}
      >
        <X /> {t("confirmReject")}
      </Button>
    </div>
  );
}
