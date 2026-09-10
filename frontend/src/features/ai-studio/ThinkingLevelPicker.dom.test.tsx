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
      agentThinkingOn: "开启",
      agentThinkingLow: "低",
      agentThinkingMedium: "中",
      agentThinkingHigh: "高",
      agentThinkingUnavailable: "这条连接发不出思考档位",
      agentThinkingUnavailableHint: "去设置里打开 reasoning_effort",
    })[key] ?? key,
}));

let catalog: unknown[] = [];
const api = vi.fn(async () => catalog);
vi.mock("@/api/client", () => ({ api: () => api() }));

import { ThinkingLevelPicker } from "./ThinkingLevelPicker";

const session = { id: "s1", model: "kimi-k3", provider_profile_id: "p1", thinking_level: "off" };
const model = (extra: Record<string, unknown>) => ({
  model: "kimi-k3",
  provider_profile_id: "p1",
  provider_name: "Kimi",
  display_name: "k3",
  ...extra,
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <ThinkingLevelPicker session={session as any} />
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
    catalog = [model({ reasoning: true, reasoning_effort: null })];
    mount();
    expect(await screen.findByText("这条连接发不出思考档位")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();
    expect(screen.queryByText("关闭")).not.toBeInTheDocument();
  });

  it("打开了 reasoning_effort 才给真正的档位", async () => {
    catalog = [model({ reasoning: true, reasoning_effort: true })];
    mount();
    expect(await screen.findByRole("combobox")).toBeInTheDocument();
    expect(screen.queryByText("这条连接发不出思考档位")).not.toBeInTheDocument();
  });

  it("这个模型压根不思考 —— 控件整个不出现", async () => {
    catalog = [model({ reasoning: false })];
    const { container } = mount();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelector("[role=combobox]")).toBeNull();
  });

  it("目录还没到的时候什么都不渲染 —— 不闪一下「发不出去」", () => {
    catalog = [model({ reasoning: true, reasoning_effort: true })];
    const { container } = mount();
    // 首帧:查询还没落地。此前这里会渲染出禁用态,而这条连接其实是发得出的。
    expect(container.textContent).toBe("");
  });
});
