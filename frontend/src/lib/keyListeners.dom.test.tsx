/** @vitest-environment jsdom */
import { act, cleanup, render } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { AnnotationModeHint } from "@/features/markers/AnnotationModeHint";
import { listenKeys } from "@/lib/shortcuts";

afterEach(cleanup);

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

describe("批注模式的 Esc", () => {
  it("在批注框里组词时按 Esc 是放弃组词,不退出批注模式;平常按 Esc 才退出", () => {
    const onExit = vi.fn();
    render(
      <>
        <AnnotationModeHint kind="comment" onExit={onExit} />
        <textarea aria-label="draft" />
      </>,
    );
    const draft = document.querySelector("textarea")!;
    draft.focus();
    press(draft, { key: "Escape", isComposing: true, keyCode: 229 });
    expect(onExit).not.toHaveBeenCalled();
    press(draft, { key: "Escape" });
    expect(onExit).toHaveBeenCalledTimes(1);
  });
});
