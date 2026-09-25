/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 版本历史:每一版写着是谁存的;当前那一版是**别人**存的、我还没认可时,给「认可这一版」——
 * 只有它借不到我的私有账号 / 档案 / 本机文件(见后端 domain/authority)。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const attested: Array<[string, number]> = [];
let rows: Array<Record<string, unknown>> = [];
vi.mock("@/api/client", () => ({
  listWorkflowRevisions: () => Promise.resolve(rows),
  restoreWorkflowRevision: vi.fn(),
  attestWorkflowRevision: (workflowId: string, revision: number) => {
    attested.push([workflowId, revision]);
    return Promise.resolve({});
  },
}));

const { WorkflowRevisionHistory } = await import("./WorkflowRevisionHistory");

const workflow = { id: "wf", workspace_id: "ws", revision: 2, graph_hash: "h2" } as never;
const row = (revision: number, createdBy: string, attestedBy: string[] = []) => ({
  id: `r${revision}`, workflow_id: "wf", revision, graph_hash: `h${revision}`, source: "edit", note: "",
  created_by: createdBy, created_by_name: createdBy === "me" ? "Me" : "Mate", attested_by: attestedBy,
  created_at: "2026-09-20T00:00:00Z",
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkflowRevisionHistory workflow={workflow} open onOpenChange={() => {}} onRestored={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  attested.length = 0;
});

it("别人存的当前版给「认可这一版」,点下去认可的就是这一版", async () => {
  rows = [row(2, "mate"), row(1, "me")];
  show();
  expect(await screen.findAllByText("wfRevisionAuthor")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: /wfRevisionAttest/ }));
  await waitFor(() => expect(attested).toEqual([["wf", 2]]));
});

it("我存的、或我已认可过的当前版,不再给认可按钮", async () => {
  rows = [row(2, "me")];
  const { unmount } = show();
  await screen.findByText("wfRevisionAuthor");
  expect(screen.queryByRole("button", { name: /wfRevisionAttest/ })).toBeNull();
  unmount();

  rows = [row(2, "mate", ["me"])];
  show();
  expect(await screen.findByText("wfRevisionYouVouch")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /wfRevisionAttest/ })).toBeNull();
});
