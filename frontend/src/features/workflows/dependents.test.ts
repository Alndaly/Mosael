import { describe, expect, it } from "vitest";

import { withDependentsCleared } from "@/features/workflows/dependents";

/** llm 节点的真实形状:模型跟着供应商配置走。 */
const LLM = { profile_id: {}, model: { depends_on: "profile_id" } };

describe("withDependentsCleared", () => {
  it("换供应商配置时清掉旧模型", () => {
    const before = { profile_id: "kimi", model: "kimi-for-coding" };
    expect(withDependentsCleared(before, "profile_id", "ollama", LLM)).toEqual({
      profile_id: "ollama",
      model: "",
    });
  });

  it("值没变就不动模型", () => {
    // 组件重渲染回填、或者用户重新选中同一项时,不该把填好的模型清掉。
    const before = { profile_id: "kimi", model: "kimi-for-coding" };
    expect(withDependentsCleared(before, "profile_id", "kimi", LLM)).toEqual(before);
  });

  it("改的是别的字段时不牵连模型", () => {
    const before = { profile_id: "kimi", model: "kimi-for-coding", temperature: "0.2" };
    const after = withDependentsCleared(before, "temperature", "0.9", LLM);
    expect(after.model).toBe("kimi-for-coding");
  });

  it("模型本来就是空的时候不写出一次无谓的改动", () => {
    const before = { profile_id: "kimi" };
    expect(withDependentsCleared(before, "profile_id", "ollama", LLM)).toEqual({ profile_id: "ollama" });
  });

  it("一个父字段能带下多个子字段", () => {
    // plugin_tool:工具名和实例都跟着插件走。
    const specs = {
      plugin_id: {},
      tool_name: { depends_on: "plugin_id" },
      instance_id: { depends_on: "plugin_id" },
    };
    const before = { plugin_id: "a", tool_name: "search", instance_id: "i-1" };
    expect(withDependentsCleared(before, "plugin_id", "b", specs)).toEqual({
      plugin_id: "b",
      tool_name: "",
      instance_id: "",
    });
  });

  it("没有依赖声明时就是普通赋值", () => {
    const before = { a: "1", b: "2" };
    expect(withDependentsCleared(before, "a", "9", { a: {}, b: {} })).toEqual({ a: "9", b: "2" });
  });
});
