/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 点「重启」之后**立刻**要有反应。
 *
 * 后端重启一条长连接是"立刻受理、后台去连",接口很快就返回;而这一页是每 4 秒轮询一次。
 * 此前只等接口回来再 invalidate —— 中间几秒按钮不转、状态还是上一轮的「错误」,看起来就像
 * "点了没反应"(维护者 2026-10-24:「对应机器人刷新没有 loading」)。
 */

const api = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api }));
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

const BOT = { id: "bot-a", workspace_id: "ws-1", name: "机器人 A", app_id: "cli_a", capability: "editor", enabled: true, status: "error", status_detail: "长连接进程退出(code 2)" };

//: 重启请求挂在这里,由用例自己决定什么时候放行 —— 不靠 slept 的真实毫秒等它。
let releaseRestart: (value: unknown) => void = () => undefined;
const pending = { promise: Promise.resolve({}) as Promise<unknown> };

beforeEach(() => {
  pending.promise = new Promise((resolve) => {
    releaseRestart = resolve;
  });
  api.mockReset();
  api.mockImplementation(async (path: string) => {
    if (path.startsWith("/api/feishu/bots?")) return [BOT];
    if (path.endsWith("/restart")) {
      //: 重启接口**不立刻返回**:好断言"请求还在飞"时的样子(用挂起的 promise,不睡真计时器)。
      return pending.promise;
    }
    throw new Error(`unexpected request: ${path}`);
  });
});

it("点重启:这一行立刻变成「连接中」,刷新钮转圈;真实状态由轮询写回", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <FeishuSection workspace={WORKSPACE} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("机器人 A")).toBeTruthy());
  expect(screen.getByText(zh.feishuStatusError)).toBeTruthy();

  const restart = screen.getByRole("button", { name: zh.feishuRestart });
  await userEvent.click(restart);

  //: 请求还在飞的时候就已经是「连接中」—— 不等接口返回,也不等下一次轮询。
  await waitFor(() => expect(screen.getByText(zh.feishuStatusConnecting)).toBeTruthy());
  expect(screen.queryByText(zh.feishuStatusError)).toBeNull();
  expect(restart.getAttribute("aria-busy")).toBe("true");

  //: 放行之后,真实状态由接口那条回写(status: connecting)接管,转圈继续 —— 直到轮询把 online/error 写回。
  releaseRestart({ ...BOT, status: "connecting" });
  await waitFor(() => expect(screen.getByText(zh.feishuStatusConnecting)).toBeTruthy());
});
