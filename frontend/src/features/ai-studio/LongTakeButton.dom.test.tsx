/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ listWorkflows: vi.fn(), createWorkflow: vi.fn(), runWorkflow: vi.fn() }));
vi.mock("@/api/client", async (original) => ({ ...(await original<typeof import("@/api/client")>()), ...api }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { LongTakeButton } from "./LongTakeButton";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function open(prompt = "雨夜走路") {
  render(<QueryClientProvider client={new QueryClient()}><LongTakeButton workspaceId="w" prompt={prompt} /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "genLongTake" }));
}

it("工作区里没有这张工作流:从模板建一份,带着输入框里的想法开跑", async () => {
  api.listWorkflows.mockResolvedValue([]);
  api.createWorkflow.mockResolvedValue({ id: "new" });
  api.runWorkflow.mockResolvedValue({ id: "job" });
  open();
  fireEvent.click(screen.getByRole("button", { name: "genLongTakeStart" }));
  await waitFor(() => expect(api.runWorkflow).toHaveBeenCalledWith("new", { idea: "雨夜走路", target_seconds: 60, max_segments: 12, max_spend: 0 }));
  expect(api.createWorkflow).toHaveBeenCalledWith(expect.objectContaining({ template_id: "long_take_video" }));
});

it("已经有了就用它,不再建一份", async () => {
  api.listWorkflows.mockResolvedValue([{ id: "have", graph: { meta: { template_id: "long_take_video" } } }]);
  api.runWorkflow.mockResolvedValue({ id: "job" });
  open();
  fireEvent.click(screen.getByRole("button", { name: "genLongTakeStart" }));
  await waitFor(() => expect(api.runWorkflow).toHaveBeenCalled());
  expect(api.createWorkflow).not.toHaveBeenCalled();
  expect(api.runWorkflow.mock.calls[0][0]).toBe("have");
});

it("输入框是空的也打得开,没写想法不让开始", () => {
  open("");
  expect((screen.getByRole("button", { name: "genLongTakeStart" }) as HTMLButtonElement).disabled).toBe(true);
});
