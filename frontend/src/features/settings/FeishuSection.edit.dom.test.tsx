/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 「编辑机器人」这个入口。
 *
 * 此前没有它 —— 而这台机器上的 App Secret 因为主密钥换过已经解不开,唯一的出路就是**重填一次**;
 * 没有编辑入口,用户只能望着「长连接进程退出(code 2)」(2026-10-24)。
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
  capability: "editor", enabled: true, status: "error", status_detail: "长连接进程退出(code 2)",
};

const patches: Array<Record<string, unknown>> = [];

beforeEach(() => {
  patches.length = 0;
  api.mockReset();
  api.mockImplementation(async (path: string, init?: { method?: string; body?: string }) => {
    if (path.startsWith("/api/feishu/bots?")) return [BOT];
    if (init?.method === "PATCH") {
      const body = JSON.parse(init.body ?? "{}") as Record<string, unknown>;
      patches.push(body);
      return { ...BOT, ...body };
    }
    throw new Error(`unexpected request: ${path}`);
  });
});

it("行内有一颗「编辑」:改名称与 App Secret,留空的项不提交", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <FeishuSection workspace={WORKSPACE} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("机器人 A")).toBeTruthy());

  await userEvent.click(screen.getByRole("button", { name: zh.feishuEdit }));
  await waitFor(() => expect(screen.getByDisplayValue("机器人 A")).toBeTruthy());

  //: App ID 预填当前值;Secret **不回显**,留空 = 不修改。
  expect(screen.getByDisplayValue("cli_a")).toBeTruthy();
  const secret = screen.getByPlaceholderText(zh.feishuEditSecretPlaceholder);
  const name = screen.getByDisplayValue("机器人 A");
  await userEvent.clear(name);
  await userEvent.type(name, "新名字");
  await userEvent.type(secret, "s3cret-new");
  await userEvent.click(screen.getByRole("button", { name: zh.feishuEditSave }));

  await waitFor(() => expect(patches).toHaveLength(1));
  expect(patches[0]).toEqual({ name: "新名字", app_id: "cli_a", app_secret: "s3cret-new" });
});

it("Secret 留空时不提交 app_secret(没有原值可回填)", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <FeishuSection workspace={WORKSPACE} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("机器人 A")).toBeTruthy());
  await userEvent.click(screen.getByRole("button", { name: zh.feishuEdit }));
  await waitFor(() => expect(screen.getByDisplayValue("机器人 A")).toBeTruthy());
  await userEvent.click(screen.getByRole("button", { name: zh.feishuEditSave }));

  await waitFor(() => expect(patches).toHaveLength(1));
  expect(patches[0]).not.toHaveProperty("app_secret");
});
