/** @vitest-environment jsdom */
/**
 * 设置 → 团队与成员里的「重命名 / 删除工作区」和切换器用同一份门槛(workspaceMenuState)、
 * 同一份删除收尾(lib/workspaces 的 useDeleteWorkspace)。此前这里自己判权限、不查还剩几个、
 * 删完只让列表失效 —— 切换器灰掉的删除,在这里照样点得下去。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, expect, it, vi } from "vitest";

import type { Workspace } from "@/api/client";
import { workspaceKeys } from "@/api/queryKeys";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));
const h = vi.hoisted(() => ({
  role: "owner",
  server: [] as Array<{ id: string; name: string; role: string }>,
  deleteWorkspace: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  listWorkspaces: async () => h.server,
  listMembers: async () => ({ my_role: h.role, members: [] }),
  listActivity: async () => [],
  deleteWorkspace: (id: string) => h.deleteWorkspace(id),
  renameWorkspace: vi.fn(),
  inviteMember: vi.fn(),
  removeMember: vi.fn(),
  setMemberRole: vi.fn(),
}));

import { TeamSection } from "@/features/settings/TeamSection";

function mount(current: { id: string; name: string; role: string }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TeamSection workspace={current as Workspace} />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  h.role = "owner";
  h.deleteWorkspace.mockReset();
  h.deleteWorkspace.mockImplementation(async (id: string) => {
    h.server = h.server.filter((one) => one.id !== id);
  });
});

it("只剩一个工作区:owner 也删不了,按钮灰掉并说原因", async () => {
  h.server = [{ id: "w1", name: "唯一", role: "owner" }];
  mount(h.server[0]);
  const remove = await screen.findByRole("button", { name: /deleteWorkspace/ });
  await waitFor(() => expect(remove).toHaveAttribute("title", "workspaceDeleteLastOne"));
  expect(remove).toBeDisabled();
});

it("admin 能改名但看不到删除", async () => {
  h.role = "admin";
  h.server = [
    { id: "w1", name: "一", role: "admin" },
    { id: "w2", name: "二", role: "owner" },
  ];
  mount(h.server[0]);
  expect(await screen.findByRole("button", { name: /rename/ })).toBeEnabled();
  await waitFor(() => expect(screen.queryByRole("button", { name: /deleteWorkspace/ })).toBeNull());
});

it("删掉当前工作区:列表缓存里立刻拿掉它(WorkspaceGate 据此落到下一个)", async () => {
  h.server = [
    { id: "w1", name: "一", role: "owner" },
    { id: "w2", name: "二", role: "owner" },
  ];
  const client = mount(h.server[0]);
  const remove = await screen.findByRole("button", { name: /deleteWorkspace/ });
  await waitFor(() => expect(remove).toBeEnabled());
  fireEvent.click(remove);
  fireEvent.click(await screen.findByRole("button", { name: "confirm" }));
  await waitFor(() => expect(h.deleteWorkspace).toHaveBeenCalledWith("w1"));
  await waitFor(() =>
    expect(client.getQueryData<Workspace[]>(workspaceKeys.all())?.map((one) => one.id)).toEqual(["w2"]),
  );
});
