import { act, fireEvent, screen } from "@testing-library/react";

/** 点不了的按钮说明挂在外面那层壳上(见 Hint 的 `disabledReason`),从按钮往上找壳。 */
function triggerOf(element: HTMLElement): HTMLElement {
  return (element.closest("[data-hint-disabled]") as HTMLElement | null) ?? element;
}

/**
 * 读一个控件的悬停说明(`Hint` / `IconButton` 那一条)。
 *
 * 像键盘用户那样切过去:说明立刻出,不用等悬停延时,也不依赖 jsdom 没有的指针几何。返回说明的全文
 * (名字、快捷键、补充说明、点不了的原因按顺序连在一起)。拿不到焦点的元素(徽标、标签、芯片)用
 * `hoverHint`。
 */
export async function readHint(element: HTMLElement): Promise<string> {
  const target = triggerOf(element);
  fireEvent.keyDown(document, { key: "Tab" });
  act(() => {
    //: 它可能已经有焦点了(对话框打开时自动聚焦到第一个能聚焦的,正好是它):再 focus() 一次什么都不发生,说明不出。
    //: 先移开再切回来 —— 此前这种用例能绿,靠的是上一条测试按过 Tab、留下了「键盘在切」的标记(单独跑必红)。
    if (document.activeElement === target) target.blur();
    target.focus();
  });
  const tooltip = await screen.findByRole("tooltip");
  return tooltip.textContent ?? "";
}

/**
 * 读一个**拿不到焦点**的元素上的悬停说明:像指针那样移上去,等说明出来(悬停延时之内)。
 * 开了假定时器的测试别用它(findByRole 要真定时器),照文件里已有的写法推进时间再同步读。
 */
export async function hoverHint(element: HTMLElement): Promise<string> {
  const target = triggerOf(element);
  fireEvent.pointerEnter(target);
  fireEvent.pointerMove(target);
  //: 悬停有延时(应用里 300ms),整套并行跑时 jsdom 慢,给足余量。
  const tooltip = await screen.findByRole("tooltip", {}, { timeout: 2000 });
  return tooltip.textContent ?? "";
}
