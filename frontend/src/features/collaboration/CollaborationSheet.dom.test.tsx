/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      boardCollaboration: "团队讨论",
      boardCollaborationHint: "集中查看画布讨论",
      boardDiscussionJump: "在画布中查看",
      commentsEmpty: "还没有评论",
      boardCommentModeHint: "点击画布或节点添加评论",
      teamSystemActor: "系统",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));

const anchored = {
  id: "comment-1",
  author: { id: "user-2", username: "demo", display_name: "演示成员", avatar_key: "" },
  body: "第一条意见",
  mentioned_user_ids: [],
  anchor: { kind: "canvas", x: 120, y: 240, node_id: "video-1" },
  created_at: "2026-09-04T04:00:00Z",
};
/** 接口允许没有锚点的讨论 —— 那种跳不过去。 */
const floating = { ...anchored, id: "comment-2", body: "第二条意见", anchor: null };
const listComments = vi.fn().mockResolvedValue([anchored, floating]);
vi.mock("@/api/client", () => ({
  listComments: (...args: unknown[]) => listComments(...args),
  listMembers: vi.fn().mockResolvedValue({ members: [] }),
}));

import { CollaborationSheet } from "./CollaborationSheet";

afterEach(cleanup);

function open(subjectType: "board" | "workflow", onJump = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CollaborationSheet
        open
        onOpenChange={vi.fn()}
        workspaceId="workspace-1"
        subjectType={subjectType}
        subjectId="subject-1"
        onJumpToComment={onJump}
      />
    </QueryClientProvider>,
  );
  return onJump;
}

describe("讨论侧栏", () => {
  it("一条流水读下来,不再分「清单 + 详情」两栏", async () => {
    /*
     * 分栏那一版在 500px 的侧栏里摆不下,而它换来的只是"少看两行截断" —— 代价是多点一下、
     * 多一份选中状态,以及空态出现两遍。所以这里所有讨论**同时**是完整的。
     */
    open("board");
    expect(await screen.findByText("第一条意见")).toBeInTheDocument();
    expect(screen.getByText("第二条意见")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("有锚点才给「在画布中查看」,并把那条讨论交出去", async () => {
    const onJump = open("board");
    const jumps = await screen.findAllByRole("button", { name: "在画布中查看" });
    expect(jumps).toHaveLength(1); // 只有带坐标的那条有
    await userEvent.click(jumps[0]);
    expect(onJump).toHaveBeenCalledWith(expect.objectContaining({ id: "comment-1" }));
  });

  it("对 subject 不挑食 —— 工作流按 workflow 去问同一个接口", async () => {
    // 画板和工作流在后端只是换了个 subject_type;这条钉住"两个页面共用同一份组件"。
    listComments.mockClear();
    open("workflow");
    expect(await screen.findByText("第一条意见")).toBeInTheDocument();
    expect(listComments).toHaveBeenCalledWith("workspace-1", "workflow", "subject-1");
  });

  it("两个画布页面用的是同一份 —— 不许各自再长一个讨论中心", () => {
    /*
     * 无限画布和工作流是同一种东西的两块画布:一样的评论钉、一样的 @ 提及、一样的跳回原位。
     * 此前只有画板有讨论中心,工作流的评论只能在画布上一个个点开找。两边各写一份的话,
     * 下一次改动只会落在其中一边 —— 而"哪一边"取决于当时打开的是哪个文件。
     */
    const read = (name: string) =>
      readFileSync(join(import.meta.dirname, "..", name), "utf8");
    for (const view of ["boards/BoardsView.tsx", "workflows/WorkflowsView.tsx"]) {
      expect(read(view), `${view} 该用共用的讨论侧栏`).toContain(
        'from "@/features/collaboration/CollaborationSheet"',
      );
    }
  });

  it("空态只写一次,并且撑满内容区居中", async () => {
    // 贴在顶上的话,底下会空出一屏找不到边的灰 —— 看着像是列表还没加载完。
    // jsdom 不做排版,所以这里钉的是那两条把它撑满并居中的类。
    listComments.mockResolvedValueOnce([]);
    open("board");
    expect(await screen.findAllByText("还没有评论")).toHaveLength(1);
    const empty = document.querySelector("[data-collaboration-empty]");
    expect(empty?.className).toContain("h-full");
    expect(empty?.className).toContain("place-content-center");
  });
});
