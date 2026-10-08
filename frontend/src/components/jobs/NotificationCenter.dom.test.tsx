/** @vitest-environment jsdom */
/**
 * 角标数的是「等着人看的东西」:未读通知 + 待处理邀请。但「全部已读」只管通知 ——
 * 邀请得接受或拒绝,标已读消不掉它。此前那个按钮按角标判,只有邀请时也摆着,点了数字纹丝不动。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
const h = vi.hoisted(() => ({ unread: 0, invitations: [] as unknown[], respond: vi.fn() }));
vi.mock("@/api/client", () => ({
  listNotifications: async () => ({ items: [], unread: h.unread }),
  myInvitations: async () => ({ invitations: h.invitations }),
  readAllNotifications: vi.fn(),
  readNotification: vi.fn(),
  clearReadNotifications: vi.fn(),
  respondInvitation: (id: string, accept: boolean) => h.respond(id, accept),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { NotificationCenter } from "@/components/jobs/NotificationCenter";

const INVITE = { id: "i1", workspace_name: "别人的工作区", inviter_name: "小美", role: "editor" };

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <NotificationCenter workspaceId="w1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.unread = 0;
  h.invitations = [];
});

it("只有待处理邀请:角标算上它,但不摆「全部已读」", async () => {
  h.invitations = [INVITE];
  mount();
  const bell = screen.getByRole("button", { name: "notifTitle" });
  expect(await screen.findByText("1")).toBeInTheDocument();
  fireEvent.click(bell);
  expect(await screen.findByText("notifInviteTitle")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /notifReadAll/ })).toBeNull();
});

it("有未读通知时才摆「全部已读」", async () => {
  h.unread = 2;
  h.invitations = [INVITE];
  mount();
  expect(await screen.findByText("3")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "notifTitle" }));
  expect(await screen.findByRole("button", { name: /notifReadAll/ })).toBeInTheDocument();
});

//: 体检 UM-35:此前所有邀请卡的「接受 / 拒绝」看同一个 isPending,点一张,两张卡四个按钮一起转。
it("两张邀请卡:点了一张的「接受」,只有那一个键在转,另一张卡照常能点", async () => {
  h.invitations = [INVITE, { ...INVITE, id: "i2", workspace_name: "另一个工作区" }];
  h.respond.mockImplementation(() => new Promise(() => undefined));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "notifTitle" }));
  const cards = (await screen.findAllByText("notifInviteTitle")).map((title) => title.parentElement as HTMLElement);
  fireEvent.click(within(cards[0]).getByRole("button", { name: /notifInviteAccept/ }));
  await waitFor(() => expect(h.respond).toHaveBeenCalledWith("i1", true));
  await waitFor(() => expect(within(cards[0]).getByRole("button", { name: /notifInviteAccept/ })).toHaveAttribute("aria-busy", "true"));
  expect(within(cards[0]).getByRole("button", { name: /notifInviteDecline/ })).toBeDisabled();
  expect(within(cards[1]).getByRole("button", { name: /notifInviteAccept/ })).toBeEnabled();
  expect(within(cards[1]).getByRole("button", { name: /notifInviteAccept/ })).not.toHaveAttribute("aria-busy");

  //: 点另一张的「拒绝」:转的是那张的「拒绝」,它的「接受」按不动。
  fireEvent.click(within(cards[1]).getByRole("button", { name: /notifInviteDecline/ }));
  await waitFor(() => expect(within(cards[1]).getByRole("button", { name: /notifInviteDecline/ })).toHaveAttribute("aria-busy", "true"));
  expect(within(cards[1]).getByRole("button", { name: /notifInviteAccept/ })).toBeDisabled();
});
