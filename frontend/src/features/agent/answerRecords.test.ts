/**
 * 一次选择在对话里**只画一遍**,而"多余"这件事要查证,不能猜。
 *
 * 用户报的:答完选择卡之后,同一个选择紧挨着出现两次 —— 上面一张独立的回执卡,下面
 * `ask_user` 那一行展开还是它。
 *
 * 藏错方向的代价不对称:多画一遍只是啰嗦,**藏掉唯一那份**是答案彻底看不见。而"唯一那份"
 * 的情形是真实存在的(等待有上限 590s、直连 MCP 客户端不阻塞、后端重启会掐掉那一轮),
 * 那时工具结果是 `pending`。所以判据是 `question_id` 对得上,不是"有没有一条 ask_user"。
 */
import { describe, expect, it } from "vitest";

import {
  isRedundantAnswerRecord,
  questionsRecordedByTools,
  recordedQuestionIds,
} from "@/features/agent/answerRecords";

const askUser = (result: unknown) =>
  ({ type: "tool", tool: { id: "t1", name: "ask_user", status: "done", result } }) as never;

const record = (questionId?: string) => ({
  payload: { answers: { question_id: questionId, picked: [{ question: "宏大?", choices: ["远古巨柱神殿"] }] } },
});

describe("工具结果记下了哪些问题", () => {
  it("answered 算记下了", () => {
    const ids = questionsRecordedByTools([askUser({ status: "answered", answers: {}, question_id: "q1" })]);
    expect([...ids]).toEqual(["q1"]);
  });

  it("跳过也算 —— 结果卡上写的是「你跳过了这几个问题」", () => {
    const ids = questionsRecordedByTools([askUser({ status: "dismissed", skipped: true, question_id: "q1" })]);
    expect([...ids]).toEqual(["q1"]);
  });

  it("**pending 不算** —— 工具没等到,那时回执是唯一的记录", () => {
    const ids = questionsRecordedByTools([askUser({ status: "pending", question_id: "q1" })]);
    expect([...ids]).toEqual([]);
  });

  it("没有 question_id 就不认 —— 没有钥匙时宁可多画一遍", () => {
    const ids = questionsRecordedByTools([askUser({ status: "answered", answers: {} })]);
    expect([...ids]).toEqual([]);
  });

  it("别的工具不算", () => {
    const other = { type: "tool", tool: { id: "t2", name: "get_scene", status: "done", result: { status: "answered", question_id: "q1" } } } as never;
    expect([...questionsRecordedByTools([other])]).toEqual([]);
  });

  it("空时间线不炸", () => {
    expect([...questionsRecordedByTools(undefined)]).toEqual([]);
  });
});

describe("这条回执是不是多余的", () => {
  it("工具已经记下同一个 question_id → 多余,不画", () => {
    const messages = [{ payload: { timeline: [askUser({ status: "answered", answers: {}, question_id: "q1" })] } }];
    expect(isRedundantAnswerRecord(record("q1"), recordedQuestionIds(messages))).toBe(true);
  });

  it("工具停在 pending → **必须画**,否则答案彻底看不见", () => {
    const messages = [{ payload: { timeline: [askUser({ status: "pending", question_id: "q1" })] } }];
    expect(isRedundantAnswerRecord(record("q1"), recordedQuestionIds(messages))).toBe(false);
  });

  it("记的是别的问题 → 照画", () => {
    const messages = [{ payload: { timeline: [askUser({ status: "answered", answers: {}, question_id: "q2" })] } }];
    expect(isRedundantAnswerRecord(record("q1"), recordedQuestionIds(messages))).toBe(false);
  });

  it("老消息没有 question_id → 照画(不拿猜的去藏)", () => {
    const messages = [{ payload: { timeline: [askUser({ status: "answered", answers: {}, question_id: "q1" })] } }];
    expect(isRedundantAnswerRecord(record(undefined), recordedQuestionIds(messages))).toBe(false);
  });

  it("普通消息不受影响", () => {
    expect(isRedundantAnswerRecord({ payload: { body_document: {} } }, new Set(["q1"]))).toBe(false);
    expect(isRedundantAnswerRecord({}, new Set(["q1"]))).toBe(false);
  });
});

describe("两个聊天面板用的是同一条规矩", () => {
  it("两边都 import 了这个模块 —— 各写一遍的话,它迟早在其中一个上失效", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = join(import.meta.dirname, "..", "..");
    for (const panel of ["features/ai-studio/ChatWorkspace.tsx", "features/agent/CanvasAgentChat.tsx"]) {
      expect(readFileSync(join(src, panel), "utf8")).toContain("isRedundantAnswerRecord");
    }
  });
});
