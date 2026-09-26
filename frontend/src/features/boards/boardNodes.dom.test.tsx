/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";

vi.mock("@xyflow/react", () => ({
  Handle: ({ children, isConnectable, className }: { children?: React.ReactNode; isConnectable?: boolean; className?: string }) => <div data-testid="connection-handle" data-connectable={isConnectable} className={className}>{children}</div>,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right" },
  useStore: (selector: (state: { transform: [number, number, number] }) => unknown) =>
    selector({ transform: [0, 0, 1] }),
}));
vi.mock("@/app/preferences", () => ({
  usePreferences: () => ({ locale: "zh" }),
  useI18n: () => (key: string) =>
    ({
      boardNodeQueued: "等待执行",
      boardNodeRunning: "生成中",
      generating: "生成中",
      boardNodeSucceeded: "已完成",
      boardNodeFailed: "失败",
      boardNodeCancelled: "已取消",
      boardNodeGenerateFailed: "生成失败",
      boardNodeRunFailed: "运行失败",
      boardToolRunning: "正在运行",
      boardToolStop: "停止",
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
  queued: "border-primary/45",
  running: "border-primary/70",
  succeeded: "ring-0",
  failed: "border-destructive/75",
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

function renderNode(
  kind: BoardItem["kind"],
  status: NonNullable<BoardItem["run"]>["status"],
  extra: Partial<BoardItem> = {},
  commentMode = false,
  onStop?: (id: string) => void,
) {
  const Node = BOARD_NODE_TYPES[kind];
  const item: BoardItem = {
    id: `${kind}-${status}`,
    kind,
    x: 0,
    y: 0,
    text: "测试节点",
    asset_id: status === "succeeded" && ["image", "video", "audio"].includes(kind) ? "asset-1" : undefined,
    ...extra,
    run: extra.run ?? {
        status,
        job_id: status === "queued" || status === "running" ? "job-1" : undefined,
        error: status === "failed" ? "上游拒绝了请求" : undefined,
      },
  };
  const props = {
    id: item.id,
    data: { item, onText: vi.fn(), onAspect: vi.fn(), commentMode, onStop },
    selected: false,
  } as unknown as React.ComponentProps<typeof Node>;
  //: 在跑的格子按任务查进度(和工具格同一份),要一个 QueryClient。
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Node {...props} />
    </QueryClientProvider>,
  );
}

describe("无限画布节点运行状态", () => {
  it.each(KINDS)("评论模式下 %s 节点不提供连线入口", (kind) => {
    const { queryAllByTestId } = renderNode(kind, "idle", {}, true);
    const handles = queryAllByTestId("connection-handle");
    expect(handles).toHaveLength(kind === "frame" ? 0 : 2);
    for (const handle of handles) {
      expect(handle).toHaveAttribute("data-connectable", "false");
      expect(handle).toHaveClass("!opacity-0", "!pointer-events-none");
    }
  });

  it.each(KINDS)("%s 节点的六种状态都有自己的节点级样式;成功不留彩色描边", (kind) => {
    for (const status of STATUSES) {
      const { container, unmount } = renderNode(kind, status);
      const node = container.querySelector<HTMLElement>("[data-board-run-status]");
      expect(node?.dataset.boardRunStatus).toBe(status);
      expect(node?.className).toContain(STATUS_CLASS[status]);
      if (status === "succeeded") expect(node?.className).not.toMatch(/ring-success|border-success/);
      //: 状态只画在自己的边框上:外环、外发光会溢出格子,压到旁边的格子和连线上(用户截图里在跑那一格的光晕)。
      expect(node?.className, `${kind} ${status}`).not.toMatch(/\bring-[1-8]\b|shadow-\[0_0_/);
      unmount();
    }
  });

  it("所有内容格一个外壳圆角;贴着内沿的那层按它减掉 1px 边框,两条弧同心", () => {
    //: 此前图片 / 视频 / 音频格外壳 rounded-lg、便签 / 场景 rounded-xl,里面一律 rounded-lg —— 角上露一道暗缝。
    for (const kind of ["note", "image", "video", "audio"] as const) {
      const { container, unmount } = renderNode(kind, "running", { form: { producer: kind === "note" ? "write" : "generate", prompt: "猫" } });
      const shell = container.querySelector<HTMLElement>("[data-board-run-status]") ?? container.querySelector<HTMLElement>(".group");
      expect(shell?.className, kind).toContain("rounded-xl");
      expect(shell?.className, kind).not.toContain("rounded-lg");
      if (kind !== "note") {
        const status = container.querySelector<HTMLElement>('[role="status"]')!;
        expect(status.className, kind).toContain("rounded-[calc(var(--radius-xl)-1px)]");
        //: 生成中的占位贴满格子:外面那层不给它留白(音频格此前带着给播放器的 px-2,占位两边各缩进一截)。
        expect(status.parentElement?.className ?? "", kind).not.toMatch(/\bp[xy]?-\d/);
      }
      unmount();
    }
  });

  it("刚在眼前跑成功的那一格闪一下,然后安静下来;打开时本来就成功着的不闪", () => {
    vi.useFakeTimers();
    try {
      const Node = BOARD_NODE_TYPES.image;
      const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } });
      const view = (run: BoardItem["run"], asset_id?: string) => (
        <QueryClientProvider client={client}>
          <Node {...({ id: "i", data: { item: { id: "i", kind: "image", x: 0, y: 0, asset_id, run }, onText: vi.fn(), onAspect: vi.fn() }, selected: false } as unknown as React.ComponentProps<typeof Node>)} />
        </QueryClientProvider>
      );
      const node = () => document.querySelector<HTMLElement>("[data-board-run-status]")!;
      const { rerender } = render(view({ status: "running", job_id: "j" }));
      rerender(view({ status: "succeeded" }, "a1"));
      expect(node().className).toContain("border-success/60");
      act(() => void vi.advanceTimersByTime(2000));
      expect(node().className).not.toContain("border-success");
      cleanup();
      render(view({ status: "succeeded" }, "a1"));
      expect(node().className).not.toContain("border-success");
    } finally {
      vi.useRealTimers();
    }
  });

  it.each(["image", "video", "audio"] as const)("%s 在跑:外壳上有停止,点了交给上层取消那一轮", (kind) => {
    const onStop = vi.fn();
    const { container } = renderNode(kind, "running", { form: { producer: "generate", prompt: "猫" } }, false, onStop);
    fireEvent.click(container.querySelector<HTMLElement>("[data-board-stop]")!);
    expect(onStop).toHaveBeenCalledWith(`${kind}-running`);
    cleanup();
    //: 排队中也停得下;评论模式、没在跑的不给。
    expect(renderNode(kind, "queued", {}, false, onStop).container.querySelector("[data-board-stop]")).not.toBeNull();
    cleanup();
    expect(renderNode(kind, "running", {}, true, onStop).container.querySelector("[data-board-stop]")).toBeNull();
    cleanup();
    expect(renderNode(kind, "failed", {}, false, onStop).container.querySelector("[data-board-stop]")).toBeNull();
  });

  it("失败按产出者说:生成挂了是「生成失败」,截一段挂了是「运行失败」—— 不是「没能发起生成」", () => {
    const { getByRole } = renderNode("image", "failed", { form: { producer: "generate" } });
    expect(getByRole("alert")).toHaveTextContent("生成失败");
    cleanup();
    const trimmed = renderNode("video", "failed", { form: { producer: "trim" } });
    expect(trimmed.getByRole("alert")).toHaveTextContent("运行失败");
    expect(trimmed.getByRole("alert")).toHaveTextContent("上游拒绝了请求");
  });


  it.each(Object.entries(STATUS_LABEL))("%s 状态不再重复显示在节点右上角", (status, label) => {
    const { queryByLabelText } = renderNode("image", status as keyof typeof STATUS_LABEL);
    expect(queryByLabelText(label)).toBeNull();
  });

  it("取消不是空槽，而是明确的终态", () => {
    const { getAllByText, queryByText } = renderNode("video", "cancelled");
    expect(getAllByText("已取消")).toHaveLength(1);
    expect(queryByText("生成中")).toBeNull();
  });

  it.each(["image", "video", "audio"] as const)("%s 生成中:整张卡是扫光占位,状态落成字,不是正中一个转圈", (kind) => {
    const { getByRole, container } = renderNode(kind, "running", { form: { prompt: "a beautiful girl" } });
    const status = getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent("生成中");
    expect(status).toHaveTextContent("a beautiful girl");
    //: 扫光来自共用的 <Skeleton>,铺满这一格;调用处不再挂 animate-none 把它关掉。
    const skeleton = status.querySelector<HTMLElement>("[data-slot='skeleton']");
    expect(skeleton).not.toBeNull();
    expect(skeleton).toHaveClass("skeleton", "absolute", "inset-0");
    expect(skeleton!.className).not.toMatch(/\banimate-/);
    expect(container.querySelector(".animate-spin, .animate-mosael-spin")).toBeNull();
  });

  it("排队中不扫光 —— 它在等,不是在动", () => {
    const { container } = renderNode("image", "queued");
    expect(container.querySelector("[data-slot='skeleton']")).toBeNull();
  });

  it.each(["queued", "running", "failed"] as const)("%s 的长 URL 文案限制在节点宽度内", (status) => {
    const copy =
      "ARK-request-failed:https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/abcdefghijklmnopqrstuvwxyz0123456789";
    const extra: Partial<BoardItem> =
      status === "failed"
        ? { run: { status, error: copy } }
        : { form: { prompt: copy }, run: { status, job_id: "job-1" } };
    const { getByText } = renderNode("video", status, extra);
    const text = getByText(copy);
    expect(text.className).toContain("[overflow-wrap:anywhere]");
    expect(text.parentElement?.className).toContain("min-w-0");
  });
});

it("document contents drag the node and suppress native image dragging", () => {
  const Node = BOARD_NODE_TYPES.document;
  const props = { data: { item: { id: "doc", kind: "document", note_id: "note", note_revision: 1 },
    document: { reference: { title: "Reference", markdown: "![test](https://example.com/image.png)", revision: 1 } } }, selected: false } as unknown as React.ComponentProps<typeof Node>;
  const { container } = render(<Node {...props} />);
  const content = container.querySelector("[data-document-preview]")!;
  expect(content.closest(".nodrag")).toBeNull();
  const image = container.querySelector("img")!;
  expect(image).not.toBeNull();
  expect(fireEvent.dragStart(image)).toBe(false);
});

it("文档格和笔记页是同一个渲染器:表格是笔记里那张表,外面不再多套一层框", () => {
  //: 此前是聊天消息那套 Markdown 渲染 —— 段距、字体和笔记页对不上,表格外面还多一层渲染器自己的圆角框。
  const Node = BOARD_NODE_TYPES.document;
  const markdown = "首先,前期可以先避免收费\n\n| xsa | xas |\n| --- | --- |\n| da | da |";
  const props = { data: { item: { id: "doc", kind: "document", note_id: "note", note_revision: 13 },
    document: { reference: { title: "本项目盈利方", markdown, revision: 13 } } }, selected: false } as unknown as React.ComponentProps<typeof Node>;
  const { container } = render(<Node {...props} />);
  const preview = container.querySelector<HTMLElement>("[data-document-preview]")!;
  expect(preview.classList.contains("note-card")).toBe(true);
  const prose = preview.querySelector(".note-prose");
  expect(prose, "用的是笔记页的 .note-prose").not.toBeNull();
  expect(prose!.textContent).toContain("首先,前期可以先避免收费");
  const table = prose!.querySelector("table")!;
  expect(table).not.toBeNull();
  expect([...table.querySelectorAll("th")].map((one) => one.textContent)).toEqual(["xsa", "xas"]);
  expect(preview.querySelector("[data-streamdown]"), "不再是聊天消息那套渲染").toBeNull();
});

it("选中的文档不加彩色描边(和图片、视频、便签同一条);3D 场景悬停时接点显形", () => {
  const Doc = BOARD_NODE_TYPES.document;
  const docProps = { data: { item: { id: "doc", kind: "document" } }, selected: true } as unknown as React.ComponentProps<typeof Doc>;
  const doc = render(<Doc {...docProps} />);
  const box = doc.container.firstElementChild as HTMLElement;
  expect(box.className).not.toMatch(/border-primary|ring-primary/);
  cleanup();
  const Scene = BOARD_NODE_TYPES.scene;
  const sceneProps = { data: { item: { id: "s", kind: "scene", scene_id: "sc" } }, selected: false } as unknown as React.ComponentProps<typeof Scene>;
  const scene = render(<Scene {...sceneProps} />);
  expect((scene.container.firstElementChild as HTMLElement).className.split(/\s+/)).toContain("group");
});
