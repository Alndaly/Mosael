/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
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

describe("在面板里敲名字", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  });

  /** 和检查器一样受控:每次变更都经对象存回去,再作为 value 传回来。 */
  function Controlled({ initial, onSaved }: { initial: Record<string, unknown>; onSaved: (value: Record<string, unknown>) => void }) {
    const [value, setValue] = React.useState(initial);
    return (
      <MapField
        value={value}
        variables={variables}
        onChange={(next) => {
          setValue(next);
          onSaved(next);
        }}
      />
    );
  }

  //: 已有一行 topic,新加一行想叫 topic_en —— 敲到 "topic" 那一下两行同名,对象里只剩一个键。
  //: 此前组件拿「对象还原出来的行」去和本地行比,认定是外面改了,把本地行整个换掉:
  //: 原来那行的值被新行的空值顶掉,新行消失,光标所在的输入框也跟着没了。
  it("敲到和已有的名字撞上时,已有那行和正在敲的这行都还在", () => {
    const saved: Array<Record<string, unknown>> = [];
    render(<Controlled initial={{ topic: "{{llm-1.text}}" }} onSaved={(value) => saved.push(value)} />);
    fireEvent.click(screen.getByRole("button", { name: zh.wfMapAdd }));
    const typing = () => screen.getAllByPlaceholderText(zh.wfMapKey)[1] as HTMLInputElement;
    for (const key of ["t", "to", "top", "topi", "topic", "topic_", "topic_e", "topic_en"]) {
      fireEvent.change(typing(), { target: { value: key } });
      expect(screen.getAllByPlaceholderText(zh.wfMapKey), `敲到 "${key}" 时`).toHaveLength(2);
    }
    expect(typing().value).toBe("topic_en");
    expect(saved.at(-1)).toEqual({ topic: "{{llm-1.text}}", topic_en: "" });
    // 撞名的那一瞬间存下去的也不能丢掉已有那行的值。
    expect(saved.every((value) => value.topic === "{{llm-1.text}}")).toBe(true);
  });
});
