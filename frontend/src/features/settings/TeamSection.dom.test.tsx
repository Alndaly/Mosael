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
import { readHint } from "@/test/hint";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));
const h = vi.hoisted(() => ({
  role: "owner",
  server: [] as Array<{ id: string; name: string; role: string }>,
  members: [] as Array<Record<string, unknown>>,
  sent: [] as Array<Record<string, unknown>>,
  deleteWorkspace: vi.fn(),
  inviteMember: vi.fn(),
  revokeInvitation: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  listWorkspaces: async () => h.server,
  listMembers: async () => ({ my_role: h.role, members: h.members }),
  sentInvitations: async () => ({ invitations: h.sent }),
  revokeInvitation: (wid: string, id: string) => h.revokeInvitation(wid, id),
  listActivity: async () => [],
  deleteWorkspace: (id: string) => h.deleteWorkspace(id),
  renameWorkspace: vi.fn(),
  inviteMember: (wid: string, body: unknown) => h.inviteMember(wid, body),
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
  h.members = [];
  h.sent = [];
  h.inviteMember.mockReset();
  h.revokeInvitation.mockReset();
  h.revokeInvitation.mockResolvedValue(undefined);
  h.deleteWorkspace.mockReset();
  h.deleteWorkspace.mockImplementation(async (id: string) => {
    h.server = h.server.filter((one) => one.id !== id);
  });
});

it("只剩一个工作区:owner 也删不了,按钮灰掉并说原因", async () => {
  h.server = [{ id: "w1", name: "唯一", role: "owner" }];
  mount(h.server[0]);
  const remove = await screen.findByRole("button", { name: /deleteWorkspace/ });
  await waitFor(() => expect(remove).toBeDisabled());
  expect(await readHint(remove)).toBe("workspaceDeleteLastOne");
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
  // 灰着时按钮外面多一层说明原因的壳,能点了壳就拿掉 —— 按钮会换一个元素,所以每次都重新找。
  await waitFor(() => expect(screen.getByRole("button", { name: /deleteWorkspace/ })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: /deleteWorkspace/ }));
  const confirm = await screen.findByRole("button", { name: "deleteWorkspacePermanently" });
  fireEvent.change(screen.getByRole("textbox", { name: "deleteWorkspaceTypeName" }), { target: { value: "一 " } });
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);
  await waitFor(() => expect(h.deleteWorkspace).toHaveBeenCalledWith("w1"));
  await waitFor(() =>
    expect(client.getQueryData<Workspace[]>(workspaceKeys.all())?.map((one) => one.id)).toEqual(["w2"]),
  );
});

//: 体检 UM-07:邀请出错时此前只把「用户名」三个字染红,一句话都没有。
it("邀请出错时把后端给的原因写在输入框下面", async () => {
  h.server = [{ id: "w1", name: "Studio", role: "owner" }];
  h.inviteMember.mockRejectedValue(new Error("没有这个用户名。对方要先有这台 Mosael 的账号"));
  mount(h.server[0]);
  fireEvent.change(await screen.findByPlaceholderText("teamInvitePlaceholder"), { target: { value: "nosuchuser" } });
  fireEvent.click(screen.getByRole("button", { name: /teamInvite/ }));
  expect(await screen.findByText("没有这个用户名。对方要先有这台 Mosael 的账号")).toBeInTheDocument();
});

it("发出去、还没应答的邀请列在成员下面,能撤回(先问一句)", async () => {
  h.server = [{ id: "w1", name: "Studio", role: "owner" }];
  h.sent = [{ id: "inv1", workspace_id: "w1", workspace_name: "Studio", inviter_name: "Me", invitee_name: "Mate", role: "viewer", status: "pending", created_at: "2026-10-08T00:00:00Z" }];
  const { container } = (() => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <TeamSection workspace={h.server[0] as Workspace} />
      </QueryClientProvider>,
    );
  })();
  expect(await screen.findByText("Mate")).toBeInTheDocument();
  expect(container.querySelector('[data-pending-invitation="inv1"]')?.textContent).toContain("role_viewer");
  fireEvent.click(screen.getByRole("button", { name: "teamInviteRevoke" }));
  fireEvent.click(await screen.findByRole("button", { name: "teamInviteRevoke" }));
  await waitFor(() => expect(h.revokeInvitation).toHaveBeenCalledWith("w1", "inv1"));
});

it("编辑看不到发出去的邀请(和后端同一道闸),也就不去要", async () => {
  h.role = "editor";
  h.server = [{ id: "w1", name: "Studio", role: "editor" }];
  h.sent = [{ id: "inv1", workspace_id: "w1", workspace_name: "Studio", inviter_name: "Me", invitee_name: "Mate", role: "viewer", status: "pending", created_at: "2026-10-08T00:00:00Z" }];
  mount(h.server[0]);
  await screen.findByText("Studio");
  await waitFor(() => expect(screen.queryByText("Mate")).toBeNull());
});

//: 体检 UM-29:退出确认此前把自己的用户名当成工作区名(「确定退出「uiviewer」所在的工作区?」)。
it("退出确认里写的是工作区名,不是自己的用户名", async () => {
  h.role = "viewer";
  h.server = [{ id: "w1", name: "Studio", role: "viewer" }];
  h.members = [{ user_id: "u1", username: "uiviewer", display_name: "Viewer", role: "viewer", is_self: true }];
  mount(h.server[0]);
  fireEvent.click(await screen.findByRole("button", { name: "teamLeave" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog.textContent).toContain("teamLeaveConfirm");
  expect(dialog.textContent).not.toContain("uiviewer");
});
