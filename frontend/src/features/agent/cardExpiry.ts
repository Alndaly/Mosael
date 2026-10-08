/**
 * 作废的确认卡(`status: "expired"`)怎么说(ADR 0007 修订 2026-10-08)。
 *
 * 卡是一轮**阻塞着等**的东西:一轮结束(用户停止、卡等到点、整轮超时、失败、照常答完)时,后端把它还在等的卡结成
 * `expired`,`error` 里记的是由头的码(见 backend domain/agent/card_expiry 的 EXPIRY_*)。界面按码说人话,不把码本身
 * 摆出来,也不把它当成「出错了」标红 —— 卡作废是那一轮结束的自然结果。
 */

export const EXPIRED = "expired";

export type ExpiryLabel = "confirmExpiredTurnStopped" | "confirmExpiredWaitTimeout" | "confirmExpiredTurnEnded";

export function expiryLabel(reason: string | null | undefined): ExpiryLabel {
  if (reason === "turn_stopped") return "confirmExpiredTurnStopped";
  if (reason === "wait_timeout") return "confirmExpiredWaitTimeout";
  return "confirmExpiredTurnEnded";
}
