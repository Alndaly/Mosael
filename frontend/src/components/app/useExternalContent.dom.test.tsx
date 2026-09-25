/** @vitest-environment jsdom */
//: 四个可编辑的 TipTap 编辑器从外面接内容:输入法组词期间一律不回灌(回灌就打断组词、
//: 拼音字母上屏),组词结束后外面那份真的不一样才换上。
import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import type { Editor } from "@tiptap/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import { ChatComposer } from "@/features/agent/ChatComposer";
import { PromptEditor } from "@/features/boards/PromptEditor";
import { NoteEditor } from "@/features/notes/NoteEditor";
import { RefEditor } from "@/features/workflows/RefEditor";
import { parseSourceAssetText, sourceAssetText } from "@/features/workflows/sourceAssetLines";
import { COMPOSE_SETTLE_MS } from "./useExternalContent";

beforeAll(() => {
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(cleanup);

const doc = (text: string) => ({ type: "doc", content: [{ type: "paragraph", content: text ? [{ type: "text", text }] : [] }] });

/** 每个编辑器:给一份字,渲染出来。 */
const EDITORS: Record<string, (text: string) => React.ReactElement> = {
  RefEditor: (text) => <RefEditor value={text} onChange={() => undefined} variables={[]} />,
  PromptEditor: (text) => (
    <PromptEditor value={text} onChange={() => undefined} placeholder="" candidates={() => []} onSubmit={() => undefined} emptyHint={() => ""} />
  ),
  ChatComposer: (text) => <ChatComposer workspaceId="w1" value={doc(text)} onChange={() => undefined} onSubmit={() => undefined} search={async () => []} />,
  NoteEditor: (text) => <NoteEditor markdown={text} onChange={() => undefined} onReference={() => undefined} workspaceId="w1" noteId="n1" />,
};

async function editorOf(container: HTMLElement): Promise<Editor> {
  return waitFor(() => {
    const dom = container.querySelector(".ProseMirror") as (HTMLElement & { editor?: Editor }) | null;
    expect(dom?.editor).toBeTruthy();
    return dom!.editor!;
  });
}

describe.each(Object.keys(EDITORS))("%s:组词期间不从外面回灌", (name) => {
  it("组词中外面换了一份:先不动;组词结束后才换上", async () => {
    const make = EDITORS[name]!;
    const view = render(make("原来的"));
    const editor = await editorOf(view.container);
    expect(editor.getText()).toBe("原来的");

    act(() => {
      editor.view.dom.dispatchEvent(new CompositionEvent("compositionstart", { data: "", bubbles: true }));
    });
    expect(editor.view.composing).toBe(true);
    view.rerender(make("外面改的"));
    expect(editor.getText()).toBe("原来的");

    act(() => {
      editor.view.dom.dispatchEvent(new CompositionEvent("compositionend", { data: "", bubbles: true }));
    });
    await waitFor(() => expect(editor.getText()).toBe("外面改的"), { timeout: COMPOSE_SETTLE_MS * 10 });
  });
});

describe("RefEditor:外面那份只是自己发出去那版的规整写法", () => {
  it("不回灌 —— 打的空格、刚回车出来的空行留着", async () => {
    const normalize = (text: string) => sourceAssetText(parseSourceAssetText(text));
    function Field() {
      const [stored, setStored] = React.useState("a:first_frame");
      return <RefEditor value={stored} normalize={normalize} onChange={(next) => setStored(normalize(next))} variables={[]} />;
    }
    const view = render(<Field />);
    const editor = await editorOf(view.container);
    act(() => {
      editor.commands.focus("end");
      editor.commands.splitBlock();
      editor.commands.insertContent("b ");
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, COMPOSE_SETTLE_MS));
    });
    //: 存下去的是规整过的 "a:first_frame\nb",但编辑器里第二行后面那个空格得在 —— 用户正要接着写角色。
    expect(editor.state.doc.child(1).textContent).toBe("b ");
  });
});
