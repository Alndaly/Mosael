/** @vitest-environment jsdom */
import { act, cleanup, render } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { AnnotationModeHint } from "./AnnotationModeHint";

afterEach(cleanup);

const press = (target: EventTarget, init: KeyboardEventInit) =>
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
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
