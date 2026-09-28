/** @vitest-environment jsdom */
import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { listenKeys } from "@/lib/shortcuts";

const press = (target: EventTarget, init: KeyboardEventInit) =>
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
  });

describe("listenKeys:输入法组词期间的按键不交给快捷键", () => {
  it("isComposing 的、keyCode 229 的都不交;平常的照交;拆掉之后都不交", () => {
    const handler = vi.fn();
    const stop = listenKeys(window, handler);
    press(document.body, { key: "Enter", isComposing: true });
    //: 开始组词的那一下:Chromium 还没标 isComposing,但 keyCode 已经是 229。
    press(document.body, { key: "n", keyCode: 229 });
    expect(handler).not.toHaveBeenCalled();
    press(document.body, { key: "Escape" });
    expect(handler).toHaveBeenCalledTimes(1);
    stop();
    press(document.body, { key: "Escape" });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
