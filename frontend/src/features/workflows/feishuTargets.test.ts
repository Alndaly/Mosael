/**
 * 画布上要现查「收件人」目录的那几档:**只有这一张图真的用得上哪一档才去问**。
 *
 * 群那一档在后端是**现问飞书**(`_feishu_chats`,每台机器人一次 REST),而 `to` 是一段 `{{…}}` 引用或
 * 空着的时候卡上写的是「发起人」,问了也用不上 —— 所以判据写在这里,由它说了算。
 */
import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { feishuTargetParents } from "@/features/workflows/feishuTargets";

function graph(nodes: Array<[string, Record<string, unknown>]>): WorkflowGraph {
  return {
    nodes: nodes.map(([type, config], index) => ({ id: `n${index}`, type, name: "", config, position: { x: 0, y: 0 } })),
    edges: [],
  } as WorkflowGraph;
}

describe("收件人目录要问哪几档", () => {
  it("私聊 / 发群各问各的", () => {
    expect(feishuTargetParents(graph([["await_approval", { channel: "user", to: "ou_x" }]]))).toEqual({ user: true, chat: false });
    expect(feishuTargetParents(graph([["feishu_message", { channel: "chat", to: "oc_x" }]]))).toEqual({ user: false, chat: true });
  });

  it("别的档、别的节点不问", () => {
    expect(feishuTargetParents(graph([["await_approval", { channel: "origin" }]]))).toEqual({ user: false, chat: false });
    expect(feishuTargetParents(graph([["await_approval", { channel: "raw", raw_id: "ou_x" }]]))).toEqual({ user: false, chat: false });
    expect(feishuTargetParents(graph([["llm", { channel: "user", to: "ou_x" }]]))).toEqual({ user: false, chat: false });
  });

  it("没有值可查的不问:`to` 空着或是一段引用时卡上写的是「发起人」", () => {
    expect(feishuTargetParents(graph([["await_approval", { channel: "user", to: "" }]]))).toEqual({ user: false, chat: false });
    expect(feishuTargetParents(graph([["await_approval", { channel: "user", to: "{{开始.负责人}}" }]]))).toEqual({ user: false, chat: false });
  });
});
