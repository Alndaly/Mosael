/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 插件数组里每一项是一块结构(Manim 讲解视频的「讲解步骤」):一项一张卡,按每一项声明的几格填 ——
 * 不是一个让人手写 `[{"title": …}]` 的 JSON 框(用户截图:框里是一个字面的 `""`)。
 *
 * 走的是真的 NodeConfigForm:字段声明的形状和 /api/workflows/node-types 发下来的一样(后端按界面语言翻好了
 * label / description,见 backend plugins.nodes 的 _structure_fields 与 node_catalog.translated_spec)。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { NodeConfigForm, type ConfigSpec } from "@/features/nodeForms/NodeConfigForm";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

const SPECS = {
  subtitle: { type: "template", label: "副标题", description: "标题页的副标题,一句话说清讲什么。" },
  steps: {
    type: "list",
    required: true,
    label: "讲解步骤",
    description: "一步一步讲的内容,1 到 20 步。",
    editor: "items",
    min_items: 1,
    max_items: 3,
    fields: {
      title: { type: "text", required: true, label: "标题", description: "这一步的标题。" },
      narration: { type: "text", multiline: true, label: "旁白" },
      bullets: { type: "list", label: "要点", max_items: 6 },
      plot: {
        type: "object",
        editor: "fields",
        label: "函数图像",
        fields: {
          expression: { type: "text", required: true, label: "算式" },
          x_min: { type: "number", label: "x 最小值" },
        },
      },
      seconds: { type: "number", label: "时长(秒)" },
    },
  },
  summary: { type: "list", label: "要点回顾", max_items: 6 },
} as unknown as Record<string, ConfigSpec>;

function renderForm(config: Record<string, unknown>, keys: string[] = ["steps"]) {
  const onSet = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TooltipProvider>
        <NodeConfigForm
          fields={keys.map((key) => [key, SPECS[key]] as [string, ConfigSpec])}
          config={config}
          workspaceId="w1"
          variables={["{{llm-1.json}}"]}
          fieldOptions={{ dynamicOptions: () => null, whyEmpty: () => ({ kind: "none" }), assets: [] }}
          onSetConfig={onSet}
          onTypeConfig={vi.fn()}
          onPatchConfig={vi.fn()}
          references
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return onSet;
}

const cards = () => screen.queryAllByRole("region");
const jsonEditor = () => document.querySelector(".cm-editor");

describe("一串结构:一项一张卡", () => {
  it("字段名按后端翻好的显示(副标题 / 讲解步骤 / 要点回顾),不是英文键名", () => {
    renderForm({}, ["subtitle", "steps", "summary"]);
    const text = document.body.textContent ?? "";
    for (const label of ["副标题", "讲解步骤", "要点回顾", "标题", "旁白", "函数图像"]) expect(text).toContain(label);
    for (const key of ["Subtitle", "Steps", "Summary", "subtitle", "steps", "summary"]) {
      expect(Array.from(document.querySelectorAll("[data-field-key] > span")).map((el) => el.textContent)).not.toContain(key);
    }
  });

  it("值是空串(接上游时清掉的字面量)按还没填:一张空卡(至少一步),不是一个写着 `\"\"` 的 JSON 框", () => {
    renderForm({ steps: "" });
    expect(jsonEditor()).toBeNull();
    expect(cards()).toHaveLength(1);
    expect(document.body.textContent).not.toContain('""');
  });

  it("填一格只存填了的那几格;数也存成文字(后端按 input_schema 转回数)", () => {
    const onSet = renderForm({ steps: "" });
    const card = cards()[0];
    const title = within(card).getAllByRole("textbox")[0];
    fireEvent.change(title, { target: { value: "勾股定理" } });
    expect(onSet).toHaveBeenLastCalledWith("steps", [{ title: "勾股定理" }]);
  });

  it("函数图像收成一组,填过的一打开就展开;改里面一格只动那一格,别的键原样留着", () => {
    const onSet = renderForm({ steps: [{ title: "图像", plot: { expression: "sin(x)" }, extra: 1 }] });
    const group = document.querySelector<HTMLDetailsElement>('details[data-field-key="plot"]');
    expect(group?.open).toBe(true);
    const xMin = within(group as HTMLElement).getAllByRole("textbox")[1];
    fireEvent.change(xMin, { target: { value: "-3" } });
    expect(onSet).toHaveBeenLastCalledWith("steps", [{ title: "图像", plot: { expression: "sin(x)", x_min: "-3" }, extra: 1 }]);
  });

  it("上下挪、删;删到下限(1 步)不让删", () => {
    const onSet = renderForm({ steps: [{ title: "一" }, { title: "二" }] });
    expect(cards()).toHaveLength(2);
    fireEvent.click(within(cards()[0]).getByRole("button", { name: "wfItemsMoveDown" }));
    expect(onSet).toHaveBeenLastCalledWith("steps", [{ title: "二" }, { title: "一" }]);
    fireEvent.click(within(cards()[1]).getByRole("button", { name: "delete" }));
    expect(onSet).toHaveBeenLastCalledWith("steps", [{ title: "二" }]);
    expect(cards()).toHaveLength(1);
    expect((within(cards()[0]).getByRole("button", { name: "delete" }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(cards()[0]).getByRole("button", { name: "wfItemsMoveUp" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("加一项:新卡空着不存;到了上限(max_items)不再给「加一项」", () => {
    const onSet = renderForm({ steps: [{ title: "一" }, { title: "二" }] });
    //: 每张卡里「要点」那一串也有自己的「加一项」;整串的那一个在卡片后面
    const addCard = () => document.querySelector('[data-slot="items-field"] > button');
    fireEvent.click(addCard() as HTMLElement);
    expect(cards()).toHaveLength(3);
    expect(onSet).not.toHaveBeenCalled();
    expect(addCard()).toBeNull();
    expect(screen.getByRole("note").textContent).toBe("wfItemsFull");
  });

  it("整格是一段 `{{…}}` 引用:照旧显示那段引用,不摆卡片", async () => {
    renderForm({ steps: "{{llm-1.json}}" });
    expect(cards()).toHaveLength(0);
    await waitFor(() => expect(document.body.textContent).toContain("llm-1.json"));
  });

  it("存着的不是一串对象(形状写错了):退回 JSON 框原样摆出来,不在卡片里丢掉", () => {
    renderForm({ steps: ["只是一段字"] });
    expect(cards()).toHaveLength(0);
    expect(jsonEditor()).not.toBeNull();
  });
});
