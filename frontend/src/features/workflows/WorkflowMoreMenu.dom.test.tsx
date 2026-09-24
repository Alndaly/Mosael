/** @vitest-environment jsdom */
/**
 * 工作流详情页工具栏最右那颗 ⋯。
 *
 * 用户报过:「版本历史 · v29」「导出为文件」「删除」三行里,删除被单独框成一个带描边的盒子,
 * 行高和另外两行也不一样,整个菜单看不出分组。这里钉住条目、顺序、分组和破坏性样式。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeAll, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  fetchWorkflowNodeTypes: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));

vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { Workspace } from "@/api/client";
import { MENU_ITEM_DESTRUCTIVE } from "@/components/ui/floating";
import { WorkflowsView } from "@/features/workflows/WorkflowsView";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", () => new Promise(() => undefined));
});

const workflow = {
  id: "workflow-1",
  workspace_id: "w1",
  name: "测试工作流",
  description: "",
  revision: 29,
  graph: { nodes: [], edges: [] },
  created_at: "2026-09-20T00:00:00",
  updated_at: "2026-09-20T00:00:00",
};

it("⋯ 里是 重命名 / 版本历史 v29 / 导出为文件,删除单独一组、红字、没有描边", async () => {
  localStorage.setItem("mosael:selected:workflows", workflow.id);
  apiMocks.listWorkflows.mockResolvedValue([workflow]);
  apiMocks.fetchWorkflowNodeTypes.mockResolvedValue([]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><WorkflowsView workspace={{ id: "w1", name: "w" } as Workspace} /></QueryClientProvider>);

  const toolbar = await screen.findByRole("group", { name: "canvasTools" }, { timeout: 10000 });
  fireEvent.click(within(toolbar).getByRole("button", { name: "more" }));
  const menu = screen.getByRole("menu", { name: "more" });

  const rows = [...menu.children].map((el) => (el.getAttribute("role") === "separator" ? "|" : el.textContent));
  expect(rows).toEqual(["rename", "wfRevisionHistoryv29", "wfExport", "|", "delete"]);
  // 版本号是附注,不拼进名字里。
  expect(within(menu).getByText("v29").className).toContain("text-muted-foreground");

  const del = within(menu).getByRole("menuitem", { name: "delete" });
  expect(del.className).toContain(MENU_ITEM_DESTRUCTIVE);
  expect(del.className).not.toMatch(/border-t|border-divider|rounded-t-none/);
  // 所有条目同一行高。
  for (const item of within(menu).getAllByRole("menuitem")) expect(item.className).toContain("min-h-9");

  fireEvent.click(within(menu).getByRole("menuitem", { name: "rename" }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
}, 20000);
