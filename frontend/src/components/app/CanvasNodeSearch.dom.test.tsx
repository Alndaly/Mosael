/** @vitest-environment jsdom */
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

const zh = messages["zh-CN"];
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: MessageKey) => zh[key] }));

import {
  CanvasNodeSearch,
  matchCanvasEntries,
  searchHighlightClass,
  stepCanvasMatch,
  type CanvasSearchEntry,
  type CanvasSearchHighlight,
} from "./CanvasNodeSearch";
import { EdgeShapeToggle, shapeEdges, useEdgeShape } from "./canvasEdgeShape";

const entries: CanvasSearchEntry[] = [
  { id: "n1", title: "开场白", subtitle: "便签", text: ["开场白:先讲痛点", "note"] },
  { id: "i1", title: "一只橘猫", subtitle: "图片", text: ["一只橘猫趴在窗台", "image"] },
  { id: "n2", title: "结尾", subtitle: "便签", text: ["结尾回到猫", "note"] },
  { id: "v1", title: "视频", subtitle: "视频", text: ["video"] },
];

describe("匹配与游标", () => {
  it("按标题、类型、正文里的字匹配,不分大小写", () => {
    expect(matchCanvasEntries(entries, "猫").map((one) => one.id)).toEqual(["i1", "n2"]);
    expect(matchCanvasEntries(entries, "NOTE").map((one) => one.id)).toEqual(["n1", "n2"]);
    expect(matchCanvasEntries(entries, "图片").map((one) => one.id)).toEqual(["i1"]);
    expect(matchCanvasEntries(entries, "  ")).toHaveLength(4);
  });

  it("下一个 / 上一个到头绕回;还没跳过时往后从第一个、往前从最后一个开始", () => {
    expect(stepCanvasMatch(null, 3, 1)).toBe(0);
    expect(stepCanvasMatch(null, 3, -1)).toBe(2);
    expect(stepCanvasMatch(2, 3, 1)).toBe(0);
    expect(stepCanvasMatch(0, 3, -1)).toBe(2);
    expect(stepCanvasMatch(5, 3, 1)).toBe(0);
    expect(stepCanvasMatch(0, 0, 1)).toBeNull();
  });

  it("命中的画半透明圈,当前那个画实线圈,没命中的不画", () => {
    const hit: CanvasSearchHighlight = { ids: new Set(["a", "b"]), activeId: "b" };
    expect(searchHighlightClass(hit, "a")).toContain("outline-primary/45");
    expect(searchHighlightClass(hit, "b")).toMatch(/outline-primary(\s|$)/);
    expect(searchHighlightClass(hit, "c")).toBeUndefined();
    expect(searchHighlightClass(null, "a")).toBeUndefined();
  });
});

function mount(props: Partial<React.ComponentProps<typeof CanvasNodeSearch>> = {}) {
  const onFocus = vi.fn();
  const onHighlight = vi.fn();
  const view = render(
    <div>
      <textarea aria-label="便签正文" />
      <CanvasNodeSearch entries={entries} onFocus={onFocus} onHighlight={onHighlight} {...props} />
    </div>,
  );
  const input = () => screen.getByRole("textbox", { name: zh.wfNodeSearch });
  const lastHighlight = () => onHighlight.mock.calls.at(-1)?.[0] as CanvasSearchHighlight | null;
  return { ...view, onFocus, onHighlight, input, lastHighlight };
}

async function pressFind(target: Window | Element = window) {
  await act(async () => {
    fireEvent.keyDown(target, { key: "f", metaKey: true });
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  });
}

describe("查找节点", () => {
  it("⌘F 打开;边打字边把命中的交给画布去圈", async () => {
    const { input, lastHighlight } = mount();
    expect(screen.queryByRole("textbox", { name: zh.wfNodeSearch })).toBeNull();
    await pressFind();
    expect(input()).toHaveFocus();
    // 空查询不圈 —— 什么都没搜时整块画布一圈一圈的只是噪音。
    expect(lastHighlight()).toBeNull();

    fireEvent.change(input(), { target: { value: "猫" } });
    expect([...(lastHighlight()?.ids ?? [])]).toEqual(["i1", "n2"]);
    expect(lastHighlight()?.activeId).toBeNull();
    expect(screen.getByText("0/2")).toBeInTheDocument();
  });

  it("Enter 下一个、⇧Enter 上一个,到头绕回;每一步都让画布跳过去", async () => {
    const { input, onFocus, lastHighlight } = mount();
    await pressFind();
    fireEvent.change(input(), { target: { value: "猫" } });

    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onFocus).toHaveBeenLastCalledWith("i1");
    expect(lastHighlight()?.activeId).toBe("i1");
    expect(screen.getByText("1/2")).toBeInTheDocument();

    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onFocus).toHaveBeenLastCalledWith("n2");
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onFocus).toHaveBeenLastCalledWith("i1");

    fireEvent.keyDown(input(), { key: "Enter", shiftKey: true });
    expect(onFocus).toHaveBeenLastCalledWith("n2");
    expect(screen.getByText("2/2")).toBeInTheDocument();
    // 列表里当前那一行也标出来。
    expect(screen.getByRole("button", { name: /结尾/ })).toHaveAttribute("aria-current", "true");
  });

  it("输入法组词时的 Enter 是上屏,不跳", async () => {
    const { input, onFocus } = mount();
    await pressFind();
    fireEvent.change(input(), { target: { value: "mao" } });
    fireEvent.keyDown(input(), { key: "Enter", isComposing: true });
    expect(onFocus).not.toHaveBeenCalled();
  });

  it("Esc 关掉,并把画布上的圈摘掉", async () => {
    const { input, lastHighlight } = mount();
    await pressFind();
    fireEvent.change(input(), { target: { value: "猫" } });
    expect(lastHighlight()).not.toBeNull();

    fireEvent.keyDown(input(), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: zh.wfNodeSearch })).toBeNull();
    expect(lastHighlight()).toBeNull();

    // 再打开是一次新的查找,不带着上次的词。
    await pressFind();
    expect(input()).toHaveValue("");
  });

  it("点列表里的一行:跳过去并收起", async () => {
    const { input, onFocus } = mount();
    await pressFind();
    fireEvent.change(input(), { target: { value: "结尾" } });
    fireEvent.click(screen.getByRole("button", { name: /结尾/ }));
    expect(onFocus).toHaveBeenCalledWith("n2");
    expect(screen.queryByRole("textbox", { name: zh.wfNodeSearch })).toBeNull();
  });

  it("焦点在能打字的地方时 ⌘F 不劫持", async () => {
    mount();
    const note = screen.getByRole("textbox", { name: "便签正文" });
    note.focus();
    await pressFind(note);
    expect(screen.queryByRole("textbox", { name: zh.wfNodeSearch })).toBeNull();
  });

  it("工具条上的按钮也能打开,标题里写着快捷键", () => {
    mount();
    const trigger = screen.getByRole("button", { name: zh.wfNodeSearch });
    expect(trigger.getAttribute("title")).toContain("⌘F");
    fireEvent.click(trigger);
    expect(screen.getByRole("textbox", { name: zh.wfNodeSearch })).toBeInTheDocument();
  });
});

describe("连线走线方式", () => {
  function Harness({ storageKey }: { storageKey: string }) {
    const [shape, setShape] = useEdgeShape(storageKey);
    return (
      <>
        <EdgeShapeToggle value={shape} onChange={setShape} />
        <output>{shape}</output>
      </>
    );
  }

  it("按下哪颗就是哪种;记在本地偏好里,重进还是它", () => {
    localStorage.clear();
    const first = render(<Harness storageKey="board-edge-shape" />);
    expect(screen.getByRole("button", { name: zh.wfEdgeBezier })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: zh.wfEdgeSmoothStep }));
    expect(screen.getByRole("button", { name: zh.wfEdgeSmoothStep })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent("smoothstep");
    first.unmount();

    render(<Harness storageKey="board-edge-shape" />);
    expect(screen.getByRole("button", { name: zh.wfEdgeSmoothStep })).toHaveAttribute("aria-pressed", "true");
  });

  it("工作流和画板各记各的", () => {
    localStorage.clear();
    const board = render(<Harness storageKey="board-edge-shape" />);
    fireEvent.click(screen.getByRole("button", { name: zh.wfEdgeSmoothStep }));
    board.unmount();
    render(<Harness storageKey="wf-edge-shape" />);
    expect(screen.getByRole("button", { name: zh.wfEdgeBezier })).toHaveAttribute("aria-pressed", "true");
  });

  it("写到每一条边上;已经是这种的原样返回,不换引用", () => {
    const same = { id: "a", type: "smoothstep" };
    const other: { id: string; type?: string } = { id: "b" };
    const shaped = shapeEdges([same, other], "smoothstep");
    expect(shaped[0]).toBe(same);
    expect(shaped[1]).toEqual({ id: "b", type: "smoothstep" });
  });
});
