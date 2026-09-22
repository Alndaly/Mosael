import { beforeEach, describe, expect, it } from "vitest";

import { selectedClipId, useEditorStore } from "@/stores/editorStore";

/**
 * 「当前那一个选中的片段」是**派生值**,不是第二份状态。
 *
 * store 里此前同时存 `selectedClipId` 和 `selectedClipIds`,恒等式
 * `selectedClipId === selectedClipIds.at(-1) ?? null` 由**每个写入口各自记得**维持。
 * 三个入口当时都写对了,所以两者永远一致 —— 而第四个入口("选中某轨全部片段"、
 * "撤销后恢复选区")只要漏一行,属性面板和时间线就会看到不同的选中态,
 * 没有任何东西会报错。
 *
 * 这几条不是在测 `.at(-1)` 会不会算 —— 是在钉住「**每一条改选区的路都只写那一份列表**」。
 * 所以它们走的是真的 action,而不是直接 setState。
 */
describe("剪辑台的选区", () => {
  beforeEach(() => {
    useEditorStore.getState().selectClips([]);
  });

  it("单选 = 长度为一的列表", () => {
    useEditorStore.getState().selectClip("a");

    const state = useEditorStore.getState();
    expect(state.selectedClipIds).toEqual(["a"]);
    expect(selectedClipId(state)).toBe("a");
  });

  it("取消选中之后没有「那一个」", () => {
    useEditorStore.getState().selectClip("a");
    useEditorStore.getState().selectClip(null);

    const state = useEditorStore.getState();
    expect(state.selectedClipIds).toEqual([]);
    expect(selectedClipId(state)).toBeNull();
  });

  it("加选之后,「那一个」是最后点的 —— 多选按点击顺序累加", () => {
    const store = useEditorStore.getState();
    store.toggleSelectClip("a");
    store.toggleSelectClip("b");

    expect(useEditorStore.getState().selectedClipIds).toEqual(["a", "b"]);
    expect(selectedClipId(useEditorStore.getState())).toBe("b");
  });

  it("取消掉最后点的那个,「那一个」退回前一个", () => {
    const store = useEditorStore.getState();
    store.toggleSelectClip("a");
    store.toggleSelectClip("b");
    store.toggleSelectClip("b");

    expect(useEditorStore.getState().selectedClipIds).toEqual(["a"]);
    expect(selectedClipId(useEditorStore.getState())).toBe("a");
  });

  it("框选一批之后,「那一个」是这批里的最后一个", () => {
    useEditorStore.getState().selectClips(["a", "b", "c"]);

    expect(selectedClipId(useEditorStore.getState())).toBe("c");
  });

  it("store 里没有第二份选区状态 —— 这条一红就说明它又被存回去了", () => {
    useEditorStore.getState().selectClips(["a", "b"]);

    expect(Object.keys(useEditorStore.getState())).not.toContain("selectedClipId");
  });
});
