/** @vitest-environment jsdom */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Hint, TooltipProvider } from "./tooltip";

function mount() {
  render(
    <TooltipProvider delayDuration={0}>
      <Hint label="让 AI 写" hint="在这张便签下面打开 AI 写作">
        <button type="button" aria-label="让 AI 写">A</button>
      </Hint>
      <Hint label="翻译">
        <button type="button" aria-label="翻译">B</button>
      </Hint>
    </TooltipProvider>,
  );
  return [screen.getByRole("button", { name: "让 AI 写" }), screen.getByRole("button", { name: "翻译" })];
}

describe("图标按钮的悬停说明", () => {
  it("键盘切过来时出:名字一行、说明一行", () => {
    const [write] = mount();
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => write.focus());
    expect(screen.getByRole("tooltip").textContent).toBe("让 AI 写在这张便签下面打开 AI 写作");
  });

  it("焦点被还回来(关掉菜单、面板之后)不出 —— 否则那条说明挂在按钮上,移到别的按钮也不走", () => {
    const [write] = mount();
    fireEvent.pointerDown(document.body);
    act(() => write.focus());
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("同一时刻只有一条:下一条出来,上一条收起", () => {
    const [write, translate] = mount();
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => write.focus());
    fireEvent.keyDown(document, { key: "Tab" });
    act(() => translate.focus());
    expect(screen.getAllByRole("tooltip").map((one) => one.textContent)).toEqual(["翻译"]);
  });
});
