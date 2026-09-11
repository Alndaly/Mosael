/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      agentThinkingLevel: "思考",
      agentThinkingOff: "关闭",
      agentThinkingModelDefault: "模型默认",
      agentThinkingOn: "开启",
      agentThinkingLow: "低",
      agentThinkingMedium: "中",
      agentThinkingHigh: "高",
      agentThinkingUnavailable: "这条连接发不出思考档位",
      agentThinkingUnavailableHint: "去设置里打开 reasoning_effort",
      modelListLoading: "读取模型…",
    })[key] ?? key,
}));

let catalog: unknown[] = [];
//: 会话没写死模型时,档位要靠「设置 → AI 对话」的默认回退。两个端点得分开答。
let defaults: unknown[] = [{ capability: "chat", provider_profile_id: "p1", model: "kimi-k3" }];
const api = vi.fn(async (url: string) => (url.includes("provider-defaults") ? defaults : catalog));
vi.mock("@/api/client", () => ({ api: (url: string) => api(url) }));

import { ThinkingLevelPicker } from "./ThinkingLevelPicker";

const session = { id: "s1", model: "kimi-k3", provider_profile_id: "p1", thinking_level: "off" };
//: 库里几乎每条会话都长这样 —— 不写死模型,跟着默认走。
const inheriting = { id: "s2", model: null, provider_profile_id: null, thinking_level: "off" };
const model = (extra: Record<string, unknown>) => ({
  model: "kimi-k3",
  provider_profile_id: "p1",
  provider_name: "Kimi",
  display_name: "k3",
  ...extra,
});

function mount(which: unknown = session) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <ThinkingLevelPicker session={which as any} />
    </QueryClientProvider>,
  );
}

afterEach(cleanup);

describe("思考档位", () => {
  /**
   * 用户报的:选了「关闭」,Kimi k3 照样在思考。
   *
   * 原因在链路末端 —— 我们给 pi 造的是合成模型,不带 thinkingFormat,所以按供应商匹配的思考
   * 分支一条都不命中,全落到通用的 reasoning_effort 上;而那两条都要求
   * compat.supportsReasoningEffort,它来自模型行上的 reasoning_effort,默认是空。
   * 于是四个档位发出去的请求逐字节相同。
   */
  it("发不出档位时,不摆四个做同一件事的选项", async () => {
    catalog = [model({ reasoning: true, thinking_levels: [] })];
    mount();
    expect(await screen.findByText("这条连接发不出思考档位")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.queryByText("关闭")).not.toBeInTheDocument();
  });

  it("后端说得出档位才给下拉", async () => {
    catalog = [model({ reasoning: true, thinking_levels: ["off", "low", "medium", "high"] })];
    mount();
    expect(await screen.findByRole("combobox")).toBeInTheDocument();
    expect(screen.queryByText("这条连接发不出思考档位")).not.toBeInTheDocument();
  });

  it("这个模型压根不思考 —— 也是空清单,同一条路", async () => {
    catalog = [model({ reasoning: false, thinking_levels: [] })];
    const { container } = mount();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(container.querySelector("[role=combobox]")).toBeNull();
  });

  it("发不出去时占住这一格 —— 标题是外面画的,返回 null 会留下一个空标题", async () => {
    // 用户截图里就是这个:「思考」和「视频分析方式」之间一片空。
    catalog = [model({ reasoning: true, thinking_levels: [] })];
    const { container } = mount();
    await screen.findByText("这条连接发不出思考档位");
    const placeholder = container.querySelector("button")!;
    expect(placeholder).toBeDisabled();
    // 形状要和旁边两个下拉一致,不是一段浮着的灰字。
    expect(placeholder.className).toContain("bg-field");
    expect(placeholder.className).toContain("border");
  });

  it("关不掉的模型不给「关闭」—— Kimi k3 只有低和高", async () => {
    // 查证:k3 的 reasoning_effort 只收 low/high/max,没有关闭,也没有「中」。
    // 此前界面给它四档,其中「关闭」是空操作、「中」是个会被拒的值。
    catalog = [model({ reasoning: true, thinking_levels: ["low", "high"] })];
    mount();
    await screen.findByRole("combobox");
    expect(screen.queryByText("关闭")).not.toBeInTheDocument();
  });

  /**
   * 上一条只说了"不该有什么",而漏掉的一直是"那该有什么"。
   *
   * 会话的 thinking_level 建表默认是 off,而 k3 的清单里没有 off —— Select 拿着一个清单里
   * 不存在的值,Radix 找不到对应的 ItemText,**触发器整个是空的**。每个 k3 会话打开都这样,
   * 而它正是这个功能针对的那个模型。空白读起来是"坏了",不是"还没挑"。
   */
  it("k3 会话默认那一档:写的是「模型默认」,不是一片空白", async () => {
    catalog = [model({ reasoning: true, thinking_levels: ["low", "high"] })];
    mount();
    const trigger = await screen.findByRole("combobox");
    expect(trigger.textContent).not.toBe("");
    expect(trigger.textContent).toContain("模型默认");
  });

  it("能关的模型照旧说「关闭」", async () => {
    catalog = [model({ reasoning: true, thinking_levels: ["off", "low", "medium", "high"] })];
    mount();
    const trigger = await screen.findByRole("combobox");
    expect(trigger.textContent).toContain("关闭");
    expect(trigger.textContent).not.toContain("模型默认");
  });

  it("目录还没到时说「读取中」,不说「发不出去」", () => {
    catalog = [model({ reasoning: true, thinking_levels: ["off", "low"] })];
    const { container } = mount();
    // 首帧:查询还没落地。"还不知道"不能长成一个结论 —— 而这条连接其实是发得出的。
    expect(container.textContent).toContain("读取模型…");
    expect(container.textContent).not.toContain("发不出思考档位");
  });

  /**
   * **会话不写死模型才是常态。**
   *
   * 新建会话的 `model` / `provider_profile_id` 都是 NULL,跟着「设置 → AI 对话」的默认走
   * (线上库里翻出来的每一条都是这样)。而这个组件原先直接拿 `session.model` 去目录里找 ——
   * 空值匹配不上任何一行,于是**每一个没手动指定模型的会话**都被判成「这条连接发不出思考
   * 档位」,哪怕那个模型明明支持。开关等于没有,而且不报错。
   *
   * 浏览器里实测发现:用户的 Kimi k3 会话正是如此。ModelPicker 一直做了这个回退,所以底部
   * 显示的模型是对的 —— 两处各算各的,才让这个洞藏了下来。
   */
  it("会话没写死模型时,按默认模型取档位,而不是判成发不出去", async () => {
    catalog = [model({ reasoning: true, thinking_levels: ["low", "high"] })];
    mount(inheriting);
    const trigger = await screen.findByRole("combobox");
    expect(trigger.textContent).toContain("模型默认");
    expect(screen.queryByText("这条连接发不出思考档位")).not.toBeInTheDocument();
  });

  it("默认模型还没到时说「读取中」,不说「发不出去」", () => {
    catalog = [model({ reasoning: true, thinking_levels: ["low", "high"] })];
    const { container } = mount(inheriting);
    expect(container.textContent).toContain("读取模型…");
    expect(container.textContent).not.toContain("发不出思考档位");
  });
});
