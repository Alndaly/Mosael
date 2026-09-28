/** @vitest-environment jsdom */
/**
 * ⌘K 面板里的三件事:
 * - 「新建项目」真的建一个(和顶栏项目切换器同一个动作),不是跳回首页让人再点一次;
 * - 「切换主题」和顶栏按钮走同一个循环(浅 → 深 → 跟随系统),不在深浅之间两态互切;
 * - 默认高亮按实际渲染顺序取第一项 —— 只搜到工作流时 Enter 也得有目标。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeAll, beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ theme: "dark", setTheme: vi.fn() }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", theme: h.theme, setTheme: h.setTheme }),
}));
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => false }));
vi.mock("@/api/client", () => ({
  api: async () => [],
  listWorkflows: async () => [{ id: "wf1", name: "zzqx 周报", description: "", graph: { nodes: [] } }],
  listPublishTasks: async () => [],
}));

import { CommandPalette } from "@/components/layout/CommandPalette";

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
});
beforeEach(() => {
  h.theme = "dark";
  h.setTheme.mockReset();
});

function mount() {
  const onNavigate = vi.fn();
  const onCreateProject = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CommandPalette
        workspace={{ id: "w1", name: "W" } as never}
        projects={[]}
        onNavigate={onNavigate}
        onOpenProject={vi.fn()}
        onCreateProject={onCreateProject}
      />
    </QueryClientProvider>,
  );
  act(() => void window.dispatchEvent(new CustomEvent("mosael:open-cmdk")));
  return { onNavigate, onCreateProject };
}

it("新建项目直接建,不跳首页", async () => {
  const { onNavigate, onCreateProject } = mount();
  fireEvent.click(await screen.findByRole("option", { name: /createProject/ }));
  expect(onCreateProject).toHaveBeenCalledTimes(1);
  expect(onNavigate).not.toHaveBeenCalled();
});

it("切换主题和顶栏同一个循环:深色的下一档是跟随系统", async () => {
  mount();
  const toggle = await screen.findByRole("option", { name: /cmdkToggleTheme/ });
  expect(toggle).toHaveTextContent("themeSystem");
  fireEvent.click(toggle);
  expect(h.setTheme).toHaveBeenCalledWith("system");
});

it("只搜到工作流时,默认高亮落在它身上", async () => {
  mount();
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "zzqx" } });
  const workflow = await screen.findByRole("option", { name: /zzqx 周报/ });
  await waitFor(() => expect(workflow).toHaveAttribute("aria-selected", "true"));
});
