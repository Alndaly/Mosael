import React from "react";

import type { Confirmation } from "@/api/client";

/**
 * 一次对话的确认卡,交给对话里各行去查 —— context 和取它的 hook 住在这里,**不引任何 UI**
 * (见 app/contextIdentity.test:热更新整个重跑一个同时导出组件的模块,会造出第二个 context)。
 * 取卡、拍板的 provider 在 InlineConfirmations。
 */
export type Decisions = {
  sessionId: string;
  readOnly: boolean;
  /** 每次工具调用对应的那张卡(按卡上的 tool_call_id)。 */
  byToolCall: ReadonlyMap<string, Confirmation>;
  /** 还在等人拍板的卡。「判定中」的不在其中(隔离判断者正在看,几秒内多半自己放行)。 */
  pending: readonly Confirmation[];
  /** 一张待决卡底部那一行:三档按钮,或者只读时的一句话。 */
  actionsFor: (item: Confirmation) => React.ReactNode;
};

export const DecisionsContext = React.createContext<Decisions | null>(null);

const NO_CARDS: readonly Confirmation[] = [];

/** 对话里某次工具调用开的那张卡 —— 没有就是 null(不开卡的工具、外层没有挂 provider 的视图)。 */
export function useToolCallConfirmation(toolCallId: string): Confirmation | null {
  return React.useContext(DecisionsContext)?.byToolCall.get(toolCallId) ?? null;
}

/** 这次对话里还在等人拍板的卡。外层没有挂 provider 时是空的。 */
export function usePendingConfirmations(): readonly Confirmation[] {
  return React.useContext(DecisionsContext)?.pending ?? NO_CARDS;
}

/** 外层那个 provider 管的是哪次对话、是不是只读。没有 provider 就是 null。 */
export function useDecisionsScope(): { sessionId: string; readOnly: boolean } | null {
  const context = React.useContext(DecisionsContext);
  return context ? { sessionId: context.sessionId, readOnly: context.readOnly } : null;
}
