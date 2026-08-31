/** @vitest-environment jsdom */
import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";

vi.mock("@xyflow/react", () => ({
  Handle: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right" },
  useStore: (selector: (state: { transform: [number, number, number] }) => unknown) =>
    selector({ transform: [0, 0, 1] }),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      boardNodeQueued: "等待执行",
      boardNodeRunning: "生成中",
      boardNodeSucceeded: "已完成",
      boardNodeFailed: "失败",
      boardNodeCancelled: "已取消",
      boardsGenerateFailed: "生成失败",
      boardKindNote: "便签",
      boardKindImage: "图片",
      boardKindVideo: "视频",
      boardKindAudio: "音频",
      boardKindFrame: "分组",
      boardNotePlaceholder: "双击写点什么",
    })[key] ?? key,
}));
vi.mock("@/components/app/asset-preview", () => ({
  AssetInlinePreview: () => <div data-testid="asset-preview" />,
}));
vi.mock("@/features/boards/BoardPlayer", () => ({
  BoardAudio: () => <div data-testid="audio-player" />,
  BoardVideo: () => <div data-testid="video-player" />,
}));

import { BOARD_NODE_TYPES } from "./boardNodes";

const STATUS_LABEL = {
  queued: "等待执行",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
} as const;

const STATUS_CLASS = {
  idle: "ring-0",
  queued: "ring-primary/15",
  running: "ring-primary/25",
  succeeded: "ring-success/20",
  failed: "ring-destructive/25",
  cancelled: "border-dashed",
} as const;

const KINDS: BoardItem["kind"][] = ["note", "image", "video", "audio", "frame"];
const STATUSES: NonNullable<BoardItem["run"]>["status"][] = [
  "idle",
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];

afterEach(cleanup);

function renderNode(kind: BoardItem["kind"], status: NonNullable<BoardItem["run"]>["status"]) {
  const Node = BOARD_NODE_TYPES[kind];
  const item: BoardItem = {
    id: `${kind}-${status}`,
    kind,
    x: 0,
    y: 0,
    text: "测试节点",
    asset_id: status === "succeeded" && ["image", "video", "audio"].includes(kind) ? "asset-1" : undefined,
    run: {
      status,
      job_id: status === "queued" || status === "running" ? "job-1" : undefined,
      error: status === "failed" ? "上游拒绝了请求" : undefined,
    },
  };
  const props = {
    id: item.id,
    data: { item, onText: vi.fn(), onAspect: vi.fn() },
    selected: false,
  } as unknown as React.ComponentProps<typeof Node>;
  return render(<Node {...props} />);
}

describe("无限画布节点运行状态", () => {
  it.each(KINDS)("%s 节点的六种状态都有自己的节点级样式", (kind) => {
    for (const status of STATUSES) {
      const { container, unmount } = renderNode(kind, status);
      const node = container.querySelector<HTMLElement>("[data-board-run-status]");
      expect(node?.dataset.boardRunStatus).toBe(status);
      expect(node?.className).toContain(STATUS_CLASS[status]);
      unmount();
    }
  });

  it.each(Object.entries(STATUS_LABEL))("%s 状态在节点上直接说明当前发生了什么", (status, label) => {
    const { getByLabelText } = renderNode("image", status as keyof typeof STATUS_LABEL);
    expect(getByLabelText(label)).toBeTruthy();
  });

  it("取消不是空槽，而是明确的终态", () => {
    const { getAllByText, queryByText } = renderNode("video", "cancelled");
    expect(getAllByText("已取消")).toHaveLength(2);
    expect(queryByText("生成中")).toBeNull();
  });
});
