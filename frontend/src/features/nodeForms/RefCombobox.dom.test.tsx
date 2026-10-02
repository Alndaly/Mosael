/** @vitest-environment jsdom */
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { messages } from "@/app/messages";
import { RefCombobox } from "./RefCombobox";
import { RefCatalogContext, type RefCatalog } from "./refCatalog";

const zh = messages["zh-CN"];
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: keyof typeof zh) => zh[key],
  usePreferences: () => ({ locale: "zh-CN" }),
}));

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

/** 宿主给的引用目录:节点叫什么、输出叫什么、哪个输出底下有哪些字段(工作流里由图和注册表算,见 workflowRefCatalog)。 */
const NAMES: Record<string, string> = { report: "写运营诊断", save_note: "存成笔记", web: "抓网页" };
const OUTPUTS: Record<string, Record<string, string>> = {
  report: { json: "JSON", text: "文本" },
  save_note: { note_id: "笔记" },
  web: { json: "JSON" },
};
const catalog: RefCatalog = {
  look: (path) => {
    const [node, output, ...rest] = path.split(".");
    if (!NAMES[node]) return { parts: path.split("."), problem: { kind: "node", node } };
    if (output !== undefined && !OUTPUTS[node][output]) return { parts: [NAMES[node], output, ...rest], problem: { kind: "output", node: NAMES[node], output } };
    return { parts: [NAMES[node], ...(output === undefined ? [] : [OUTPUTS[node][output]]), ...rest], problem: null };
  },
  fields: (path) => (path === "report.json" ? ["title", "verdict", "report_markdown"] : []),
};

const variables = ["{{report.json}}", "{{report.text}}", "{{save_note.note_id}}", "{{web.json}}"];

function renderField(value: string, extra: Partial<React.ComponentProps<typeof RefCombobox>> = {}) {
  const onValueChange = vi.fn();
  const view = render(
    <RefCatalogContext.Provider value={catalog}>
      <RefCombobox value={value} variables={variables} onValueChange={onValueChange} {...extra} />
    </RefCatalogContext.Provider>,
  );
  return { onValueChange, ...view };
}

describe("整格一个引用", () => {
  it("显示成「节点 · 输出 · 子路径」的引用标签,不摆双括号 —— 指向上游输出里某个字段的也一样", () => {
    //: 此前只有恰好在清单里的(`{{save_note.note_id}}`)显示得干净,`{{report.json.verdict}}` 不在清单里,
    //: 退回原样显示那串模板。
    for (const [value, label] of [
      ["{{report.json.verdict}}", "写运营诊断 · JSON · verdict"],
      ["{{save_note.note_id}}", "存成笔记 · 笔记"],
      [" {{report.json.report_markdown}} ", "写运营诊断 · JSON · report_markdown"],
    ]) {
      const { container, unmount } = renderField(value);
      const trigger = screen.getByRole("combobox");
      expect(trigger.textContent).toBe(label);
      expect(container.textContent).not.toContain("{{");
      expect(trigger.querySelector("[data-ref-token]")).not.toBeNull();
      expect(trigger.querySelector("[data-ref-problem]")).toBeNull();
      //: 悬停看得到存下去的那条路径。
      expect(trigger.title).toBe(value.trim().slice(2, -2));
      unmount();
    }
  });

  it("指不到东西的:错误样式的标签,底下一句为什么 —— 不静默显示原文", () => {
    renderField("{{reprot.json.verdict}}");
    const trigger = screen.getByRole("combobox");
    expect(trigger.querySelector("[data-ref-problem='node']")).not.toBeNull();
    expect(screen.getByRole("alert").textContent).toBe(zh.wfRefMissingNode.replace("{node}", "reprot"));
    expect(trigger.textContent).not.toContain("{{");
  });

  it("节点在、没有这个输出:说的是输出", () => {
    renderField("{{report.jsno.verdict}}");
    expect(screen.getByRole("combobox").querySelector("[data-ref-problem='output']")).not.toBeNull();
    expect(screen.getByRole("alert").textContent).toBe(zh.wfRefMissingOutput.replace("{node}", "写运营诊断").replace("{output}", "jsno"));
  });

  it("字面量照原样显示", () => {
    const { container } = renderField("固定的一段话");
    expect(screen.getByRole("combobox").textContent).toBe("固定的一段话");
    expect(container.querySelector("[data-ref-token]")).toBeNull();
  });
});

describe("挑上游的输出", () => {
  it("输出声明了结构的,字段各一项排在它后面;挑了存下去的是那条子路径", async () => {
    const user = userEvent.setup();
    const { onValueChange } = renderField("");
    await user.click(screen.getByRole("combobox"));
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "写运营诊断 · JSON",
      "写运营诊断 · JSON · title",
      "写运营诊断 · JSON · verdict",
      "写运营诊断 · JSON · report_markdown",
      "写运营诊断 · 文本",
      "存成笔记 · 笔记",
      "抓网页 · JSON",
    ]);
    await user.click(within(listbox).getByText("写运营诊断 · JSON · verdict"));
    expect(onValueChange).toHaveBeenLastCalledWith("{{report.json.verdict}}");
  });

  it("没声明结构的输出:在引用后接着敲字段路径,最前给一项「引用 …」", async () => {
    const user = userEvent.setup();
    const { onValueChange } = renderField("");
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("web.json.posts");
    const pick = await screen.findByText(zh.wfRefUseField.replace("{ref}", "抓网页 · JSON · posts"));
    //: 字面量那一项也还在:真想填这么一段字的,照样能填。
    expect(screen.getByText(zh.comboboxUseCustomValue.replace("{q}", "web.json.posts"))).toBeTruthy();
    await user.click(pick);
    expect(onValueChange).toHaveBeenLastCalledWith("{{web.json.posts}}");
  });

  it("前两段不是上游的输出,不冒充引用", async () => {
    const user = userEvent.setup();
    renderField("");
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("data.json.bak");
    await screen.findByText(zh.comboboxUseCustomValue.replace("{q}", "data.json.bak"));
    expect(screen.queryByText(/^引用「/)).toBeNull();
  });

  it("挑资源的下拉(literal=false)只收引用:随手敲的一串字不给填", async () => {
    const user = userEvent.setup();
    renderField("", { literal: false, options: [{ value: "asset-1", label: "片头.mp4" }] });
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("随手一串");
    expect(screen.queryByText(zh.comboboxUseCustomValue.replace("{q}", "随手一串"))).toBeNull();
    await user.clear(document.querySelector<HTMLInputElement>("[cmdk-input]")!);
    await user.keyboard("{{{{web.json.items}}");
    expect(await screen.findByText(zh.wfUseReference.replace("{q}", "{{web.json.items}}"))).toBeTruthy();
  });
});

describe("字和引用混写", () => {
  it("和提示词同一个编辑器:引用是整块的标签,不摆双括号", async () => {
    const { container } = renderField("> {{report.json.verdict}} / {{report.json.report_markdown}}");
    expect(screen.queryByRole("combobox")).toBeNull();
    await waitFor(() =>
      expect([...container.querySelectorAll("[data-ref-chip]")].map((chip) => chip.textContent)).toEqual([
        "report.json.verdict",
        "report.json.report_markdown",
      ]),
    );
    expect(container.textContent).not.toContain("{{");
  });
});
