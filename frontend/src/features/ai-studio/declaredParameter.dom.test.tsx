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

import { DeclaredParameterControl } from "@/features/ai-studio/parameterPanel";
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

  it("有可选值的给下拉,第一项是「默认」(= 不发)", () => {
    render(
      <DeclaredParameterControl
        parameter={{ ...steps, type: "string", options: ["euler", "dpmpp_2m"], defaultValue: "euler" }}
        value=""
        onChange={vi.fn()}
      />,
    );
    // 触发器上显示的是「默认(euler)」那一项,不是 euler 本身 —— 两者提交出去的东西不一样
    expect(screen.getByRole("combobox").textContent).toContain("genDeclaredDefault");
  });
});
