/** @vitest-environment jsdom */
//: 正在写补充说明时,后台重新拉取回来一份不一样的准则(别人改过、或者窗口重新聚焦):
//: 此前整份盖掉草稿,写了一半的字说没就没。
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.fn();
vi.mock("@/api/client", () => ({
  api: (path: string, init?: RequestInit) => api(path, init),
  listMembers: async () => ({ my_role: "owner", members: [] }),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AutopilotRulesSection } from "./AutopilotRulesSection";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const rules = (over: Record<string, unknown> = {}) => ({
  rules: { http_request: "ask", publish: "ask", run_code: "ask", run_host_code: "ask", blender: "ask", notes: "", ...over },
});

it("有没存的改动时,重新拉回来的准则不盖掉草稿;没改过时照常跟上", async () => {
  api.mockResolvedValueOnce(rules({ notes: "原来的" }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AutopilotRulesSection workspace={{ id: "w1" } as never} />
    </QueryClientProvider>,
  );
  const notes = (await screen.findByDisplayValue("原来的")) as HTMLTextAreaElement;

  fireEvent.change(notes, { target: { value: "原来的,再补一句" } });
  api.mockResolvedValueOnce(rules({ notes: "原来的", http_request: "judge" }));
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["autopilot-rules", "w1"] });
  });
  //: 拉回来的那份已经进了缓存、页面也跟着渲染过一轮 —— 再看草稿还在不在。
  await waitFor(() => expect(client.getQueryData(["autopilot-rules", "w1"])).toEqual(rules({ notes: "原来的", http_request: "judge" })));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(notes.value).toBe("原来的,再补一句");

  //: 存下之后,草稿和服务端对上了 —— 之后别处再改,照常跟上。
  api.mockResolvedValueOnce(rules({ notes: "原来的,再补一句" }));
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining("autopilot-rules"), expect.objectContaining({ method: "PUT" })));
  api.mockResolvedValue(rules({ notes: "别人改的" }));
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["autopilot-rules", "w1"] });
  });
  await waitFor(() => expect(notes.value).toBe("别人改的"));
});
