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
      ["workflow-node-unusable", "plugin.dev.x.go"],
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

  it("存着 (连接, 模型) 或工具名的会话、记录、画板、工作流、定时任务也失效 —— 目录重拉、工作流库里改名会当场改写它们", () => {
    // ADR 0045 修订之二:在工作流库里升级旧格式表单、改名挪目录,后端在同一个请求(或紧跟着的那次目录重拉)里把引用改到
    // 新名字。此前只失效选项:关掉工作流库回到会话,会话还指着改名前的那个(升级完的会话照旧显示完整工作流的参数),
    // 画板格子说「用不了」,要等一分钟的 staleTime。
    const qc = new QueryClient();
    const holders = [
      ["generation-sessions", "ws-1", "image"],
      ["generation-jobs", "ws-1", "s-1"],
      ["boards", "ws-1", "detail", "b-1"],
      ["boards", "ws-1"],
      ["workflows", "ws-1"],
      ["scheduled-tasks", "ws-1"],
    ];
    for (const key of holders) qc.setQueryData(key, []);

    invalidatePluginDependents(qc);

    for (const key of holders) expect(qc.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
  });
});
