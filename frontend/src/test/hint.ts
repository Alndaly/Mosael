import { act, fireEvent, screen } from "@testing-library/react";

/**
 * 读一个控件的悬停说明(`Hint` / `IconButton` 那一条)。
 *
 * 像键盘用户那样切过去:说明立刻出,不用等悬停延时,也不依赖 jsdom 没有的指针几何。点不了的按钮
 * 说明挂在外面那层壳上(见 Hint 的 `disabledReason`),所以从按钮往上找壳。返回说明的全文
 * (名字、快捷键、补充说明、点不了的原因按顺序连在一起)。
 */
export async function readHint(element: HTMLElement): Promise<string> {
  const target = (element.closest("[data-hint-disabled]") as HTMLElement | null) ?? element;
  fireEvent.keyDown(document, { key: "Tab" });
  act(() => target.focus());
  const tooltip = await screen.findByRole("tooltip");
  return tooltip.textContent ?? "";
}
