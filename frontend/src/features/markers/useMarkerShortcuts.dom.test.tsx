/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { useMarkerShortcuts } from "./useMarkerShortcuts";
import type { CanvasMarker } from "./markers";

const markers: CanvasMarker[] = [
  { id: "a", name: "开头", x: 10, y: 20, shortcut: "Alt+1" },
  { id: "b", name: "只有名字", x: 0, y: 0 },
  { id: "c", name: "单键", x: 5, y: 5, shortcut: "1" },
];

function Harness({ jump, enabled = true }: { jump: (marker: CanvasMarker) => void; enabled?: boolean }) {
  useMarkerShortcuts(markers, jump, enabled);
  return <input aria-label="prompt" />;
}

it("按下绑定的键就跳到那个标记", () => {
  const jump = vi.fn();
  render(<Harness jump={jump} />);
  fireEvent.keyDown(window, { key: "1", code: "Digit1", altKey: true });
  expect(jump).toHaveBeenCalledWith(markers[0]);
});

it("没绑键的标记按什么都跳不过去", () => {
  const jump = vi.fn();
  render(<Harness jump={jump} />);
  fireEvent.keyDown(window, { key: "9", code: "Digit9", altKey: true });
  expect(jump).not.toHaveBeenCalled();
});

it("焦点在输入框里时让路 —— 否则在提示词里打一个 1 就被传送走了", () => {
  const jump = vi.fn();
  const { getByLabelText } = render(<Harness jump={jump} />);
  const input = getByLabelText("prompt");
  input.focus();
  fireEvent.keyDown(input, { key: "1", code: "Digit1" });
  expect(jump).not.toHaveBeenCalled();
  // 同一个键在画布上是有效的。
  fireEvent.keyDown(window, { key: "1", code: "Digit1" });
  expect(jump).toHaveBeenCalledWith(markers[2]);
});

it("关掉之后不再监听(评论模式下画布不接管按键)", () => {
  const jump = vi.fn();
  render(<Harness jump={jump} enabled={false} />);
  fireEvent.keyDown(window, { key: "1", code: "Digit1", altKey: true });
  expect(jump).not.toHaveBeenCalled();
});
