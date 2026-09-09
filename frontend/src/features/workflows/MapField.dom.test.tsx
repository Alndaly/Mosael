/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { messages } from "@/app/messages";
import { MapField } from "./MapField";

const zh = messages["zh-CN"];
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: keyof typeof zh) => zh[key],
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const variables = ["{{start.cleanup_style}}", "{{source_video.asset_id}}", "{{verbatim_transcript.text}}"];

describe("具名输出的「值或上游输出」", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("屏幕上不摆花括号,存下去的仍然是模板", () => {
    /*
     * 那两对括号是语法不是信息:一列全是 `{{…}}` 时,要跨过它们才读得到真正区分彼此的那半截,
     * 而长一点的引用右边还会先被截断(`{{apply_cleanup.removed_seco…}}`)。
     * 但**值不能跟着改** —— 引擎认的就是 `{{…}}`,去了括号等于把引用变成一个同名的字面量。
     */
    const onChange = vi.fn();
    render(<MapField value={{ source_asset_id: "{{source_video.asset_id}}" }} onChange={onChange} variables={variables} />);
    const trigger = screen.getByRole("combobox");
    expect(trigger.textContent).toContain("source_video.asset_id");
    expect(trigger.textContent).not.toContain("{{");
    // 没动过就不该发出变更 —— 顺带钉住"显示归显示,值不受影响"。
    expect(onChange).not.toHaveBeenCalled();
  });

  it("不再另摆一排上游 chip —— 同一份清单在同一个面板里出现两遍,第二遍只是噪音", () => {
    const { container } = render(<MapField value={{}} onChange={vi.fn()} variables={variables} />);
    for (const ref of variables) {
      expect(container.textContent, `${ref} 不该在面板上另列一遍`).not.toContain(ref.replace(/[{}]/g, ""));
    }
  });
});
