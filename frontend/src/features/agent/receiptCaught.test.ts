/**
 * 「智能体接住了这条回执吗」—— 只拿已有事实判,不新造状态。
 *
 * 维护者 2026-10-18 拍板的信息架构:后台任务回执**不该**在对话里当一条独立消息常驻 ——
 * 对话里留的是结论(智能体那句话);回执只在**智能体没接住**时才显式出现。
 *
 * 判据两样,都是后端已经写着的事实:
 *   1. 回执自己的 `payload.undelivered` —— 还没交给智能体(交给它时后端会把键删掉,见 host._hand_over_receipts);
 *   2. 回执**之后**有没有一条助手消息,且那一轮不是被后端重启掐断的(`payload.error_kind == "restart"`)。
 *
 * 没有 `undelivered` 的老回执照同样的规则走:后面有正常回答就算接住,没有就算没接住 ——
 * 不为旧数据写特例分支。
 */
import { describe, expect, it } from "vitest";

import { caughtReceiptsByMessage, receiptWasCaught } from "./ChatBubble";

type MessageLike = { id: string; role: string; payload?: unknown; error?: string | null };

const receipt = (id: string, payload: Record<string, unknown> = {}): MessageLike => ({
  id,
  role: "job_receipt",
  payload: { job_id: "j1", status: "failed", kind: "tts", subject: "配音 1", ...payload },
  error: null,
});
const assistant = (id: string, payload: Record<string, unknown> = {}): MessageLike => ({
  id,
  role: "assistant",
  payload: { usage: {}, ...payload },
  error: null,
});
const restarted = (id: string): MessageLike => ({
  id,
  role: "assistant",
  payload: { error_kind: "restart" },
  error: "backend restarted mid-turn",
});
const user = (id: string): MessageLike => ({ id, role: "user", payload: {}, error: null });

describe("回执被智能体接住了吗", () => {
  it("后面有一条正常助手消息 → 接住了", () => {
    const messages = [user("u1"), receipt("r1"), assistant("a1")];
    expect(receiptWasCaught(messages, 1)).toBe(true);
  });

  it("后面什么都没有 → 没接住", () => {
    expect(receiptWasCaught([user("u1"), receipt("r1")], 1)).toBe(false);
    // 只有用户在说话也算没有回答。
    expect(receiptWasCaught([receipt("r1"), user("u1")], 0)).toBe(false);
  });

  it("后面只有被重启掐断的那一轮 → 没接住;再往后有正常回答 → 接住了", () => {
    expect(receiptWasCaught([receipt("r1"), restarted("a1")], 0)).toBe(false);
    expect(receiptWasCaught([receipt("r1"), restarted("a1"), assistant("a2")], 0)).toBe(true);
  });

  it("还没交给智能体的(undelivered)→ 没接住,哪怕后面碰巧有别的回答", () => {
    const messages = [receipt("r1", { undelivered: true, deliver_as: "me" }), assistant("a1")];
    expect(receiptWasCaught(messages, 0)).toBe(false);
  });

  it("同一批回执由同一条回答接住,都归到那条消息的步骤里", () => {
    const messages = [receipt("r1"), receipt("r2", { job_id: "j2" }), assistant("a1")];
    const byMessage = caughtReceiptsByMessage(messages);
    expect([...byMessage.keys()]).toEqual(["a1"]);
    expect(byMessage.get("a1")?.map((one) => one.id)).toEqual(["r1", "r2"]);
  });

  it("没接住的回执不进归属表 —— 它们要显式出现", () => {
    const undelivered = caughtReceiptsByMessage([
      receipt("r1", { undelivered: true }),
      receipt("r2"),
      restarted("a1"),
    ]);
    expect(undelivered.size).toBe(0);
  });

  it("不是回执的消息不被当成回执", () => {
    expect(receiptWasCaught([assistant("a1"), assistant("a2")], 0)).toBe(false);
  });
});
