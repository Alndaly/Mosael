/** @vitest-environment jsdom */
/**
 * 「N 轮失败」的口径(维护者 2026-10-18 拍板 #6):
 *
 * 此前是本会话**累计**——不连续、不清零,后端重启留下的中断说明也算一条失败。重启不是失败,
 * 它是一轮没跑完;把它算进失败数,用户看到的是「3 轮失败」,而那三轮里可能有两轮只是应用更新。
 *
 * 现在:从最后一条消息往前数**连续**带失败的助手轮,遇到成功轮就停;重启中断的轮次跳过(不算失败,
 * 也不打断连续计数),单独统计。没有 `error_kind` 标记的旧消息一律按真实失败算 —— 不为旧数据写分支。
 */
import { describe, expect, it } from "vitest";

import { tallyTurnFailures } from "./ChatWorkspace";

type FailureLike = { role: string; error?: string | null; payload?: unknown };

const assistant = (error: string | null, payload: Record<string, unknown> = {}): FailureLike => ({
  role: "assistant",
  error,
  payload,
});
const user = (): FailureLike => ({ role: "user", error: null, payload: {} });
const failure = () => assistant("Connection error.");
const success = () => assistant(null);
const restarted = () => assistant("backend restarted mid-turn", { error_kind: "restart" });

describe("连续失败 / 重启中断的统计口径", () => {
  it("三历史失败后有一轮成功:连续失败归零", () => {
    const messages = [user(), failure(), user(), failure(), user(), failure(), user(), success()];
    expect(tallyTurnFailures(messages)).toEqual({ consecutiveFailures: 0, restartInterruptions: 0 });
  });

  it("从那轮成功之后又连续失败两次:连续失败是 2,不是历史上的 5", () => {
    const messages = [
      user(), failure(), user(), failure(), user(), failure(), user(), success(),
      user(), failure(), user(), failure(),
    ];
    expect(tallyTurnFailures(messages)).toEqual({ consecutiveFailures: 2, restartInterruptions: 0 });
  });

  it("重启中断单独计数,不从连续失败里扣,也不打断连续失败", () => {
    const messages = [
      user(), failure(), user(), failure(),
      user(), restarted(), user(), restarted(),
    ];
    expect(tallyTurnFailures(messages)).toEqual({ consecutiveFailures: 2, restartInterruptions: 2 });
  });

  it("旧消息没有 error_kind 标记:按真实失败算,不给旧数据写分支", () => {
    const messages = [user(), assistant("boom", { usage: {} }), user(), success()];
    expect(tallyTurnFailures(messages)).toEqual({ consecutiveFailures: 0, restartInterruptions: 0 });
    expect(tallyTurnFailures([user(), assistant("boom", { usage: {} })])).toEqual({
      consecutiveFailures: 1,
      restartInterruptions: 0,
    });
  });

  it("只数助手轮:用户消息和回执不参与", () => {
    const messages = [
      { role: "user", error: "queued thing", payload: {} },
      failure(),
      { role: "job_receipt", error: "receipt failed", payload: {} },
    ];
    expect(tallyTurnFailures(messages)).toEqual({ consecutiveFailures: 1, restartInterruptions: 0 });
  });
});
