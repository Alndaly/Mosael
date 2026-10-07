import React from "react";
import { confirmationKeys } from "@/api/queryKeys";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, X } from "lucide-react";

import {
  approveConfirmation,
  getAgentSession,
  listConfirmations,
  rejectConfirmation,
  updateAgentSession,
  type Confirmation,
} from "@/api/client";
import { approveLabel } from "@/features/agent/approveLabels";
import { invalidateAfterDecision } from "@/features/agent/confirmationCaches";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { useCardChoices } from "@/features/agent/cardChoices";
import { ConfirmationCard } from "@/features/agent/ConfirmationCard";
import { registerInlineConfirmSurface } from "@/features/agent/confirmSurface";
import { DecisionsContext, usePendingConfirmations, type Decisions } from "@/features/agent/decisionsContext";


/**
 * 聊天流里的确认卡(Claude Code / Codex 式):智能体提出的写操作在对话里就地决策,
 * 三档动作——允许一次 / 本会话始终允许(按工具和档位记忆,撤不回的两档不提供)/ 拒绝。
 *
 * 此前确认只存在于右上角的全局 ConfirmationCenter,而它 z-index 低于 AI 助手浮窗,
 * 会被整块盖住——模型说"等待您的确认",用户却什么都看不到。现在:聊天面板打开时
 * 卡片就在对话里(本组件),全局中心让位(见 confirmSurface.ts);没有聊天面板时
 * 全局中心照常兜底(MCP / 飞书等外部智能体仍走它)。
 *
 * **卡摆在发起它的那次工具调用里**(按卡上的 `tool_call_id` 对上时间线里的那一行,见 ToolCalls),
 * 决定之后收成那一行里的一句状态。此前卡只知道属于哪次对话,统一堆在消息列表末尾,批完还留着一张
 * 「✓ 已执行」加 ×:一轮里连着请求五条配音,五张大卡一张接一张压在输入框上面(用户截图)。
 * 所以这里不再自己画一叠卡,而是给对话里的每一行一个查询口:这次调用有没有卡、卡到了哪一步。
 *
 * **「本会话始终允许」是服务端策略**,不是这里的一段自动批准。它此前记在 localStorage 里、
 * 由本组件挂载期间轮询自动批 —— 于是聊天面板一关组件就卸载,而 turn 还在跑:同一个"授权"的
 * 行为取决于某个 React 组件在不在,飞书和 MCP 那两条入口更是完全够不着。现在点它只是把(工具, 档位)
 * 写进会话的白名单,放行由后端在开卡的那一刻判定(domain/agent/autopilot)。
 */
/** 三档动作。顺序固定:允许一次 → 本会话始终允许 → 拒绝,从最小授权到最大再到否。 */
type Choice = "once" | "session" | "reject";

//: 主按钮只有一个:「允许一次」是最小的授权。「拒绝」推到行尾,和两个「允许」分开 —— 扫一眼就知道
//: 哪边是放行、哪边是否决;窄对话栏里换行时它也还是独自在右。
const CHOICES = [
  { choice: "once", icon: Check, label: "confirmAllowOnce", variant: "default", className: undefined },
  { choice: "session", icon: CheckCheck, label: "confirmAllowSession", variant: "outline", className: undefined },
  { choice: "reject", icon: X, label: "confirmReject", variant: "ghost", className: "ml-auto text-muted-foreground hover:text-destructive" },
] as const satisfies readonly {
  choice: Choice;
  icon: typeof Check;
  label: "confirmAllowOnce" | "confirmAllowSession" | "confirmReject";
  variant: "default" | "outline" | "ghost";
  className?: string;
}[];

/**
 * 「本会话始终允许」只给这几档(与后端 `autopilot.SESSION_ALLOWABLE` 同一份):最坏撤得回的(edit)和只花时间、
 * 花钱的(render-cost / ai-cost)。撤不回的两档(external / destroy)不给 —— 同一个工具名下,这两档的每一张卡
 * 后果各不相同(发到哪、删什么、跑哪张图),点一次就放开的是以后所有的;要持续放行这一类,走自动模式里的
 * 放行准则。不认识的档也不给:授权界面上认不出来不等于没事。
 */
const SESSION_ALLOWABLE = new Set(["edit", "render-cost", "ai-cost"]);

/**
 * 这张卡给不给「本会话始终允许」。除了档位,工具自己还可以声明**每一次都要人点头**(后端 `always_asks`,
 * 见 ConfirmableTool.always_asks):改技能会长期改变智能体以后的做法(ADR 0043),那几张卡不管哪一档都不给。
 */
function offersSessionAllow(item: Confirmation): boolean {
  return !item.always_asks && SESSION_ALLOWABLE.has(item.permission);
}

/**
 * 读回最近多少张卡来给工具行配状态。一次对话的卡多半在几十张以内;更早的那些对不上状态,行里只剩工具
 * 自己的成败 —— 少一句「已批准」,不会说错。上限与后端 CONFIRMATION_LIST_LIMIT 一致。
 */
const SESSION_CARD_WINDOW = 100;

/** 卡的状态只往前走(待决 → 已批准 → 已执行 / 失败;待决 → 拒绝 / 作废)。几份来源对不齐时,走得最远的那份是真的。 */
function progress(status: string): number {
  return status === "pending" ? 0 : status === "approved" ? 1 : 2;
}

const NO_CARDS: readonly Confirmation[] = [];

/**
 * 一次对话的确认卡:取卡、拍板、把结果交给对话里的各行。
 *
 * `sessionId` 就是**会话 id**:既是白名单挂靠的会话,也是确认卡的归属筛选键。
 * `readOnly`:同事共享来的对话 —— 卡照样摆出来,三档动作换成一句「等主人拍板」。这种卡只在这里出现:
 * 全局确认中心只列我能拍板的(见 ConfirmationCenter),面板关着时它也不会跑到那边去。
 * `live`:这次对话正有一轮在跑 —— 卡的状态会在这期间往前走(批准 → 执行完),要跟着刷。
 */
export function ConfirmationsProvider({
  workspaceId,
  sessionId,
  readOnly = false,
  live = false,
  children,
}: {
  workspaceId: string;
  sessionId: string;
  readOnly?: boolean;
  live?: boolean;
  children: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();

  // 挂载登记:全局中心据此知道**这个会话**的卡已经有人管了,不再重复显示(其余照常兜底)。
  React.useEffect(() => registerInlineConfirmSurface(sessionId), [sessionId]);

  // **只取本会话的卡**。此前拉的是整个工作区的 pending —— 于是同工作区其它对话、工作流节点、
  // MCP/飞书外部智能体的确认卡都会挤进当前对话,用户以为授的是「这次对话」,实际授的是别人的。
  const pending = useQuery({
    queryKey: confirmationKeys.pending(workspaceId, sessionId),
    queryFn: () => listConfirmations({ workspaceId, status: "pending", sessionId }),
    refetchInterval: 1500,
    refetchOnWindowFocus: true,
  });
  // 有了结论的卡:给对应那一行配一句状态。别处批的(自动放行、飞书、全局中心)也要看得到,所以从服务端读,
  // 不只记自己点过的那几张。
  const recent = useQuery({
    queryKey: confirmationKeys.session(workspaceId, sessionId),
    queryFn: () => listConfirmations({ workspaceId, sessionId, limit: SESSION_CARD_WINDOW }),
    refetchInterval: live ? 2000 : false,
    refetchOnWindowFocus: true,
  });

  /**
   * 自己刚拍板的那几张:接口回来的那一份。两份列表刷新之前,它让那一行**立刻**从卡变成状态 ——
   * 不然点完「允许一次」,卡还要原样再挂一个轮询周期。
   *
   * `scope` 换了(切到另一个会话)就当作清空,不用 effect 去追。
   */
  const [decided, setDecided] = React.useState<{ scope: string; cards: Confirmation[] }>({ scope: sessionId, cards: [] });
  const mine = decided.scope === sessionId ? decided.cards : NO_CARDS;

  /**
   * 三档动作走**同一个** mutation —— 因为「谁在转」要由它的变量说了算。
   *
   * 此前是两个 mutation、三个按钮共读 `isPending`,于是点任何一个,同屏所有卡的所有按钮一起转。
   * 转圈的意思是"我正在做这件事";六个一起转说的是另一件事,而这张卡正是需要知情同意的地方。
   * 变量里带上卡的 id 和选了哪一档,`decide.variables` 就直接是"此刻在飞的是哪一个"。
   *
   * 「本会话始终允许」的两步(写白名单 → 批准)也收在这里顺序 await:它对用户是一个动作,
   * 就该从头到尾转同一个按钮 —— 拆成两个 mutation 时,第二步一起手,转的会变成隔壁那个。
   */
  const decide = useMutation({
    mutationFn: async ({
      id,
      tool,
      permission,
      choice,
      choices,
    }: {
      id: string;
      tool: string;
      permission: string;
      choice: Choice;
      /** 卡上拨的开关(「建好就启用」),批准时带上。 */
      choices: Record<string, boolean>;
    }) => {
      if (choice === "session") {
        // 先写白名单再批准:反过来的话,同一工具的下一张卡可能赶在白名单落库前就被判成手动。
        // 记的是**(工具, 这张卡的档位)**:以后同一工具不高于这一档的卡才放行(同一工具取最高的那条由后端归并)。
        const session = await getAgentSession(sessionId);
        const next = [...(session.auto_allow_tools ?? []), { tool, permission }];
        await updateAgentSession(sessionId, { auto_allow_tools: next });
        void qc.invalidateQueries({ queryKey: ["agent-session", sessionId] });
      }
      return choice === "reject" ? rejectConfirmation(id) : approveConfirmation(id, choices);
    },
    onSuccess: (card) => {
      setDecided((prev) => ({
        scope: sessionId,
        cards: [...(prev.scope === sessionId ? prev.cards : []).filter((one) => one.id !== card.id), card],
      }));
      invalidateAfterDecision(qc, workspaceId);
    },
  });
  // 此刻在飞的是哪一张卡的哪一档。没有就是 null。
  const busy = decide.isPending ? decide.variables : null;
  const { mutate } = decide;

  const actionsFor = React.useCallback((item: Confirmation): React.ReactNode =>
    readOnly ? (
      <p className="m-0 border-t border-divider pt-2.5 text-ui-xs text-muted-foreground">{t("agentDecisionOwnerOnly")}</p>
    ) : (
      <DecisionButtons
        item={item}
        busyChoice={busy?.id === item.id ? busy.choice : null}
        onDecide={(choice, choices) => mutate({ id: item.id, tool: item.tool, permission: item.permission, choice, choices })}
      />
    ), [busy, mutate, readOnly, t]);

  // 对话里每一次工具调用的那一行都读这一份:面板每秒走一次的计时也会让这里重渲,值不变就别让它们跟着重渲。
  const value = React.useMemo((): Decisions => {
    // 三份来源按卡合并,每张取走得最远的那份。「判定中」的待决卡只出现在 recent 里(待决列表把它筛掉了),
    // 它不该被画成一张等人点的卡 —— 所以 recent 里的待决一律不收。
    const cards = new Map<string, Confirmation>();
    const merge = (card: Confirmation) => {
      const known = cards.get(card.id);
      if (!known || progress(card.status) >= progress(known.status)) cards.set(card.id, card);
    };
    for (const card of pending.data ?? []) merge(card);
    for (const card of recent.data ?? []) if (card.status !== "pending") merge(card);
    for (const card of mine) merge(card);

    const byToolCall = new Map<string, Confirmation>();
    const waiting: Confirmation[] = [];
    for (const card of cards.values()) {
      if (card.tool_call_id) byToolCall.set(card.tool_call_id, card);
      if (card.status === "pending") waiting.push(card);
    }
    return { sessionId, readOnly, byToolCall, pending: waiting, actionsFor };
  }, [sessionId, readOnly, pending.data, recent.data, mine, actionsFor]);

  return <DecisionsContext.Provider value={value}>{children}</DecisionsContext.Provider>;
}

/**
 * 一张卡底部的三档动作。转的只有被点的那一个;同一张卡的另外两个禁掉(一张卡只能有一个结论),
 * 别的卡完全不受影响 —— 它等的不是同一件事。卡上拨过的开关(useCardChoices)在点下去那一刻带走。
 */
function DecisionButtons({
  item,
  busyChoice,
  onDecide,
}: {
  item: Confirmation;
  /** 这张卡此刻在飞的是哪一档;没有就是 null。 */
  busyChoice: Choice | null;
  onDecide: (choice: Choice, choices: Record<string, boolean>) => void;
}) {
  const t = useI18n();
  const { values } = useCardChoices();
  const sessionAllow = offersSessionAllow(item);
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-divider pt-2.5">
      {CHOICES.filter(({ choice }) => choice !== "session" || sessionAllow).map(({ choice, icon: Icon, label, variant, className }) => (
        <Button
          key={choice}
          size="sm"
          variant={variant}
          className={className}
          loading={busyChoice === choice}
          disabled={busyChoice !== null}
          onClick={() => onDecide(choice, values)}
        >
          <Icon /> {t(choice === "once" ? approveLabel(item.tool, label) : label)}
        </Button>
      ))}
      {sessionAllow ? null : (
        <span className="text-ui-2xs text-muted-foreground">{t(item.always_asks ? "confirmAlwaysAsks" : "confirmAsksEveryTime")}</span>
      )}
    </div>
  );
}

/** 一张等人拍板的卡,底部是三档动作(只读时是一句话)。只在 ConfirmationsProvider 里面有动作可给。 */
export function PendingConfirmationCard({ item }: { item: Confirmation }) {
  const t = useI18n();
  const context = React.useContext(DecisionsContext);
  return (
    // 「跳到最新」那颗按钮靠这个标记找到它(卡在视口外时,把人带到卡跟前)。
    <div data-pending-decision="" className="min-w-0">
      <ConfirmationCard item={item} eyebrow={t("confirmAgentRequest")} actions={context?.actionsFor(item)} />
    </div>
  );
}

/**
 * 对不上对话里任何一行的待决卡。
 *
 * 这一行此刻不在屏上:流还没把那次调用送到(卡比工具行先到)、流没接上、或者换到了轨迹 / 子代理视图。
 * 卡**不能因为找不到位置就看不见** —— 智能体正阻塞在那里等它,看不见就是干等到超时。所以它们退回
 * 列表末尾(这正是那一轮此刻的位置)。`placed` 是对话里画出来的那些工具调用 id。
 */
export function UnplacedConfirmations({ placed }: { placed: ReadonlySet<string> }) {
  const t = useI18n();
  const items = usePendingConfirmations().filter((item) => !item.tool_call_id || !placed.has(item.tool_call_id));
  if (items.length === 0) return null;
  return (
    // 与消息内容列同宽(780px 居中):此前裸 grid 吃满整个滚动区,确认卡横跨全屏。
    <div className="mx-auto grid w-full max-w-[780px] grid-cols-[minmax(0,1fr)] gap-2" role="region" aria-label={t("confirmTitle")}>
      {items.map((item) => (
        <PendingConfirmationCard key={item.id} item={item} />
      ))}
    </div>
  );
}
