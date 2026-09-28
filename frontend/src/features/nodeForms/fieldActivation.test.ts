import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/workflow-field-activation.json";

import { isTakenByOneOfPeer, isWorkflowFieldActive, oneOfGroups } from "@/features/nodeForms/fieldActivation";

describe("isWorkflowFieldActive", () => {
  const specs = {
    engine: { default: "google" },
    profile_id: { active_when: { engine: "ai" } },
  };

  it("无条件字段始终参与", () => {
    expect(isWorkflowFieldActive(specs.engine, {}, specs)).toBe(true);
  });

  it("按当前配置决定字段是否参与", () => {
    expect(isWorkflowFieldActive(specs.profile_id, { engine: "google" }, specs)).toBe(false);
    expect(isWorkflowFieldActive(specs.profile_id, { engine: "ai" }, specs)).toBe(true);
  });

  it("父字段未保存时读取声明默认值", () => {
    expect(isWorkflowFieldActive(specs.profile_id, {}, specs)).toBe(false);
  });

  it("支持一个条件允许多个取值", () => {
    const spec = { active_when: { engine: ["ai", "local"] } };
    expect(isWorkflowFieldActive(spec, { engine: "local" }, specs)).toBe(true);
  });

  it.each(contract.cases)("与后端共享契约：$name", ({ spec, config, specs, active }) => {
    expect(isWorkflowFieldActive(spec, config, specs)).toBe(active);
  });
});

describe("one_of:同组恰好填一个", () => {
  const specs = {
    session: {},
    asset_id: { one_of: "source" },
    file_path: { one_of: "source" },
  };

  it("按组名归拢,顺序是声明的顺序", () => {
    expect(oneOfGroups(specs)).toEqual([["asset_id", "file_path"]]);
  });

  it("一格填了,同组其余的收起来;都空时都在", () => {
    expect(isTakenByOneOfPeer("file_path", specs, { asset_id: "a1" })).toBe(true);
    expect(isTakenByOneOfPeer("asset_id", specs, { asset_id: "a1" })).toBe(false);
    expect(isTakenByOneOfPeer("asset_id", specs, {})).toBe(false);
    expect(isTakenByOneOfPeer("file_path", specs, { asset_id: "  " })).toBe(false);
    expect(isTakenByOneOfPeer("session", specs, { asset_id: "a1" })).toBe(false);
  });

  it("接了上游也算填了", () => {
    expect(isTakenByOneOfPeer("file_path", specs, {}, (key) => key === "asset_id")).toBe(true);
  });

  it("两格都已经填了就都留着 —— 藏起来就既看不见也清不掉", () => {
    const both = { asset_id: "a1", file_path: "/tmp/x.mp4" };
    expect(isTakenByOneOfPeer("asset_id", specs, both)).toBe(false);
    expect(isTakenByOneOfPeer("file_path", specs, both)).toBe(false);
  });
});
