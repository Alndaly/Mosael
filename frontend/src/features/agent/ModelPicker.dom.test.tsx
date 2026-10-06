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
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const listCapabilityModels = vi.fn();
const listProviderModels = vi.fn();
const api = vi.fn();
const sessions = vi.hoisted(() => ({
  listAgentSessions: vi.fn(),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  api: (...args: unknown[]) => api(...(args as [])),
  //: 连接清单与能力默认按路径答(测试里的 api 替身按路径分),模型行单独桩。
  listProviderProfiles: () => api("/api/settings/providers"),
  listProviderDefaults: () => api("/api/settings/provider-defaults"),
  listCapabilityModels: (...args: unknown[]) => listCapabilityModels(...(args as [])),
  //: 设置页用的整份目录。选择器**不该**读它(见下面「只列对话模型」那一条)。
  listProviderModels: (...args: unknown[]) => listProviderModels(...(args as [])),
  ...sessions,
}));
//: 下拉本身(Popover + cmdk)不是这里要验的;每个选项摊成一个按钮,只验「选了之后写到哪」。
//: 触发器外面的悬停说明照真的那样套(真组件也是 Hint 包着触发器)。
vi.mock("@/components/ui/searchable-select", async () => {
  const { Hint } = await import("@/components/ui/tooltip");
  return {
  SearchableSelect: ({
    trigger,
    hint,
    options,
    onValueChange,
  }: {
    trigger: React.ReactNode;
    hint?: string | null;
    options: { value: string; label: string }[];
    onValueChange: (value: string) => void;
  }) => (
    <>
      <Hint label={hint}>{trigger}</Hint>
      {options.map((option) => (
        <button key={option.value} type="button" data-option={option.value} onClick={() => onValueChange(option.value)}>
          {option.label}
        </button>
      ))}
    </>
  ),
  };
});
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
import { readHint } from "@/test/hint";

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
    listCapabilityModels.mockImplementation(() => new Promise(() => {}));
    mount();
    const holder = await screen.findByRole("status");
    expect(holder.textContent).toContain("deepseek-v4-flash");
  });

  it("会话还没读到也不消失", async () => {
    api.mockImplementation(() => new Promise(() => {}));
    listCapabilityModels.mockImplementation(() => new Promise(() => {}));
    mount(null);
    expect((await screen.findByRole("status")).textContent).toContain("选择模型");
  });

  it("对话模型清单读不出来,会话上选着的那个照样在,而且说一声少了东西", async () => {
    api.mockImplementation((path: string) =>
      path.includes("provider-defaults")
        ? Promise.resolve([])
        : Promise.resolve([
            { id: "p1", name: "好的那条", enabled: true },
            { id: "p2", name: "另一条", enabled: true },
          ]),
    );
    listCapabilityModels.mockRejectedValue(new Error("端点挂了"));
    mount();
    // 此前:读失败整个控件 return null。
    const trigger = await screen.findByRole("button", { name: "模型" });
    expect(trigger.textContent).toContain("deepseek-v4-flash");
    //: 少了东西要说一声,不能一声不吭。
    expect(await readHint(trigger)).toBe("有连接的模型列表没读出来");
  });

  it("只列会对话、配置了的模型 —— 不是每条连接的整份目录", async () => {
    //: 付费实测:百炼一条连接的目录 277 行,生视频的 wan2.2-s2v、作曲的 fun-music、没配置的 kimi-k3 都摊在对话模型的下拉里。
    api.mockImplementation((path: string) =>
      path.includes("provider-defaults")
        ? Promise.resolve([{ capability: "chat", provider_profile_id: "p2", model: "qwen-plus" }])
        : Promise.resolve([
            { id: "p1", name: "Kimi", enabled: true },
            { id: "p2", name: "阿里云百炼", enabled: true },
            { id: "p3", name: "火山方舟", enabled: true },
          ]),
    );
    listCapabilityModels.mockResolvedValue([
      { provider_profile_id: "p1", provider_name: "Kimi", model: "k3" },
      { provider_profile_id: "p2", provider_name: "阿里云百炼", model: "qwen-plus" },
    ]);
    listProviderModels.mockResolvedValue([{ id: "wan2.2-s2v" }, { id: "fun-music-v1" }, { id: "kimi-k3" }]);
    mount({ id: "s1", provider_profile_id: "p1", model: "k3" });
    await screen.findByRole("button", { name: "模型" });
    const offered = [...document.querySelectorAll("[data-option]")].map((one) => one.textContent);
    expect(offered).toEqual(["Kimi · k3", "阿里云百炼 · qwen-plus"]);
    expect(listCapabilityModels).toHaveBeenCalledWith("chat");
    expect(listProviderModels).not.toHaveBeenCalled();
  });
});

describe("还没有会话时", () => {
  it("照样能选模型:先建出当前会话,再把模型写进去", async () => {
    api.mockImplementation((path: string) =>
      path.includes("provider-defaults")
        ? Promise.resolve([])
        : Promise.resolve([{ id: "p1", name: "连接", enabled: true }]),
    );
    listCapabilityModels.mockResolvedValue([
      { provider_profile_id: "p1", provider_name: "连接", model: "m-fast" },
      { provider_profile_id: "p1", provider_name: "连接", model: "m-deep" },
    ]);
    sessions.listAgentSessions.mockResolvedValue([]);
    sessions.createAgentSession.mockResolvedValue({ id: "s-new", workspace_id: "ws", title: "新对话" });
    sessions.updateAgentSession.mockResolvedValue({});
    mount(null);

    //: 此前这里是一个点不动的占位 —— 空工作区里第一条消息只能用默认模型发。
    fireEvent.click(await screen.findByRole("button", { name: "m-deep" }));
    await waitFor(() =>
      expect(sessions.updateAgentSession).toHaveBeenCalledWith("s-new", { provider_profile_id: "p1", model: "m-deep" }),
    );
    expect(sessions.createAgentSession).toHaveBeenCalledWith({ workspace_id: "ws" });
    //: 建出来的就是「当前会话」—— 面板、浮标接下来看到的都是它。
    expect(window.localStorage.getItem("mosael.agent.session.ws")).toBe("s-new");
  });
});
