/** @vitest-environment jsdom */
/**
 * 登录之后兑现待处理的那张邀请链接(ADR 0054 D51):直接加入、切过去,toast 写主人和角色,能撤销(退出、切回原来那个)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  redeem: vi.fn(),
  remove: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: h.success, error: h.error } }));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      inviteJoined: "已加入「{name}」",
      inviteAlreadyMember: "你已经在「{name}」里了",
      inviteJoinedDetail: "主人:{owner} · 你的角色:{role}",
      role_editor: "编辑者",
    })[key] ?? key,
}));
vi.mock("@/api/client", () => ({
  redeemInviteLink: (code: string) => h.redeem(code),
  removeMember: (ws: string, user: string) => h.remove(ws, user),
}));

const { useJoinFromInvite } = await import("./useJoinFromInvite");
const { pendingInvite, setPendingInvite } = await import("@/lib/inviteLinks");

const selected: string[] = [];

function Probe({ current }: { current: string | null }) {
  const joining = useJoinFromInvite((id) => selected.push(id), current);
  return <span data-joining={joining ? "yes" : "no"} />;
}

function mount(current: string | null = "old-ws") {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Probe current={current} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  selected.length = 0;
  for (const fn of Object.values(h)) fn.mockReset();
});
afterEach(() => cleanup());

it("没有待处理的邀请:什么都不做", () => {
  mount();
  expect(h.redeem).not.toHaveBeenCalled();
  expect(document.querySelector("[data-joining]")?.getAttribute("data-joining")).toBe("no");
});

it("兑现、切过去、toast 写主人和角色;撤销 = 退出并切回原来那个", async () => {
  setPendingInvite("Invite-Code-1234");
  h.redeem.mockResolvedValue({ workspace_id: "team-ws", workspace_name: "内容组", role: "editor", owner_name: "阿青", already_member: false });
  h.remove.mockResolvedValue(undefined);
  mount("old-ws");
  await waitFor(() => expect(selected).toEqual(["team-ws"]));
  expect(h.redeem).toHaveBeenCalledTimes(1);
  expect(pendingInvite()).toBeNull();
  const [title, options] = h.success.mock.calls[0];
  expect(title).toBe("已加入「内容组」");
  expect(options.description).toBe("主人:阿青 · 你的角色:编辑者");

  options.action.onClick();
  await waitFor(() => expect(h.remove).toHaveBeenCalledWith("team-ws", "me"));
  await waitFor(() => expect(selected).toEqual(["team-ws", "old-ws"]));
});

it("本来就是成员:切过去,不给撤销(撤销会把原有的成员身份也退掉)", async () => {
  setPendingInvite("Invite-Code-1234");
  h.redeem.mockResolvedValue({ workspace_id: "team-ws", workspace_name: "内容组", role: "editor", owner_name: "阿青", already_member: true });
  mount();
  await waitFor(() => expect(h.success).toHaveBeenCalled());
  const [title, options] = h.success.mock.calls[0];
  expect(title).toBe("你已经在「内容组」里了");
  expect(options.action).toBeUndefined();
});

it("用不了:说一声,放下这张", async () => {
  setPendingInvite("Invite-Code-1234");
  h.redeem.mockRejectedValue(new Error("这个邀请链接已经有人用过了"));
  mount();
  await waitFor(() => expect(h.error).toHaveBeenCalled());
  expect(h.error.mock.calls[0][1]).toEqual({ description: "这个邀请链接已经有人用过了" });
  expect(pendingInvite()).toBeNull();
  expect(selected).toEqual([]);
});
