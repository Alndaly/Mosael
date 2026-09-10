/** @vitest-environment jsdom */
import React from "react";
import { render } from "@testing-library/react";
import { Ratio } from "lucide-react";
import { describe, expect, it } from "vitest";

import { ParameterField, ParameterSection } from "./parameterPanel";

/**
 * 引擎参数栏里每一栏都挂着 `supportsParameter(...)`:换个模型,一整块可能一栏都不剩。
 * 这几条钉的就是"空块不许留下标题" —— 一个光秃秃的「出片规格」宣告这儿有东西,然后什么都不给。
 */
describe("参数分块", () => {
  it("所有栏都不满足条件时,整块连标题都不渲染", () => {
    const supportsSize = false;
    const supportsSeed = false;
    const { container } = render(
      <ParameterSection icon={Ratio} title="出片规格">
        {supportsSize && <ParameterField label="尺寸"><input /></ParameterField>}
        {supportsSeed && <ParameterField label="Seed"><input /></ParameterField>}
      </ParameterSection>,
    );
    expect(container.textContent).toBe("");
  });

  it("map 出来的栏一个都没有时也算空 —— 各家自定义的开关就是这么来的", () => {
    const keys: string[] = [];
    const { container } = render(
      <ParameterSection icon={Ratio} title="调参">
        {keys.map((key) => (
          <ParameterField key={key} label={key}>
            <input />
          </ParameterField>
        ))}
      </ParameterSection>,
    );
    expect(container.textContent).toBe("");
  });

  it("只要还剩一栏,标题就照常出现", () => {
    const { container } = render(
      <ParameterSection icon={Ratio} title="出片规格">
        {false && <ParameterField label="尺寸"><input /></ParameterField>}
        <ParameterField label="张数">
          <input />
        </ParameterField>
      </ParameterSection>,
    );
    expect(container.querySelector("h3")?.textContent).toBe("出片规格");
    expect(container.querySelectorAll("label")).toHaveLength(1);
  });
});

describe("一栏参数", () => {
  /** label 包着控件,点标签就聚焦到控件 —— 不靠手写 htmlFor/id 配对。 */
  it("标签和控件在同一个 label 里", () => {
    const { container } = render(
      <ParameterField label="尺寸">
        <input />
      </ParameterField>,
    );
    const label = container.querySelector("label")!;
    expect(label.querySelector("span")?.textContent).toBe("尺寸");
    expect(label.querySelector("input")).not.toBeNull();
  });

  it("没给解释就不留空位", () => {
    const { container } = render(
      <ParameterField label="尺寸">
        <input />
      </ParameterField>,
    );
    expect(container.querySelectorAll("label > span")).toHaveLength(1);
  });
});
