// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { isImeBackspace, isSyntheticImeBackspace } from "./compositionKeydown";

function syntheticBackspace(): KeyboardEvent {
  const event = document.createEvent("Event");
  event.initEvent("keydown", true, true);
  Object.assign(event, { key: "Backspace", keyCode: 8 });
  return event as unknown as KeyboardEvent;
}

describe("组词中的退格", () => {
  it("真实键盘退格归输入法，Tiptap 不能看见", () => {
    const event = new KeyboardEvent("keydown", { key: "Backspace" });
    expect(isImeBackspace({ composing: true }, event)).toBe(true);
    expect(isSyntheticImeBackspace({ composing: true }, event)).toBe(false);
  });

  it("ProseMirror 从 DOM 变更补发的退格要拦住，否则 Tiptap 会 dispatch 空事务", () => {
    const event = syntheticBackspace();
    expect(isImeBackspace({ composing: true }, event)).toBe(true);
    expect(isSyntheticImeBackspace({ composing: true }, event)).toBe(true);
  });

  it("不在组词中、或者不是退格，都不归这条规则", () => {
    expect(isImeBackspace({ composing: false }, syntheticBackspace())).toBe(false);
    expect(isImeBackspace({ composing: true }, new KeyboardEvent("keydown", { key: "Enter" }))).toBe(false);
  });
});
