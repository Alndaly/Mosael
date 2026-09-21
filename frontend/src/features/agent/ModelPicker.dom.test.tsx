/** @vitest-environment jsdom */

/**
 * 模型选择器**永远占着它那一格**。
 *
 * 用户报的是「智能体怎么连模型选择的那个 select 框都没了」。查下来:此前只要「还在读」或
 * 「任何一条连接的模型列表出错」,整个控件就 `return null` —— 凭空消失,而且不说为什么。
 *
 * 两种后果都很坏:读取期间它闪没再闪回来,页面一慢就"不见了";而一条坏连接会把**其余所有
 * 连接**的模型一起带走 —— 一条挂掉的端点吃掉整个功能。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const listProviderModels = vi.fn();
const api = vi.fn();
vi.mock("@/api/client", () => ({
  api: (...args: unknown[]) => api(...(args as [])),
  listProviderModels: (...args: unknown[]) => listProviderModels(...(args as [])),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      agentModelPlaceholder: "选择模型",
      agentModelLabel: "模型",
      agentConfigureModel: "去配置模型",
      cmdkEmpty: "没有结果",
      agentModelSomeUnavailable: "有连接的模型列表没读出来",
    })[key] ?? key,
}));
vi.mock("@/features/agent/effectiveModel", () => ({
  useEffectiveChatModel: (session: { provider_profile_id?: string; model?: string } | null) => ({
    providerProfileId: session?.provider_profile_id ?? "",
    model: session?.model ?? "",
  }),
}));
vi.mock("@/lib/gotoSettings", () => ({ gotoSettings: vi.fn() }));

import { ModelPicker } from "@/features/agent/ModelPicker";

const SESSION = { id: "s1", provider_profile_id: "p1", model: "deepseek-v4-flash" } as never;

function mount(session: unknown = SESSION) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ModelPicker workspaceId="ws" session={session as never} />
    </QueryClientProvider>,
  );
}

describe("模型选择器", () => {
  it("还在读的时候不消失,而且先把会话上那个模型名显示出来", async () => {
    // 一直挂着的请求 = 读取中。此前这一刻整个控件是 null。
    api.mockImplementation(() => new Promise(() => {}));
    listProviderModels.mockImplementation(() => new Promise(() => {}));
    mount();
    const holder = await screen.findByRole("status");
    expect(holder.textContent).toContain("deepseek-v4-flash");
  });

  it("会话还没读到也不消失", async () => {
    api.mockImplementation(() => new Promise(() => {}));
    listProviderModels.mockImplementation(() => new Promise(() => {}));
    mount(null);
    expect((await screen.findByRole("status")).textContent).toContain("选择模型");
  });

  it("一条连接读失败,别的连接的模型照样能选", async () => {
    api.mockImplementation((path: string) =>
      path.includes("provider-defaults")
        ? Promise.resolve([])
        : Promise.resolve([
            { id: "p1", name: "好的那条", enabled: true },
            { id: "p2", name: "坏的那条", enabled: true },
          ]),
    );
    listProviderModels.mockImplementation((id: string) =>
      id === "p1" ? Promise.resolve([{ id: "deepseek-v4-flash" }]) : Promise.reject(new Error("端点挂了")),
    );
    mount();
    // 此前:p2 一失败,整个控件 return null —— p1 下面的模型也一起没了。
    const trigger = await screen.findByRole("button", { name: "模型" });
    expect(trigger.textContent).toContain("deepseek-v4-flash");
    //: 少了东西要说一声,不能一声不吭。
    expect(trigger.getAttribute("title")).toBe("有连接的模型列表没读出来");
  });
});
