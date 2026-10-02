/** @vitest-environment jsdom */
import React from "react";
import type { Editor } from "@tiptap/react";
import { act, render, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { messages } from "@/app/messages";
import { RefEditor } from "./RefEditor";
import { RefCatalogContext, type RefCatalog } from "./refCatalog";

/**
 * 混写编辑器(提示词、模板、混写的「值或上游输出」)里的引用标签,和整格引用(RefCombobox)是同一枚:
 * 「节点标题 · 输出显示名 · 子路径」,指不到东西是错误色,悬停看存下去的路径。此前这里摆的是原始路径
 * `report.json.verdict`,同一个面板里两种写法。
 */

const zh = messages["zh-CN"];
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: keyof typeof zh) => zh[key],
  usePreferences: () => ({ locale: "zh-CN" }),
}));

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
});

const NAMES: Record<string, string> = { report: "写运营诊断", save_note: "存成笔记" };
const OUTPUTS: Record<string, Record<string, string>> = { report: { json: "JSON", text: "文本" }, save_note: { note_id: "笔记" } };
const catalog: RefCatalog = {
  look: (path) => {
    const [node, output, ...rest] = path.split(".");
    if (!NAMES[node]) return { parts: path.split("."), problem: { kind: "node", node } };
    if (output !== undefined && !OUTPUTS[node][output]) return { parts: [NAMES[node], output, ...rest], problem: { kind: "output", node: NAMES[node], output } };
    return { parts: [NAMES[node], ...(output === undefined ? [] : [OUTPUTS[node][output]]), ...rest], problem: null };
  },
  fields: () => [],
};
const variables = ["{{report.json}}", "{{report.text}}", "{{save_note.note_id}}"];

function renderEditor(value: string, vars: string[] = variables) {
  return render(
    <RefCatalogContext.Provider value={catalog}>
      <RefEditor value={value} variables={vars} onChange={vi.fn()} />
    </RefCatalogContext.Provider>,
  );
}

const chips = (container: HTMLElement) => [...container.querySelectorAll<HTMLElement>("[data-ref-chip]")];

describe("混写编辑器里的引用标签", () => {
  it("显示成「节点标题 · 输出显示名 · 子路径」,悬停看存下去的路径,不摆双括号", async () => {
    const { container } = renderEditor("> {{report.json.verdict}} 存在 {{save_note.note_id}}");
    await waitFor(() => expect(chips(container).map((chip) => chip.textContent)).toEqual(["写运营诊断 · JSON · verdict", "存成笔记 · 笔记"]));
    expect(chips(container).map((chip) => chip.title)).toEqual(["report.json.verdict", "save_note.note_id"]);
    expect(chips(container).some((chip) => chip.dataset.refProblem)).toBe(false);
    expect(container.textContent).not.toContain("{{");
  });

  it("指不到东西的:错误色,悬停说为什么", async () => {
    const { container } = renderEditor("看 {{reprot.json.title}} 和 {{report.jsno}}");
    await waitFor(() => expect(chips(container)).toHaveLength(2));
    const [node, output] = chips(container);
    expect(node.dataset.refProblem).toBe("node");
    expect(node.title).toBe(zh.wfRefMissingNode.replace("{node}", "reprot"));
    expect(output.dataset.refProblem).toBe("output");
    expect(output.title).toBe(zh.wfRefMissingOutput.replace("{node}", "写运营诊断").replace("{output}", "jsno"));
  });

  it("这一格的上游清单里列着的一定指得到 —— 容器自己的输出读的是体里的节点,这一层的图里没有它们", async () => {
    const { container } = renderEditor("{{tr.translated}} 完", ["{{tr.translated}}"]);
    await waitFor(() => expect(chips(container)).toHaveLength(1));
    expect(chips(container)[0].dataset.refProblem).toBeUndefined();
    expect(chips(container)[0].textContent).toBe("tr · translated");
  });

  it("@ 菜单摆的是同一个名字;照着屏幕上的名字敲也找得到", async () => {
    const { container } = renderEditor("");
    const editor = await waitFor(() => {
      const dom = container.querySelector(".ProseMirror") as (HTMLElement & { editor?: Editor }) | null;
      expect(dom?.editor).toBeTruthy();
      return dom!.editor!;
    });
    act(() => {
      editor.commands.focus("end");
      editor.commands.insertContent("@存成");
    });
    const menu = await waitFor(() => {
      const found = document.querySelector("[data-suggestion-menu]");
      expect(found?.textContent).toBeTruthy();
      return found!;
    });
    expect([...menu.querySelectorAll("button")].map((button) => [button.textContent, button.title])).toEqual([["存成笔记 · 笔记", "save_note.note_id"]]);
  });
});
