/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { Hint, TooltipProvider } from "./tooltip";
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

  it("hint:没被截断时只说补充的那句;被截断时全文在上、补充在下", async () => {
    const { unmount } = render(
      <TooltipProvider delayDuration={0}><Truncate hint="https://example.com/a/b.mp4">b.mp4</Truncate></TooltipProvider>,
    );
    let text = screen.getByText("b.mp4");
    overflow(text, 60, 120);
    hover(text);
    expect((await screen.findByRole("tooltip")).textContent).toBe("https://example.com/a/b.mp4");
    unmount();
    render(<TooltipProvider delayDuration={0}><Truncate hint="qwen3-235b">{NAME}</Truncate></TooltipProvider>);
    text = screen.getByText(NAME);
    overflow(text, 400, 120);
    hover(text);
    expect((await screen.findByRole("tooltip")).textContent).toBe(`${NAME}qwen3-235b`);
  });
});

describe("截断的字在一条 Hint 的触发区里", () => {
  it("说明只出一条:被截断的全文并进那条 Hint,不另挂一条", async () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="双击改名">
          <Truncate>{NAME}</Truncate>
        </Hint>
      </TooltipProvider>,
    );
    const text = screen.getByText(NAME);
    overflow(text, 400, 120);
    hover(text);
    const tooltips = await screen.findAllByRole("tooltip");
    expect(tooltips.map((one) => one.textContent)).toEqual([`${NAME}双击改名`]);
  });

  it("没被截断就只说 Hint 自己那句;Hint 没话说、字也没截断就不出", async () => {
    const { rerender } = render(
      <TooltipProvider delayDuration={0}>
        <Hint label={undefined}>
          <button type="button"><Truncate>短名字</Truncate></button>
        </Hint>
      </TooltipProvider>,
    );
    const text = screen.getByText("短名字");
    overflow(text, 60, 120);
    hover(screen.getByRole("button"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("tooltip")).toBeNull();
    overflow(text, 400, 120);
    rerender(
      <TooltipProvider delayDuration={0}>
        <Hint label={undefined}>
          <button type="button"><Truncate>短名字</Truncate></button>
        </Hint>
      </TooltipProvider>,
    );
    fireEvent.pointerLeave(screen.getByRole("button"));
    hover(screen.getByRole("button"));
    expect((await screen.findByRole("tooltip")).textContent).toBe("短名字");
  });

  it("弹出来的浮层不算 Hint 的触发区:菜单里截断的字自己挂说明,不交给外面那条", () => {
    render(
      <TooltipProvider delayDuration={0}>
        <Hint label="更多">
          <span>
            <Popover open>
              <PopoverTrigger>more</PopoverTrigger>
              <PopoverContent><Truncate>{NAME}</Truncate></PopoverContent>
            </Popover>
          </span>
        </Hint>
      </TooltipProvider>,
    );
    //: React 的 context 会穿过 portal;浮层内容把范围清掉了,所以它自己是一个说明的触发器(Radix 给触发器挂 data-state)。
    expect(screen.getByText(NAME).hasAttribute("data-state")).toBe(true);
  });

  it("在 Hint 的触发区里时自己不挂说明的触发器", () => {
    render(
      <Hint label="双击改名">
        <Truncate>{NAME}</Truncate>
      </Hint>,
    );
    //: 这个 span 就是 Hint 的触发器(data-state 来自 Hint),里面不再有第二个。
    expect(document.querySelectorAll("[data-state]")).toHaveLength(1);
  });
});
