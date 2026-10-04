/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "./tooltip";
import { Truncate } from "./truncate";

function overflow(element: HTMLElement, scroll: number, client: number) {
  Object.defineProperty(element, "scrollWidth", { value: scroll, configurable: true });
  Object.defineProperty(element, "clientWidth", { value: client, configurable: true });
}

function hover(element: HTMLElement) {
  fireEvent.pointerEnter(element);
  fireEvent.pointerMove(element);
}

const NAME = "seedance-2.5-reference-to-video-final-final.safetensors";

describe("截断的文字悬停看全文", () => {
  it("单行截断,全文仍在 DOM 里(读屏念的是全文)", () => {
    render(<Truncate>{NAME}</Truncate>);
    const text = screen.getByText(NAME);
    expect(text.className).toContain("truncate");
  });

  it("真被截断了才出说明,内容是全文", async () => {
    render(<TooltipProvider delayDuration={0}><Truncate>{NAME}</Truncate></TooltipProvider>);
    const text = screen.getByText(NAME);
    overflow(text, 400, 120);
    hover(text);
    expect((await screen.findByRole("tooltip")).textContent).toBe(NAME);
  });

  it("没被截断就不出 —— 放得下的名字悬停再说一遍是噪音", async () => {
    render(<TooltipProvider delayDuration={0}><Truncate>短名字</Truncate></TooltipProvider>);
    const text = screen.getByText("短名字");
    overflow(text, 60, 120);
    hover(text);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("显示的不是纯文字时,用 text 指定说明里的全文", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Truncate text={NAME}><b>{NAME}</b></Truncate>
      </TooltipProvider>,
    );
    const text = screen.getByText(NAME).parentElement!;
    overflow(text, 400, 120);
    hover(text);
    expect((await screen.findByRole("tooltip")).textContent).toBe(NAME);
  });

  it("多行截断(lines)按高度判断", async () => {
    render(<TooltipProvider delayDuration={0}><Truncate lines={2}>{NAME}</Truncate></TooltipProvider>);
    const text = screen.getByText(NAME);
    expect(text.className).toContain("line-clamp-2");
    Object.defineProperty(text, "scrollHeight", { value: 80, configurable: true });
    Object.defineProperty(text, "clientHeight", { value: 40, configurable: true });
    hover(text);
    expect((await screen.findByRole("tooltip")).textContent).toBe(NAME);
  });
});
