import React from "react";

import { ConfirmationsProvider, UnplacedConfirmations } from "@/features/agent/InlineConfirmations";
import { useDecisionsScope, usePendingConfirmations } from "@/features/agent/decisionsContext";
import { InlineQuestions } from "@/features/agent/InlineQuestions";
import { JumpToLatest, type StickToBottom } from "@/features/agent/stickToBottom";

/**
 * 这个会话里**等人拍板**的两种卡:确认卡问「这件事能不能做」,选择卡问「你要哪一个」。
 *
 * 两个对话入口(AI 工作台、画布助手)都放,工作台的对话 / 轨迹 / 子代理视图也都放。此前每处各写一对,
 * 轨迹视图就是漏写了才让两张卡一切视图就消失的。
 *
 * 分两层:
 *   · `SessionDecisions` 包住整个对话区 —— 取卡、拍板,并让对话里**每一次工具调用的那一行**查得到自己的卡
 *     (等决定时卡就摆在那一行下面,决定之后收成那一行里的一句状态,见 ToolCalls);
 *   · `PendingDecisions` 摆在列表末尾 / 输入框上方 —— 只放**对不上任何一行**的待决卡(那一行此刻不在屏上),
 *     和选择卡。
 *
 * `readOnly`:同事共享来的对话。卡照样看得见(等的是什么,他该知道),拍板的按钮不给 —— 替主人拍板是在
 * 别人的对话里写,后端也只认主人(domain/agent/sessions)。
 */
export function SessionDecisions({
  workspaceId,
  sessionId,
  readOnly = false,
  live = false,
  children,
}: {
  workspaceId: string;
  /** 没有会话(还没开口)就什么都不取,原样渲染里面的东西。 */
  sessionId: string | null;
  readOnly?: boolean;
  /** 这次对话正有一轮在跑:卡的状态会在这期间往前走,要跟着刷。 */
  live?: boolean;
  children: React.ReactNode;
}) {
  if (!sessionId) return <>{children}</>;
  return (
    <ConfirmationsProvider workspaceId={workspaceId} sessionId={sessionId} readOnly={readOnly} live={live}>
      {children}
    </ConfirmationsProvider>
  );
}

/**
 * `placed`:对话里画出来的工具调用 id —— 对得上其中一行的卡已经摆在那一行里了,这里不再画第二份。
 * 不在对话视图里(轨迹、子代理)时传空集合:那时没有任何一行在屏上,待决的卡全摆在这里。
 */
export function PendingDecisions({ placed }: { placed: ReadonlySet<string> }) {
  const scope = useDecisionsScope();
  if (!scope) return null;
  return (
    <>
      <UnplacedConfirmations placed={placed} />
      <InlineQuestions sessionId={scope.sessionId} readOnly={scope.readOnly} />
    </>
  );
}

/**
 * 「回到最新」,知道有没有一张卡在等人拍板。
 *
 * 有的话按钮改说「有请求等你确认」,点了把那张卡滚进视口(它摆在发起它的那次工具调用里,人往上翻着历史时
 * 在视口外)。`area` 是装着这段对话的那一块:在它里面找卡,别处(另一个面板)的卡不算。
 */
export function JumpToLatestOrDecision({
  stick,
  label,
  newLabel,
  decisionLabel,
  area,
}: {
  stick: Pick<StickToBottom<HTMLElement>, "pinned" | "unseen" | "scrollToBottom">;
  label: string;
  newLabel: string;
  decisionLabel: string;
  area: React.RefObject<HTMLElement | null>;
}) {
  const waiting = usePendingConfirmations().length > 0;
  const attention = waiting
    ? { label: decisionLabel, target: () => area.current?.querySelector<HTMLElement>("[data-pending-decision]") ?? null }
    : null;
  return <JumpToLatest stick={stick} label={label} newLabel={newLabel} attention={attention} />;
}
