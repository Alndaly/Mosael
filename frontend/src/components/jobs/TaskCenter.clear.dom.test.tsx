/** @vitest-environment jsdom */
/**
 * 「清空已结束」只从我的面板上拿掉,不删任何东西(ADR 0050 D27):一点就清,不要确认框;清掉的在底下「显示已清掉的」里翻得回来(D28)。
 * 此前它是物理删除整个工作区所有人的已结束任务,先弹确认框。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
const job = (id: string) => ({
  id, kind: "proxy", status: "succeeded", progress: 1, message: `done ${id}`, error: null, payload: {},
  created_at: "2026-10-08T00:00:00", updated_at: "2026-10-08T00:00:00",
});
const h = vi.hoisted(() => ({
  panel: { jobs: [] as unknown[], cleared_at: null as string | null },
  cleared: { jobs: [] as unknown[], cleared_at: null as string | null },
  clear: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: h.toast }));
vi.mock("@/api/client", () => ({
  api: vi.fn(),
  fetchJobKinds: async () => ({
    kinds: [],
    fallback: { kind: "", label: "任务", announce: "never", affects: [], view: null, record_field: null },
  }),
  getJob: vi.fn(),
  clearTaskCenter: h.clear,
  taskCenterQuery: (workspaceId: string, { cleared = false }: { cleared?: boolean } = {}) => ({
    queryKey: ["jobs", workspaceId, "task-center", cleared ? "cleared" : "shown"],
    queryFn: async () => (cleared ? h.cleared : h.panel),
  }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { TaskCenter } from "./TaskCenter";

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TaskCenter workspaceId="w1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.panel = { jobs: [job("j1")], cleared_at: null };
  h.cleared = { jobs: [], cleared_at: null };
  h.clear.mockReset();
  h.toast.success.mockReset();
});

describe("清空已结束", () => {
  it("一点就清,不弹确认框;清完面板重新取,说的是「从你的面板清掉」", async () => {
    h.clear.mockImplementation(async () => {
      h.panel = { jobs: [], cleared_at: "2026-10-09T00:00:00" };
      return { cleared_at: "2026-10-09T00:00:00" };
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "taskCenter" }));
    fireEvent.click(await screen.findByRole("button", { name: /clearEnded/ }));

    await waitFor(() => expect(h.clear).toHaveBeenCalledWith("w1"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(h.toast.success).toHaveBeenCalledWith("clearEndedDone"));
    await waitFor(() => expect(screen.queryByText("done j1")).toBeNull());
  });

  it("清过之后底下有「显示已清掉的」,打开列出水位线之前结束的;没清过就没有这个开关", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "taskCenter" }));
    await screen.findByText("done j1");
    expect(screen.queryByRole("button", { name: /clearedShow/ })).toBeNull();
  });

  it("打开「显示已清掉的」只是看,点开照样看详情", async () => {
    h.panel = { jobs: [], cleared_at: "2026-10-09T00:00:00" };
    h.cleared = { jobs: [job("old")], cleared_at: "2026-10-09T00:00:00" };
    mount();
    fireEvent.click(screen.getByRole("button", { name: "taskCenter" }));
    const toggle = await screen.findByRole("button", { name: /clearedShow/ });
    expect(screen.queryByText("done old")).toBeNull();
    fireEvent.click(toggle);
    const section = (await screen.findByText("done old")).closest("[data-cleared-jobs]") as HTMLElement;
    expect(section).not.toBeNull();
    expect(within(section).getByRole("button", { name: /clearedHide/ })).toHaveAttribute("aria-expanded", "true");
    expect(h.clear).not.toHaveBeenCalled();
  });
});
