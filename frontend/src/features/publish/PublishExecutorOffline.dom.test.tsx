/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Workspace } from "@/api/client";

/**
 * 排着队却没人干活的时候,界面要说出来。
 *
 * 发布执行器是**另一个进程**(Electron 主进程里那份),后端只负责排队。执行器没起来,任务就
 * 停在 queued 上不动 —— 而界面此前对此一个字都不说,用户看到的是"点了发布,然后什么都没
 * 发生"。`GET /api/publish/worker/status` 这条接口一直存在,**唯一调用方是它自己的测试**
 * (见进程审计 2.10 的死字段清单)。现在它有了一个真正的读者,这几条守的就是那个读者。
 */

const tasks = vi.fn();
const online = vi.fn();
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  listPublishTasks: (...args: unknown[]) => tasks(...args),
  publishWorkerOnline: (...args: unknown[]) => online(...args),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "en-US" }),
}));

const { PublishView } = await import("./PublishView");

const queued = { id: "q", title: "Waiting", status: "queued", created_at: "2026-09-22T10:00:00Z", tags: [], result: {} };
const done = { id: "d", title: "Done", status: "succeeded", created_at: "2026-09-22T10:00:00Z", tags: [], result: {} };

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PublishView workspace={{ id: "qa" } as Workspace} />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  tasks.mockReset();
  online.mockReset();
});

it("有活儿排着而执行器离线时,说清楚为什么不动", async () => {
  tasks.mockResolvedValue([queued]);
  online.mockResolvedValue({ online: false });

  show();

  expect(await screen.findByText("publishExecutorOffline")).toBeInTheDocument();
});

it("执行器在线就不出声 —— 一条常驻的警告等于没有警告", async () => {
  tasks.mockResolvedValue([queued]);
  online.mockResolvedValue({ online: true });

  show();

  await screen.findByRole("button", { name: /Waiting/ });
  expect(screen.queryByText("publishExecutorOffline")).not.toBeInTheDocument();
});

it("没有待办就根本不问 —— 省得每 10 秒一次空轮询", async () => {
  tasks.mockResolvedValue([done]);
  online.mockResolvedValue({ online: false });

  show();

  await screen.findByRole("button", { name: /Done/ });
  await waitFor(() => expect(online).not.toHaveBeenCalled());
  expect(screen.queryByText("publishExecutorOffline")).not.toBeInTheDocument();
});

it("还没问到答案时不报警 —— 否则刚进页面会闪一条假的", async () => {
  tasks.mockResolvedValue([queued]);
  online.mockReturnValue(new Promise(() => {}));

  show();

  await screen.findByRole("button", { name: /Waiting/ });
  expect(screen.queryByText("publishExecutorOffline")).not.toBeInTheDocument();
});
