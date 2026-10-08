import React from "react";
import { createPortal } from "react-dom";
import { FLOATING_SURFACE } from "@/components/ui/floating";
import { confirmationKeys } from "@/api/queryKeys";
import { cn } from "@/lib/utils";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronUp, CornerUpLeft, ShieldAlert, X } from "lucide-react";
import { toast } from "sonner";

import { type AgentSession, approveConfirmation, getAgentSession, listConfirmations, rejectConfirmation } from "@/api/client";
import { approveLabel } from "@/features/agent/approveLabels";
import { invalidateAfterDecision } from "@/features/agent/confirmationCaches";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { useCardChoices } from "@/features/agent/cardChoices";
import { ConfirmationCard, useSettledCards } from "@/features/agent/ConfirmationCard";
import { useInlineConfirmSessions } from "@/features/agent/confirmSurface";
import { canGoHome, openedIn } from "@/features/agent/homeLabel";
import { Truncate } from "@/components/ui/truncate";
import { useHeaderStatusSlot } from "@/components/layout/headerSlot";
import { InChromeStatusSlot, useChromeStatusSlot } from "@/components/app/chromeStatusSlot";
import { APP_CHROME } from "@/components/ui/appChrome";
import { StepNativeViewAside } from "@/components/ui/nativeViewAside";
import { leaveNativeView, useNativeViewInFront } from "@/lib/nativeView";


/**
 * Global confirmation cards (plan §16.2): external agents propose mutations,
 * nothing runs until the user approves here.
 *
 * 只拉**我能拍板**的卡(`decidable`)。这里每张卡都只有「批准 / 拒绝」两个按钮,列一张我批不了的卡就是一张
 * 点了回 403、又永远消不掉的卡:同事共享给我的对话里的卡正是这样 —— 我看得见,拍板只有主人。那种卡留在它自己的
 * 对话里就地摆着(InlineConfirmations 的只读样子,写着「等对话的主人拍板」),这里不再冒出来。
 */
export function ConfirmationCenter({
  workspaceId,
  goHome,
}: {
  workspaceId: string;
  /**
   * 「回到那里」:在那段对话的家那一处接着它,再跳过去(装配层给 —— 回到 ComfyUI 那一张要打开工作台,那是插件那一侧的事)。
   * 不给就只说在哪开的。
   */
  goHome?: (session: AgentSession) => void | Promise<void>;
}) {
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
  //: **收得起来**(智能体那一路 AGENT-10):中心浮在页面右上角,三百多像素宽,正好盖住页面工具条的右半截(笔记页的「AI 助手」开关、
  //: 面板标题栏的「新对话 / 关闭」)—— 别处有一段对话在等批卡时,眼前这一页那几颗按钮点不到。收起来是**顶栏里**的一颗胶囊,写着几张
  //: 在等(见 headerSlot:还浮在页面上的话,盖住的还是那几颗);来了新卡自己再展开(收起的是「这几张」,不是「以后的都别给我看」)。
  const [tucked, setTucked] = React.useState<ReadonlySet<string>>(() => new Set());
  const headerSlot = useHeaderStatusSlot();
  //: **原生视图在前台时卡不自己跳出来**(ADR 0051 §3):内嵌浏览器、工作台的画布盖在一切 DOM 上,右上角的卡在它底下 ——
  //: 智能体等着人拍板,人看不见卡。可也不该自己让开:人正在登录、正在看画布,画面突然冻住、盖上一张卡。所以收成外壳顶栏上
  //: 的「N 张卡等你拍板」,点了才请视图让开、把卡展开;收起、拍完,视图回来。视图收起,一切照旧。
  const chromeSlot = useChromeStatusSlot();
  const overNativeView = useNativeViewInFront() && chromeSlot !== null;
  const [openOverView, setOpenOverView] = React.useState(false);
  if (openOverView && (!overNativeView || items.length === 0)) setOpenOverView(false);
  const allTucked = items.length > 0 && items.every((item) => tucked.has(item.id)) && settled.cards.length === 0;
  if (items.length === 0 && settled.cards.length === 0) return null;
  //: 视图在前台、没有要拍板的卡(只剩执行失败的那几张留着读):等视图收起再摆出来,不为它们亮一个「0 张」
  if (overNativeView && items.length === 0) return null;
  if (allTucked || (overNativeView && !openOverView)) {
    const waiting = t("confirmCenterWaiting").replace("{n}", String(items.length));
    const pill = (
      <Button
        size={overNativeView ? chromeSlot.size : "sm"}
        variant="outline"
        className={cn("gap-1.5 rounded-full", !headerSlot && !overNativeView && FLOATING_SURFACE)}
        aria-label={waiting}
        data-confirm-center-pill=""
        onClick={() => {
          setTucked(new Set());
          if (overNativeView) setOpenOverView(true);
        }}
      >
        <ShieldAlert size={14} aria-hidden />
        {/* 窄窗口顶栏放不下一句话(搜索框也只剩图标):只留数字。 */}
        <span className="max-[760px]:hidden">{waiting}</span>
        <span className="tabular-nums min-[761px]:hidden">{items.length}</span>
      </Button>
    );
    if (overNativeView) return <InChromeStatusSlot slot={chromeSlot}>{pill}</InChromeStatusSlot>;
    return headerSlot ? (
      createPortal(pill, headerSlot)
    ) : (
      <div className="fixed right-4 top-14 z-[60]" role="region" aria-label={t("confirmTitle")}>
        {pill}
      </div>
    );
  }

  return (
    // 高度有界、自己滚:卡多了不能从窗口底下溢出去,最后那张的按钮就点不到了。
    // 在原生视图前面展开时(人点了外壳上的小标):抬过外壳、请视图让开;卡里点、按 Esc 不关底下开着的弹窗(见 appChrome)。
    <div
      {...(overNativeView ? APP_CHROME : undefined)}
      className={cn(
        "fixed right-4 top-14 grid max-h-[calc(100vh-4.5rem)] w-[360px] max-w-[calc(100vw-2rem)] grid-cols-[minmax(0,1fr)] content-start gap-2 overflow-y-auto",
        overNativeView ? "z-[210]" : "z-[60]",
      )}
      role="region"
      aria-label={t("confirmTitle")}
    >
      {overNativeView && <StepNativeViewAside />}
      {items.length > 0 && (
        <div className="flex justify-end">
          <Button
            size="xs"
            variant="ghost"
            className={cn(FLOATING_SURFACE, "gap-1 text-muted-foreground")}
            onClick={() => {
              setTucked(new Set(items.map((item) => item.id)));
              setOpenOverView(false);
            }}
          >
            <ChevronUp size={13} aria-hidden />
            {t("confirmCenterTuck")}
          </Button>
        </div>
      )}
      {items.map((item) => (
        <ConfirmationCard
          key={item.id}
          item={item}
          //: 挂在对话上的卡是本工作区自己的智能体开的,不是「外部智能体」—— 下一行写着是哪段对话(CardHome)。
          eyebrow={item.session_id ? t("confirmAgentRequest") : `${t("confirmTitle")} · ${item.requested_by}`}
          className={cn(FLOATING_SURFACE, "animate-confirm-in")}
          actions={
            <>
              {/* 好几段对话同时在跑时,看得出是谁在问(ADR 0044 §9):那段对话没开着,卡才落到这里。 */}
              {item.session_id && <CardHome sessionId={item.session_id} goHome={goHome} />}
              <SettleButtons
                tool={item.tool}
                busyAction={busy?.id === item.id ? busy.action : null}
                onSettle={(action, choices) => settle.mutate({ id: item.id, action, choices })}
              />
            </>
          }
        />
      ))}
      {settled.cards.map((card) => (
        <ConfirmationCard
          key={card.id}
          item={card}
          eyebrow={card.session_id ? t("confirmAgentRequest") : `${t("confirmTitle")} · ${card.requested_by}`}
          className={FLOATING_SURFACE}
          onDismiss={() => settled.dismiss(card.id)}
        />
      ))}
    </div>
  );
}

/** 卡挂着的那段对话是在哪开的,回得去就给一颗「回到那里」。 */
function CardHome({ sessionId, goHome }: { sessionId: string; goHome?: (session: AgentSession) => void | Promise<void> }) {
  const t = useI18n();
  //: 和面板同一个键:那段对话开着时这份早就在缓存里。
  const session = useQuery({ queryKey: ["agent-session", sessionId], queryFn: () => getAgentSession(sessionId) });
  if (!session.data) return null;
  const home = session.data;
  return (
    <div className="flex min-w-0 items-center gap-2 text-ui-xs text-muted-foreground">
      <Truncate className="min-w-0 flex-1">{openedIn(t, home)}</Truncate>
      {goHome && canGoHome(home) && (
        <Button
          size="xs"
          variant="ghost"
          className="shrink-0"
          //: 去别处:内嵌浏览器、工作台在前台时先收起来再走(ADR 0051)
          onClick={() => {
            void leaveNativeView();
            void Promise.resolve(goHome(home)).catch((error: Error) => toast.error(error.message));
          }}
        >
          <CornerUpLeft /> {t("agentGoHome")}
        </Button>
      )}
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
