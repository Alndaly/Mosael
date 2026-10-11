import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { invalidatePluginDependents, PLUGIN_PACKAGES_KEY, patchPluginInstance } from "./pluginCaches";

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


/**
 * 连接上的改动**当场**写进插件目录那份缓存(`["plugins"]`)—— 维护者:「ComfyUI 插件这里,对连接的启用 / 停用
 * 不是乐观更新,导致点击会有很久的卡顿」。那份缓存的失效重问要走一趟插件(能力、状态、目录):等它回来才动开关,
 * 就是「点了很久才反应」。开关先动、请求在后台走,失败用这里交回的快照回滚(见 PluginsView 里那个 mutation)。
 */
describe("连接改动的乐观写入", () => {
  const instance = (id: string, enabled: boolean) => ({ id, name: id, enabled, blocked_reason: "" }) as never;
  const pkg = (id: string, instances: unknown[]) => ({ id, name: id, instances }) as never;
  const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

  it("当场把那一格改成新值,交回改动前的数据(失败回滚用)", () => {
    const qc = client();
    const before = [pkg("dev.mosael.comfyui", [instance("a", false)])];
    qc.setQueryData(PLUGIN_PACKAGES_KEY, before);

    const snapshot = patchPluginInstance(qc, "a", { enabled: true });

    const after = qc.getQueryData(PLUGIN_PACKAGES_KEY) as { instances: { enabled: boolean }[] }[];
    expect(after[0].instances[0].enabled, "开关先动").toBe(true);
    expect(snapshot, "交回的是改动前那一份").toBe(before);
    expect((before[0] as { instances: { enabled: boolean }[] }).instances[0].enabled, "原对象不动").toBe(false);
  });

  it("只碰那一个连接:别的连接、别的包原样", () => {
    const qc = client();
    qc.setQueryData(PLUGIN_PACKAGES_KEY, [
      pkg("dev.mosael.comfyui", [instance("a", false), instance("b", true)]),
      pkg("dev.mosael.other", [instance("c", false)]),
    ]);

    patchPluginInstance(qc, "a", { enabled: true });

    const after = qc.getQueryData(PLUGIN_PACKAGES_KEY) as { id: string; instances: { id: string; enabled: boolean }[] }[];
    expect(after[0].instances.map((one) => [one.id, one.enabled])).toEqual([["a", true], ["b", true]]);
    expect(after[1].instances.map((one) => [one.id, one.enabled])).toEqual([["c", false]]);
  });

  it("缓存里还没有这一份(或者没有这个连接):什么都不动,也不报错", () => {
    const qc = client();
    expect(patchPluginInstance(qc, "a", { enabled: true }), "没有缓存就没有快照").toBeUndefined();

    const before = [pkg("dev.mosael.comfyui", [instance("b", false)])];
    qc.setQueryData(PLUGIN_PACKAGES_KEY, before);
    patchPluginInstance(qc, "a", { enabled: true });
    expect(qc.getQueryData(PLUGIN_PACKAGES_KEY)).toBe(before);
  });
});
