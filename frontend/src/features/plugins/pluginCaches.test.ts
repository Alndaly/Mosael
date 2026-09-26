import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { invalidatePluginDependents } from "./pluginCaches";

describe("插件连接变了,跟着它走的缓存一起失效", () => {
  it("AI 工作台的模型选择器、画板工具格、节点表单都不停在旧的那一份", () => {
    // 此前插件页只失效自己那几份:启用 ComfyUI、点「刷新模型」之后回到 AI 工作台,选择器里
    // 还是旧模型,要等一分钟(默认 staleTime)或刷新整页 —— 用户以为刷新没成功。
    const qc = new QueryClient();
    const dependents = [
      ["generation-options", "image"],
      ["provider-profiles"],
      ["provider-defaults"],
      ["provider-models", "profile-1"],
      ["capability-models", "image"],
      ["board-producers", "ws-1"],
      ["workflow-node-types"],
      ["workflow-field-options", "plugin_instances", "ws-1", "", "plugin.dev.x.go", "", "instance_id"],
      ["plugins"],
      ["plugin-models", "i-1"],
    ];
    for (const key of dependents) qc.setQueryData(key, []);
    qc.setQueryData(["assets", "ws-1"], []);

    invalidatePluginDependents(qc);

    for (const key of dependents) expect(qc.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    expect(qc.getQueryState(["assets", "ws-1"])?.isInvalidated).toBe(false);
  });
});
