/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ShortcutRecorder } from "./ShortcutRecorder";
import type { CanvasMarker } from "./markers";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const marker: CanvasMarker = { id: "b", name: "结尾", x: 0, y: 0 };
const others: CanvasMarker[] = [marker, { id: "a", name: "开头", x: 0, y: 0, shortcut: "Alt+1" }];

function record(key: Partial<KeyboardEvent> & { key: string }, onChange = vi.fn()) {
  render(<ShortcutRecorder marker={marker} markers={others} onChange={onChange} />);
  fireEvent.click(screen.getByText("markerShortcutNone"));
  fireEvent.keyDown(screen.getByText("markerShortcutRecording"), key);
  return onChange;
}

it("撞上应用自己的快捷键就不给配", () => {
  const onChange = record({ key: "z", code: "KeyZ", metaKey: true });
  // 配不上去 —— 不是"配上了再看谁先响应",那样的表现是一个时灵时不灵的键。
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("markerConflictReserved");
});

it("撞上另一个标记也不给配", () => {
  const onChange = record({ key: "1", code: "Digit1", altKey: true });
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("markerConflictMarker");
});

it("不冲突的组合当场绑上,并且退出录制态", () => {
  const onChange = record({ key: "2", code: "Digit2", altKey: true });
  expect(onChange).toHaveBeenCalledWith("Alt+2");
  expect(screen.queryByText("markerShortcutRecording")).not.toBeInTheDocument();
});

it("被拒之后停在录制态 —— 换一个键就行,不用再点一次", () => {
  const onChange = vi.fn();
  render(<ShortcutRecorder marker={marker} markers={others} onChange={onChange} />);
  fireEvent.click(screen.getByText("markerShortcutNone"));
  fireEvent.keyDown(screen.getByText("markerShortcutRecording"), { key: "z", code: "KeyZ", metaKey: true });
  fireEvent.keyDown(screen.getByText("markerShortcutRecording"), { key: "3", code: "Digit3", altKey: true });
  expect(onChange).toHaveBeenCalledWith("Alt+3");
});
