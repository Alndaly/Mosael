import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/workflow-field-activation.json";

import { isWorkflowFieldActive } from "@/features/workflows/fieldActivation";

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
