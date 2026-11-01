/** @vitest-environment jsdom */
import { Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImeComposition } from "./imeComposition";
import { COMPOSE_SETTLE_MS } from "./useExternalContent";

/**
 * 两条规矩各钉一次(真实浏览器里的复现与对照见 imeComposition.ts 的说明):
 * 组词中的空事务不派发;组词里最后一个改了文档的事务在组词结束后重放成一次 update。
 */

function editorWith() {
  const editor = new Editor({ element: document.createElement("div"), extensions: [StarterKit, ImeComposition] });
  const setComposing = (value: boolean) => {
    (editor.view as unknown as { input: { composing: boolean } }).input.composing = value;
  };
  const transactions: unknown[] = [];
  editor.on("transaction", ({ transaction }) => transactions.push(transaction));
  return { editor, setComposing, transactions };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("ImeComposition", () => {
  it("组词中 Tiptap 派发的空事务被丢掉,组词外照常", () => {
    const { editor, setComposing, transactions } = editorWith();

    setComposing(true);
    editor.view.dispatch(editor.state.tr);
    expect(transactions).toHaveLength(0);

    setComposing(false);
    editor.view.dispatch(editor.state.tr);
    expect(transactions).toHaveLength(1);
    editor.destroy();
  });

  it("组词中带 meta、改文档的事务都照常派发", () => {
    const { editor, setComposing, transactions } = editorWith();
    setComposing(true);

    editor.view.dispatch(editor.state.tr.setMeta("plugin", true));
    editor.view.dispatch(editor.state.tr.insertText("ni"));

    expect(transactions).toHaveLength(2);
    expect(editor.getText()).toBe("ni");
    editor.destroy();
  });

  it("组词结束后把组词里最后的改动重放成一次 update,父层拿到最终的字", () => {
    vi.useFakeTimers();
    const { editor, setComposing } = editorWith();
    const updates: string[] = [];
    editor.on("update", ({ editor: instance }) => {
      if (!instance.view.composing) updates.push(instance.getText());
    });

    setComposing(true);
    editor.view.dispatch(editor.state.tr.insertText("你好"));
    expect(updates).toEqual([]);

    setComposing(false);
    editor.view.dom.dispatchEvent(new Event("compositionend"));
    vi.advanceTimersByTime(COMPOSE_SETTLE_MS);

    expect(updates).toEqual(["你好"]);
    editor.destroy();
  });

  it("组词结束后已有正常 update 的,不再补发", () => {
    vi.useFakeTimers();
    const { editor, setComposing } = editorWith();
    const updates: string[] = [];
    editor.on("update", ({ editor: instance }) => updates.push(instance.getText()));

    setComposing(true);
    editor.view.dispatch(editor.state.tr.insertText("你"));
    setComposing(false);
    editor.view.dom.dispatchEvent(new Event("compositionend"));
    editor.view.dispatch(editor.state.tr.insertText("好"));
    vi.advanceTimersByTime(COMPOSE_SETTLE_MS);

    expect(updates).toEqual(["你", "你好"]);
    editor.destroy();
  });
});
