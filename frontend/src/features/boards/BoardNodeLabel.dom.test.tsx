/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BoardItem } from "@/api/client";

vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  NodeResizer: () => null,
  Position: { Left: "left", Right: "right" },
  useStore: (selector: (state: { transform: [number, number, number] }) => unknown) =>
    selector({ transform: [0, 0, 1] }),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      boardKindNote: "便签",
      boardKindImage: "图片",
      boardKindVideo: "视频",
      boardKindAudio: "音频",
      boardKindFrame: "分组",
      boardKindDocument: "文档",
      rename: "重命名",
      boardRenameHint: "双击重命名",
    })[key] ?? key,
}));
vi.mock("@/components/app/asset-preview", () => ({ AssetInlinePreview: () => null }));
vi.mock("@/features/boards/BoardPlayer", () => ({ BoardAudio: () => null, BoardVideo: () => null }));

import { BOARD_NODE_TYPES, type BoardNodeData } from "./boardNodes";
import { BOARD_ITEM_TITLE_MAX, cleanTitle } from "./BoardNodeLabel";

afterEach(cleanup);

/**
 * 一格节点 + 画布替它管着的两样:这一格叫什么、是不是正在改名。改名落下时记一笔,
 * 于是测得出「落了几次、落的是什么」—— 一次改名只该落一次。
 */
function mount(item: Partial<BoardItem> & Pick<BoardItem, "kind">, options: { commentMode?: boolean } = {}) {
  const commits: string[] = [];
  const onText = vi.fn();
  let setOutside: (next: Partial<BoardItem>) => void = () => undefined;
  function Harness() {
    const [current, setCurrent] = React.useState<BoardItem>({ id: "n1", x: 0, y: 0, ...item });
    const [renaming, setRenaming] = React.useState(false);
    setOutside = (next) => setCurrent((one) => ({ ...one, ...next }));
    const Node = BOARD_NODE_TYPES[current.kind];
    const data: BoardNodeData = {
      item: current,
      onText,
      onAspect: vi.fn(),
      commentMode: options.commentMode,
      renaming,
      onRenaming: (id) => setRenaming(id === current.id),
      onRename: (_id, title) => {
        commits.push(title);
        setCurrent(({ title: _old, ...rest }) => (title ? { ...rest, title } : rest));
      },
    };
    return <Node {...({ id: current.id, data, selected: false } as unknown as React.ComponentProps<typeof Node>)} />;
  }
  const view = render(<Harness />);
  const label = () => view.container.querySelector<HTMLElement>("[data-board-node-label]")!;
  const input = () => screen.queryByLabelText<HTMLInputElement>("重命名");
  const startRenaming = () => {
    const name = label().querySelector("span")!;
    fireEvent.doubleClick(name);
  };
  return { ...view, commits, onText, label, input, startRenaming, setOutside: (next: Partial<BoardItem>) => act(() => setOutside(next)) };
}

describe("节点上方的名字", () => {
  it.each([
    ["image", "图片"],
    ["video", "视频"],
    ["audio", "音频"],
    ["note", "便签"],
    ["frame", "分组"],
  ] as const)("%s 没起名时显示种类名,起了名显示名字", (kind, fallback) => {
    const unnamed = mount({ kind });
    expect(unnamed.label().textContent).toBe(fallback);
    unnamed.unmount();

    const named = mount({ kind, title: "主视觉" });
    expect(named.label().textContent).toBe("主视觉");
  });

  it("分组框的名字读 title,不读 text", () => {
    const view = mount({ kind: "frame", title: "第一幕" });
    expect(view.label().textContent).toBe("第一幕");
  });
});

describe("双击名字就地改名", () => {
  it("Enter 落下,只落一次;输入框关掉,名字换上", () => {
    const view = mount({ kind: "image" });
    view.startRenaming();
    const input = view.input()!;
    expect(input).not.toBeNull();
    expect(input.value).toBe("");
    expect(input.placeholder).toBe("图片");
    expect(input.maxLength).toBe(BOARD_ITEM_TITLE_MAX);

    fireEvent.change(input, { target: { value: "  猫的\t正面  " } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(view.commits).toEqual(["猫的 正面"]);
    expect(view.input()).toBeNull();
    expect(view.label().textContent).toBe("猫的 正面");
    // 输入框卸掉之后浏览器可能补一个 blur —— 不能再落第二次。
    fireEvent.blur(input);
    expect(view.commits).toEqual(["猫的 正面"]);
  });

  it("Esc 放弃,名字原样", () => {
    const view = mount({ kind: "video", title: "开场" });
    view.startRenaming();
    fireEvent.change(view.input()!, { target: { value: "改了一半" } });
    fireEvent.keyDown(view.input()!, { key: "Escape" });
    expect(view.commits).toEqual([]);
    expect(view.input()).toBeNull();
    expect(view.label().textContent).toBe("开场");
  });

  it("失焦落下", () => {
    const view = mount({ kind: "audio" });
    view.startRenaming();
    fireEvent.change(view.input()!, { target: { value: "旁白" } });
    fireEvent.blur(view.input()!);
    expect(view.commits).toEqual(["旁白"]);
    expect(view.label().textContent).toBe("旁白");
  });

  it("清空名字 = 不要名字了,退回种类名", () => {
    const view = mount({ kind: "frame", title: "第一幕" });
    view.startRenaming();
    fireEvent.change(view.input()!, { target: { value: "   " } });
    fireEvent.keyDown(view.input()!, { key: "Enter" });
    expect(view.commits).toEqual([""]);
    expect(view.label().textContent).toBe("分组");
  });

  it("没改动就不落 —— 不给撤销历史多记一步", () => {
    const view = mount({ kind: "image", title: "主视觉" });
    view.startRenaming();
    fireEvent.keyDown(view.input()!, { key: "Enter" });
    expect(view.commits).toEqual([]);
  });

  it("输入法选词时的 Enter / Esc 不算数", () => {
    const view = mount({ kind: "image" });
    view.startRenaming();
    const input = view.input()!;
    fireEvent.change(input, { target: { value: "mao" } });
    // 拼音上屏那一下 Enter、撤掉候选词那一下 Esc:都还在选词。
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Escape", isComposing: true });
    // Safari:compositionend 之后那一下 isComposing 已经是 false,只剩 keyCode 229。
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(view.commits).toEqual([]);
    expect(view.input()).not.toBeNull();

    fireEvent.change(input, { target: { value: "猫" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(view.commits).toEqual(["猫"]);
  });

  it("改到一半外面重绘了(自动保存、别处改了名字):正在打的字不被盖回去", () => {
    const view = mount({ kind: "image", title: "旧名字" });
    view.startRenaming();
    fireEvent.change(view.input()!, { target: { value: "新名" } });
    view.setOutside({ title: "别处改的", x: 40 });
    expect(view.input()!.value).toBe("新名");
    fireEvent.keyDown(view.input()!, { key: "Enter" });
    expect(view.commits).toEqual(["新名"]);
  });

  it("便签上双击名字是改名,不是写正文", () => {
    const view = mount({ kind: "note", text: "正文" });
    view.startRenaming();
    expect(view.input()).not.toBeNull();
    expect(view.container.querySelector("textarea")).toBeNull();
  });

  it("评论模式下只看不改", () => {
    const view = mount({ kind: "image", title: "主视觉" }, { commentMode: true });
    view.startRenaming();
    expect(view.input()).toBeNull();
    expect(view.label().className).toContain("pointer-events-none");
  });
});

describe("名字的口径", () => {
  it("和后端 _normalize_title 一样:空白收成单个空格、首尾去掉", () => {
    expect(cleanTitle("  a \n b\t c ")).toBe("a b c");
    expect(cleanTitle("   ")).toBe("");
  });
});
