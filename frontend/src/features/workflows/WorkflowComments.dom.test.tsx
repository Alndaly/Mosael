/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useWorkflowComments } from "./WorkflowComments";

const api = vi.hoisted(() => ({ list: vi.fn(), add: vi.fn(), remove: vi.fn() }));
vi.mock("@/api/client", () => ({ listComments: api.list, addComment: api.add, deleteComment: api.remove, listMembers: async () => ({ members: [] }) }));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ ViewportPortal: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("@/features/boards/BoardCommentComposer", () => ({ BoardCommentComposer: ({ onSubmit }: { onSubmit: (draft: unknown) => void }) => <button onClick={() => onSubmit({ body: "Review this shot", bodyDocument: { type: "doc" }, mentionedUserIds: [] })}>Submit draft</button> }));

const comment = { id: "c1", author_id: "me", body: "Existing comment", anchor: { x: 50, y: 60 }, author: { username: "Me" } };
function Harness() {
  const comments = useWorkflowComments("ws", "flow");
  return <>{comments.controls(() => {})}<button onClick={() => comments.place({ x: 120, y: 240, node_id: "node1" })}>Canvas click</button>{comments.layer}</>;
}
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);
}
beforeEach(() => { vi.clearAllMocks(); api.list.mockResolvedValue([comment]); api.add.mockResolvedValue({ ...comment, id: "c2" }); });
afterEach(cleanup);

it("hiding comments preserves their data and exits editing", async () => {
  const { container } = setup();
  await screen.findByRole("button", { name: "comments 1" });
  expect(container.querySelector("[data-workflow-comment]")).toHaveStyle({ pointerEvents: "none" });
  fireEvent.click(screen.getByRole("button", { name: "boardCommentMode" }));
  fireEvent.click(screen.getByRole("button", { name: "comments 1" }));
  expect(screen.getByText("Existing comment")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "commentsHide" }));
  expect(container.querySelector("[data-workflow-comment]")).toBeNull();
  expect(screen.getByRole("button", { name: "boardCommentMode" })).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(screen.getByRole("button", { name: "commentsShow" }));
  expect(screen.getByRole("button", { name: "comments 1" })).toHaveAttribute("tabindex", "-1");
  expect(api.remove).not.toHaveBeenCalled();
});

it("creates an anchored workflow comment only in comment mode", async () => {
  setup();
  fireEvent.click(screen.getByText("Canvas click"));
  expect(screen.queryByText("Submit draft")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "boardCommentMode" }));
  fireEvent.click(screen.getByText("Canvas click"));
  fireEvent.click(screen.getByText("Submit draft"));
  await waitFor(() => expect(api.add).toHaveBeenCalledWith({
    workspace_id: "ws", subject_type: "workflow", subject_id: "flow", body: "Review this shot",
    body_document: { type: "doc" }, mentioned_user_ids: [], anchor: { kind: "canvas", x: 120, y: 240, node_id: "node1" },
  }));
});
