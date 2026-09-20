/** 工具结果里哪些 id 该渲染成媒体预览。 */
import { describe, expect, it } from "vitest";

import { collectAssetIds } from "@/features/agent/ToolCalls";

describe("媒体预览的素材来源", () => {
  it("产出型结果里的 asset_id 要收", () => {
    expect([...collectAssetIds({ asset_id: "a1" })]).toEqual(["a1"]);
    expect([...collectAssetIds({ asset_ids: [], results: [{ asset_id: "a2" }] })]).toEqual(["a2"]);
  });

  it("复数的 asset_ids 是一串 id,也要收", () => {
    // 生成任务把产物放在 result.asset_ids(domain/generation/runner);只收字符串值的话,
    // 刚生成出来的那几张图一张都不显示 —— 而那正是这块预览存在的理由。
    expect([...collectAssetIds({ asset_ids: ["a1", "a2"] })]).toEqual(["a1", "a2"]);
    expect([...collectAssetIds({ result: { asset_ids: ["a3"] }, asset_id: "a4" })]).toEqual(["a3", "a4"]);
  });

  it("工作流图里的不收 —— 那是计划,不是这次碰过的媒体", () => {
    const workflow = {
      name: "主题自动成片",
      graph: { nodes: [{ id: "n1", config: { asset_id: "还没产出来的" } }] },
    };
    expect([...collectAssetIds(workflow)]).toEqual([]);
  });

  it("图之外的仍然收 —— 同一个结果里两者可以并存", () => {
    expect([...collectAssetIds({ asset_id: "真的", graph: { nodes: [{ config: { asset_id: "计划" } }] } })]).toEqual([
      "真的",
    ]);
  });

  it("bare id 一直都不收(工作流/项目/确认卡的 id 会白发一次请求)", () => {
    expect([...collectAssetIds({ id: "w1", workflow_id: "w2" })]).toEqual([]);
  });
});
