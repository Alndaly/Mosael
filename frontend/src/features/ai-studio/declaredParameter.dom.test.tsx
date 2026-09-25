/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 模型自己声明的参数(插件生成供应商,ADR 0020)在 AI 工作台里的控件。
 *
 * 两件事:**控件照声明长**(数字给数字框、带上下界;文本给文本框;多行给多行框),以及
 * **插件给的默认值只当提示**(占位 / 「默认」那一项),不替用户选 —— 没动过的值就不发。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { DEFAULT_CHOICE, DeclaredParameterControl, ParameterRow, declaredChoices } from "@/features/ai-studio/parameterPanel";
import type { DeclaredParameter } from "@/lib/generationCapabilities";

const steps: DeclaredParameter = {
  key: "3.steps",
  type: "integer",
  label: "KSampler · steps",
  description: "",
  defaultValue: 20,
  minimum: 1,
  maximum: 150,
  step: 1,
  options: [],
  multiline: false,
  advanced: false,
};

describe("模型自己声明的参数", () => {
  it("数字参数:数字框带上下界,默认值只是占位", () => {
    const onChange = vi.fn();
    render(<DeclaredParameterControl parameter={steps} value="" onChange={onChange} />);
    const input = screen.getByPlaceholderText("20") as HTMLInputElement;
    expect(input.type).toBe("number");
    expect(input.min).toBe("1");
    expect(input.max).toBe("150");
    // 没动过就是空的 —— 不替用户填 20
    expect(input.value).toBe("");
    fireEvent.change(input, { target: { value: "30" } });
    expect(onChange).toHaveBeenCalledWith("30");
  });

  it("多行文本给多行框", () => {
    render(
      <DeclaredParameterControl
        parameter={{ ...steps, type: "string", multiline: true, defaultValue: undefined, minimum: undefined, maximum: undefined }}
        value={"a\nb"}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByDisplayValue(/a\s+b/).tagName).toBe("TEXTAREA");
  });

  it("有可选值的给下拉:默认值就是列表里标着「默认」的那一项,不另加一项", () => {
    const onChange = vi.fn();
    render(
      <DeclaredParameterControl
        parameter={{ ...steps, type: "string", options: ["euler", "dpmpp_2m"], defaultValue: "euler" }}
        value=""
        onChange={onChange}
      />,
    );
    // 没动过:触发器上就是 euler 本身(它就是会用的那个值),而不是「默认(euler)」
    const trigger = screen.getByRole("combobox");
    expect(trigger.textContent).toBe("euler");
    expect(trigger.getAttribute("title")).toBe("euler");
  });
});

describe("declaredChoices", () => {
  const t = (key: string) => key;
  const sampler: DeclaredParameter = { ...steps, type: "string", options: ["euler", "dpmpp_2m"], defaultValue: "euler" };

  it("默认值在可选值里:标一句「默认」,选它 = 不发", () => {
    const choices = declaredChoices(sampler, t);
    expect(choices.options.map((one) => one.value)).toEqual(["euler", "dpmpp_2m"]);
    expect(choices.options[0].description).toBe("genDeclaredDefaultHint");
    expect(choices.shown("")).toBe("euler");
    expect(choices.stored("euler")).toBe("");
    expect(choices.stored("dpmpp_2m")).toBe("dpmpp_2m");
    expect(choices.shown("dpmpp_2m")).toBe("dpmpp_2m");
  });

  it("没有默认值(或不在可选值里):另加一项「模型默认」", () => {
    const choices = declaredChoices({ ...sampler, defaultValue: undefined }, t);
    expect(choices.options[0]).toEqual({ value: DEFAULT_CHOICE, label: "genDeclaredDefaultNone", description: undefined });
    expect(choices.shown("")).toBe(DEFAULT_CHOICE);
    expect(choices.stored(DEFAULT_CHOICE)).toBe("");
  });
});

describe("ParameterRow", () => {
  it("标签单行截断、悬停看全名;按容器宽度决定两列还是上下叠", () => {
    const long = "CheckpointLoaderSimple · ckpt_name";
    render(
      <ParameterRow label="模型" title={long}>
        <input aria-label="模型" />
      </ParameterRow>,
    );
    const label = screen.getByText("模型", { selector: "[data-slot=parameter-label]" });
    expect(label.className).toContain("truncate");
    expect(label.className).toContain("min-w-0");
    expect(label.getAttribute("title")).toBe(long);
    const grid = label.parentElement!;
    // 两列只在容器够宽时才出现;控件那一列是 minmax(0,1fr),不会被长值顶出去
    expect(grid.className).toMatch(/@\[\d+px\]\/parameter-row:grid-cols-\[112px_minmax\(0,1fr\)\]/);
    expect(grid.parentElement!.className).toContain("@container/parameter-row");
  });
});
