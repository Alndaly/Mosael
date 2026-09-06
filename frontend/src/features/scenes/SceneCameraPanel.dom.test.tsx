/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SceneCameraPanel } from "./SceneCameraPanel";
import { Num } from "./SceneControls";
import { makeShot } from "./sceneGraph";
import type { CameraFrame } from "@/api/domains/scenes";
afterEach(cleanup);
const live: CameraFrame = {
  time: 0,
  position: [8, 3, 6],
  target: [4, 1, 2],
  fov: 45,
};
function setup(preview = false) {
  const props = {
    shot: makeShot(),
    time: 0,
    preview,
    playing: false,
    onPatch: vi.fn(),
    onTime: vi.fn(),
    onPreview: vi.fn(),
    onPlaying: vi.fn(),
    capture: vi.fn(),
    observe: vi.fn(),
    camera: vi.fn(() => live),
    onNext: vi.fn(),
  };
  render(<SceneCameraPanel {...props} />);
  return props;
}
it("creates a push from the composition being edited, then shows the resulting shot", () => {
  const p = setup();
  fireEvent.click(screen.getByRole("button", { name: /缓缓推进/ }));
  const shot = p.onPatch.mock.calls[0][0];
  expect(shot.frames[0]).toEqual(live);
  expect(shot.frames.at(-1).target).toEqual(live.target);
  expect(shot.frames.at(-1).position).toEqual([6, 2, 4]);
  expect(p.onPreview).toHaveBeenCalledWith(true);
  expect(p.onTime).toHaveBeenCalledWith(0);
});
it("keeps preview read-only and lets users continue editing from that camera", () => {
  const p = setup(true);
  expect(screen.getByRole("button", { name: "设为起点" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "从当前镜头继续调整" }));
  expect(p.observe).toHaveBeenCalledOnce();
  expect(p.capture).not.toHaveBeenCalled();
});
it("commits a numeric field once on Enter instead of saving twice through blur", () => {
  const changed = vi.fn();
  render(<Num label="测试数值" value={1} onChange={changed} />);
  const field = screen.getByRole("spinbutton");
  field.focus();
  fireEvent.change(field, { target: { value: "4" } });
  fireEvent.keyDown(field, { key: "Enter" });
  expect(changed).toHaveBeenCalledExactlyOnceWith(4);
});
