/** @vitest-environment jsdom */

/**
 * 插件清单里 `type: "json"` / `type: "code"` 的配置项(ComfyUI 的「API 模板」就是一段 JSON)。
 *
 * 钉住三件事:用的是**全应用那一个代码编辑器**(不是一个多行文本框);JSON 错在哪一行哪一列当场说,
 * 错着的时候存不了;卡片上只放摘要和「编辑」,编辑在弹窗里,保存才发出去。
 */

import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

//: CodeMirror 在 jsdom 里量不了排版。换成一个记下「用哪种语言」的文本框 —— 这里要钉的是**用了它**、
//: 以及值怎么进出,不是 CodeMirror 自己。
vi.mock("@/components/app/code-editor", () => ({
  CodeEditor: ({ value, onChange, language }: { value: string; onChange: (value: string) => void; language: string }) => {
    return <textarea data-testid="code-editor" data-language={language} value={value} onChange={(event) => onChange(event.target.value)} />;
  },
}));

import type { PluginField } from "@/api/client";
import { CodeConfigControl, codeSummary, jsonProblem } from "./CodeConfigField";

const template: PluginField = {
  key: "api_workflow",
  label: "API 模板(可选)",
  type: "json",
  language: "json",
  help: "可用占位符 `{{prompt}}`",
  required: false,
  secret: false,
  options: [],
  default: "",
  multiline: false,
};

describe("jsonProblem", () => {
  it("合法的、空的都没问题", () => {
    expect(jsonProblem('{"a": 1}')).toBeNull();
    expect(jsonProblem("   ")).toBeNull();
  });

  it("说得出第几行第几列", () => {
    const problem = jsonProblem('{\n  "a": 1,\n}');
    expect(problem).not.toBeNull();
    expect(problem!.line).toBeGreaterThanOrEqual(2);
    expect(problem!.column).toBeGreaterThanOrEqual(1);
    expect(problem!.detail).not.toMatch(/position \d+/);
  });
});

describe("codeSummary", () => {
  it("几行、几个不同的占位符", () => {
    expect(codeSummary("")).toEqual({ lines: 0, placeholders: 0 });
    expect(codeSummary('{\n "t": "{{prompt}} {{prompt}}",\n "s": "{{seed}}"\n}')).toEqual({ lines: 4, placeholders: 2 });
  });
});

describe("CodeConfigControl", () => {
  it("卡片上是摘要 + 编辑;弹窗里是代码编辑器,JSON 错着存不了,改对了保存才发出去", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<CodeConfigControl field={template} value="" onSave={onSave} />);
    expect(screen.getByText("pluginCodeEmpty")).toBeTruthy();
    expect(screen.queryByTestId("code-editor")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "pluginCodeEditTitle" }));
    const editor = await screen.findByTestId("code-editor");
    expect(editor.getAttribute("data-language")).toBe("json");
    const save = screen.getByRole("button", { name: "save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(editor, { target: { value: '{\n  "1": {"class_type": "X"},\n}' } });
    expect(screen.getByRole("alert").textContent).toContain("pluginJsonError");
    expect((screen.getByRole("button", { name: "save" }) as HTMLButtonElement).disabled).toBe(true);

    const good = '{\n  "1": {"class_type": "X", "inputs": {"text": "{{prompt}}"}}\n}';
    fireEvent.change(editor, { target: { value: good } });
    expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });
    expect(onSave).toHaveBeenCalledWith(good);
    await waitFor(() => expect(screen.queryByTestId("code-editor")).toBeNull());
  });

  it("后端拒了:原因留在弹窗里,弹窗不关", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("「API 模板」不是合法的 JSON:第 1 行第 2 列"));
    render(<CodeConfigControl field={template} value='{"a": 1}' onSave={onSave} />);
    expect(screen.getByText("pluginCodeFilled")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "pluginCodeEditTitle" }));
    fireEvent.change(await screen.findByTestId("code-editor"), { target: { value: '{"a": 2}' } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });
    expect((await screen.findByRole("alert")).textContent).toContain("第 1 行第 2 列");
    expect(screen.getByTestId("code-editor")).toBeTruthy();
  });

  it("格式化把 JSON 排好;说明里的占位符按行内代码渲染", async () => {
    render(<CodeConfigControl field={template} value='{"a":1}' onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "pluginCodeEditTitle" }));
    fireEvent.click(await screen.findByRole("button", { name: "pluginCodeFormat" }));
    expect((screen.getByTestId("code-editor") as HTMLTextAreaElement).value).toBe('{\n  "a": 1\n}');
    expect(document.querySelector("code")?.textContent).toBe("{{prompt}}");
  });
});
