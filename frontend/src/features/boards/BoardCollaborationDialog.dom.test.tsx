/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({
    boardCollaboration: "团队讨论",
    boardCollaborationHint: "集中查看画布讨论",
    discussionNavigation: "讨论导航",
    currentDiscussion: "当前讨论",
    boardDiscussionJump: "在画布中查看",
    comments: "评论",
    reviews: "审阅",
    requestReview: "请求审阅",
    reviewerPlaceholder: "选择审阅人",
    reviewNotePlaceholder: "审阅说明（可选）",
    boardCommentModeHint: "点击画布或节点添加评论",
    teamSystemActor: "系统",
  }[key] ?? key),
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));
vi.mock("@/api/client", () => ({
  listComments: vi.fn().mockResolvedValue([{
    id: "comment-1",
    author: { id: "user-2", username: "demo", display_name: "演示成员", avatar_key: "" },
    body: "第一条意见",
    mentioned_user_ids: [],
    anchor: { kind: "canvas", x: 120, y: 240, node_id: "video-1" },
    created_at: "2026-09-04T04:00:00Z",
  }]),
  listReviews: vi.fn().mockResolvedValue([]),
  listMembers: vi.fn().mockResolvedValue({ members: [] }),
  requestReview: vi.fn(),
  decideReview: vi.fn(),
}));

import type { Board, CollaborationComment } from "@/api/client";
import { BoardCollaborationDialog } from "./BoardCollaborationDialog";

afterEach(cleanup);

describe("画布团队讨论中心", () => {
  it("使用讨论导航与详情分栏，不暴露审批式审阅操作", async () => {
    const onJumpToComment = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <BoardCollaborationDialog
          open
          onOpenChange={vi.fn()}
          board={{ id: "board-1", workspace_id: "workspace-1", name: "画板" } as Board}
          onJumpToComment={onJumpToComment}
        />
      </QueryClientProvider>,
    );

    expect((await screen.findAllByText("第一条意见")).length).toBeGreaterThan(0);
    expect(screen.getByRole("navigation", { name: "讨论导航" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "当前讨论" })).toHaveTextContent("第一条意见");
    expect(screen.queryByText("请求审阅")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "在画布中查看" }));
    expect(onJumpToComment).toHaveBeenCalledWith(expect.objectContaining({ id: "comment-1" }) as CollaborationComment);
  });
});
