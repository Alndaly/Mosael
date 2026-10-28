/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 删机器人要**先问一句**。
 *
 * 这一页别的删除(记忆、技能)都走 `ConfirmDialog`,只有删机器人是点一下就删 —— 而它删掉的是
 * 「长连接断掉 + 名下绑定一起走」。维护者 2026-10-24 指出的正是这一处。
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
const BOT = {
  id: "bot-a", workspace_id: "ws-1", name: "机器人 A", app_id: "cli_a",
  capability: "editor", enabled: true, status: "online", status_detail: "",
};

const deletes: string[] = [];

beforeEach(() => {
  deletes.length = 0;
  api.mockReset();
  api.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path.startsWith("/api/feishu/bots?")) return [BOT];
    if (init?.method === "DELETE") {
      deletes.push(path);
      return undefined;
    }
    throw new Error(`unexpected request: ${path}`);
  });
});

it("点删除先弹确认:不点确认不发 DELETE;确认后才删", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <FeishuSection workspace={WORKSPACE} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("机器人 A")).toBeTruthy());

  await userEvent.click(screen.getByRole("button", { name: zh.feishuRemove }));
  //: 弹窗里写着要删的是哪一台,以及会发生什么(长连接断、绑定一起走)。
  await waitFor(() => expect(screen.getByText(zh.feishuRemoveTitle)).toBeTruthy());
  expect(screen.getByText(zh.feishuRemoveBody.replace("{name}", "机器人 A"))).toBeTruthy();
  expect(deletes).toHaveLength(0);

  //: 取消 —— 什么都不发。
  await userEvent.click(screen.getByRole("button", { name: zh.cancel }));
  await waitFor(() => expect(screen.queryByText(zh.feishuRemoveTitle)).toBeNull());
  expect(deletes).toHaveLength(0);

  //: 再来一次,这次确认。
  await userEvent.click(screen.getByRole("button", { name: zh.feishuRemove }));
  await waitFor(() => expect(screen.getByText(zh.feishuRemoveTitle)).toBeTruthy());
  await userEvent.click(screen.getAllByRole("button", { name: zh.feishuRemove }).at(-1)!);
  await waitFor(() => expect(deletes).toEqual(["/api/feishu/bots/bot-a"]));
});
