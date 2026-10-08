/** @vitest-environment jsdom */
/**
 * 「清空已结束」是物理删除,删的是整个工作区所有人的已结束任务 —— 先开确认框,写清会删几条、
 * 几条是别人的、留下几条,确认才删。此前一点就删(UM-01),工作流的执行历史跟着没了。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
const h = vi.hoisted(() => ({
  preview: vi.fn(),
  clear: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: h.toast }));
const FINISHED = [{ id: "j1", kind: "proxy", status: "succeeded", progress: 1, message: "done", error: null, payload: {}, created_at: "2026-10-08T00:00:00", updated_at: "2026-10-08T00:00:00" }];
vi.mock("@/api/client", () => ({
  api: vi.fn(async () => FINISHED),
  fetchJobKinds: async () => ({
    kinds: [],
    fallback: { kind: "", label: "任务", announce: "never", affects: [], view: null, record_field: null },
  }),
  getJob: vi.fn(),
  previewClearFinished: h.preview,
  clearFinishedJobs: h.clear,
  topLevelJobsQuery: (workspaceId: string) => ({
    queryKey: ["jobs", workspaceId, "top-level"],
    queryFn: async () => FINISHED,
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

async function openConfirm() {
  fireEvent.click(screen.getByRole("button", { name: "taskCenter" }));
  fireEvent.click(await screen.findByRole("button", { name: /clearEnded/ }));
  return screen.findByRole("alertdialog");
}

beforeEach(() => {
  h.preview.mockReset();
  h.clear.mockReset();
  h.toast.success.mockReset();
});

describe("清空已结束", () => {
  it("点一下只开确认框、不删;框里写会删几条、几条是别人的、留下几条", async () => {
    h.preview.mockResolvedValue({ tasks: 3, jobs: 5, by_others: 1, kept: 2 });
    mount();
    const dialog = await openConfirm();

    await waitFor(() => expect(dialog.textContent).toContain("clearEndedBody"));
    expect(dialog.textContent).toContain("clearEndedByOthers");
    expect(dialog.textContent).toContain("clearEndedKept");
    expect(h.preview).toHaveBeenCalledWith("w1");
    expect(h.clear).not.toHaveBeenCalled();
  });

  it("确认之后才删,删完说删了几个", async () => {
    h.preview.mockResolvedValue({ tasks: 3, jobs: 5, by_others: 0, kept: 0 });
    h.clear.mockResolvedValue({ removed: 5 });
    mount();
    const dialog = await openConfirm();
    const confirm = await waitFor(() => {
      const button = [...dialog.querySelectorAll("button")].find((one) => one.textContent === "clearEndedConfirm");
      if (!button) throw new Error("confirm button not ready");
      return button;
    });
    expect(dialog.textContent).not.toContain("clearEndedByOthers");

    fireEvent.click(confirm);
    await waitFor(() => expect(h.clear).toHaveBeenCalledWith("w1"));
    await waitFor(() => expect(h.toast.success).toHaveBeenCalledWith("clearEndedDone"));
  });

  it("还在数、或者没有可删的:确认键按不下去", async () => {
    let resolve: (value: unknown) => void = () => {};
    h.preview.mockReturnValue(new Promise((done) => (resolve = done)));
    mount();
    const dialog = await openConfirm();
    expect(dialog.textContent).toContain("clearEndedCounting");
    const confirm = [...dialog.querySelectorAll("button")].find((one) => one.textContent === "confirm");
    expect(confirm?.hasAttribute("disabled")).toBe(true);

    resolve({ tasks: 0, jobs: 0, by_others: 0, kept: 4 });
    await waitFor(() => expect(dialog.textContent).toContain("clearEndedNothing"));
    expect(dialog.textContent).toContain("clearEndedKept");
    expect([...dialog.querySelectorAll("button")].find((one) => one.textContent === "confirm")?.hasAttribute("disabled")).toBe(true);
    expect(h.clear).not.toHaveBeenCalled();
  });
});
