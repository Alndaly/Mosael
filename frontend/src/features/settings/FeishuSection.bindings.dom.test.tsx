/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「绑定飞书账号」那个弹窗里那张**名单**:按人归并,并说清每一条是**哪台机器人**眼里的。
 *
 * 维护者报的「重复用户」有两个来源。此前列表按 `open_id` 一行一条、只印 `username`,于是同一个人
 * 在两台应用里就是两行一模一样的名字(open_id 按应用隔离,这是必然的)。
 *
 * 现在这一页的列表是**这台机器人**的(接口按 `bot_id` 取),所以两条同名的行只可能是同一个人在两台
 * 机器人上的两次绑定 —— 按人归并成一条,展开看得到他绑过哪几台。`bot_id` 是这一页真正读的东西 ——
 * 不是靠别处同名标识符过棘轮(见 backend/tests/test_api_fields_reach_the_screen.py)。
 */

const api = vi.hoisted(() => vi.fn());
vi.mock("@/api/transport", () => ({ api }));
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const table = messages["zh-CN"] as Record<string, string>;
  return { useI18n: () => (key: string) => table[key] ?? key };
});
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn(async () => "data:image/png;base64,x") } }));

import { messages } from "@/app/messages";
import { FeishuSection } from "@/features/settings/FeishuSection";

const zh = messages["zh-CN"] as Record<string, string>;
const WORKSPACE = { id: "ws-1", name: "W" } as never;

const BOTS = [
  { id: "bot-a", workspace_id: "ws-1", name: "机器人 A", app_id: "cli_a", capability: "editor", enabled: true, status: "online", status_detail: "" },
  { id: "bot-b", workspace_id: "ws-1", name: "机器人 B", app_id: "cli_b", capability: "editor", enabled: true, status: "offline", status_detail: "" },
];

/** 本人(张三)在两台机器人上各绑过一次;李四只在第一台上绑过。 */
const BINDINGS = [
  { open_id: "ou_a_zhangsan", user_id: "u-1", username: "张三", bot_id: "bot-a" },
  { open_id: "ou_b_zhangsan", user_id: "u-1", username: "张三", bot_id: "bot-b" },
  { open_id: "ou_a_lisi", user_id: "u-2", username: "李四", bot_id: "bot-a" },
];

const deleted: string[] = [];

beforeEach(() => {
  api.mockReset();
  deleted.length = 0;
  api.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path.startsWith("/api/feishu/bots?")) return BOTS;
    if (path.endsWith("/bind-code")) return { code: "123456", expires_at: "" };
    if (init?.method === "DELETE") {
      deleted.push(path);
      return undefined;
    }
    if (path.includes("/bindings")) return BINDINGS;
    throw new Error(`unexpected request: ${path}`);
  });
});

async function openPanel() {
  const user = userEvent.setup();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <FeishuSection workspace={WORKSPACE} />
    </QueryClientProvider>,
  );
  //: 每台机器人一颗「绑定账号」—— 点**第一台**(bot-a)那颗,弹窗里就是这台的面板。
  await user.click((await screen.findAllByRole("button", { name: zh.feishuBind }))[0]);
  const dialog = await screen.findByRole("dialog");
  await waitFor(() => expect(dialog.querySelectorAll("[data-feishu-member]").length).toBeGreaterThan(0));
  return { user, dialog };
}

const members = (dialog: HTMLElement) => [...dialog.querySelectorAll<HTMLElement>("[data-feishu-member]")];
const bindingRows = (dialog: HTMLElement) => [...dialog.querySelectorAll<HTMLElement>("[data-feishu-binding]")];

describe("绑定名单", () => {
  it("同一个人只占一条 —— 他绑过的每台机器人各一行", async () => {
    const { dialog } = await openPanel();
    const found = members(dialog);
    //: 张三(两行)+ 李四(一行)按人归并成两条,不是三条。
    expect(found).toHaveLength(2);
    const zhangsan = found.find((row) => row.dataset.feishuMember === "u-1")!;
    expect(zhangsan).toBeTruthy();
    expect(bindingRows(zhangsan)).toHaveLength(2);
  });

  it("每一条说得出是哪台机器人 —— 读的是 bot_id,不是名字猜的", async () => {
    const { dialog } = await openPanel();
    const zhangsan = members(dialog).find((row) => row.dataset.feishuMember === "u-1")!;
    const rows = bindingRows(zhangsan);
    expect(rows.find((row) => row.dataset.feishuBinding === "ou_a_zhangsan")!.textContent).toContain("机器人 A");
    expect(rows.find((row) => row.dataset.feishuBinding === "ou_b_zhangsan")!.textContent).toContain("机器人 B");
  });

  it("删同一个人在这台机器人上的那一条,另一台机器人那一行不动", async () => {
    const { user, dialog } = await openPanel();
    const own = bindingRows(dialog).find((row) => row.dataset.feishuBinding === "ou_a_zhangsan")!;
    await user.click(within(own).getByRole("button", { name: zh.feishuUnbind }));
    await waitFor(() => expect(deleted).toEqual(["/api/feishu/bots/bot-a/bindings/ou_a_zhangsan"]));
    //: 另一台那一行还在名单里。
    expect(bindingRows(dialog).some((row) => row.dataset.feishuBinding === "ou_b_zhangsan")).toBe(true);
  });
});
