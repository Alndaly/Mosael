/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { CollaborationComment } from "@/api/client";
import { editComment } from "@/api/domains/collaboration";
import { CommentCard } from "./CommentCard";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/domains/collaboration", () => ({ editComment: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
beforeAll(() => {
  document.elementFromPoint = () => document.body;
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
});
const comment: CollaborationComment = {
  id: "c", workspace_id: "w", subject_type: "board", subject_id: "b", author_id: "me", author: null,
  body: "@同事 看这里", mentioned_user_ids: ["mate"], anchor: { x: 120, y: 50 }, created_at: "", updated_at: "",
  body_document: { type: "doc", content: [{ type: "paragraph", content: [
    { type: "userMention", attrs: { userId: "mate", label: "同事" } }, { type: "text", text: " 看这里" },
  ] }] },
};
function setup(currentUserId = "me", value = comment) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  client.setQueryData(["comments", "w", "board", "b"], [value]);
  const view = render(<QueryClientProvider client={client}><CommentCard comment={value} currentUserId={currentUserId}
    members={[{ user_id: "mate", username: "teammate", display_name: "同事", role: "editor", is_self: false }]} /></QueryClientProvider>);
  return { ...view, client };
}
describe("评论阅读与编辑", () => {
  it("提交后保留可点击的提及标签，按用户 ID 展示成员信息", async () => {
    setup();
    const mention = await screen.findByRole("button", { name: "@同事" });
    expect(mention).toHaveAttribute("data-user-id", "mate");
    await userEvent.click(mention);
    expect(await screen.findByText("@teammate")).toBeInTheDocument();
  });
  it("编辑已有评论时保留提及与锚点，并更新缓存", async () => {
    const { client } = setup();
    vi.mocked(editComment).mockResolvedValue(comment);
    await userEvent.click(screen.getByRole("button", { name: "commentEdit" }));
    expect(await screen.findByRole("button", { name: "@同事" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() => expect(editComment).toHaveBeenCalledWith("c", {
      workspace_id: "w", body: "@同事 看这里", body_document: expect.objectContaining({type: "doc"}), mentioned_user_ids: ["mate"],
    }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "save" })).not.toBeInTheDocument());
    expect(client.getQueryData<CollaborationComment[]>(["comments", "w", "board", "b"])?.[0].anchor).toEqual(comment.anchor);
  });
  it("其他人的评论不可编辑，旧版纯文本不会被当作 HTML", async () => {
    setup("other", { ...comment, body_document: {}, body: "<b>纯文本</b>" });
    expect(screen.queryByRole("button", { name: "commentEdit" })).not.toBeInTheDocument();
    expect(await screen.findByText("<b>纯文本</b>")).toBeInTheDocument();
  });
});
