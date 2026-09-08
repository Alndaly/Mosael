/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SceneCameraPanel } from "./SceneCameraPanel";
import { Num } from "./SceneControls";
import { makeShot } from "./sceneGraph";

afterEach(cleanup);
const live = {
  position: [8, 3, 6] as [number, number, number],
  target: [4, 1, 2] as [number, number, number],
  fov: 45,
};
function setup(preview = false) {
  const { camera, shot } = makeShot();
  const props = {
    shot,
    rig: camera,
    time: 0,
    preview,
    playing: false,
    onPatch: vi.fn(),
    onRig: vi.fn(),
    onTime: vi.fn(),
    onPreview: vi.fn(),
    onPlaying: vi.fn(),
    capture: vi.fn(),
    observe: vi.fn(),
    camera: vi.fn(() => live),
  };
  render(<SceneCameraPanel {...props} />);
  return props;
}
it("creates a push from the composition being edited, then shows the resulting shot", () => {
  const p = setup();
  fireEvent.click(screen.getByRole("button", { name: /缓缓推进/ }));
  // 运镜落在**相机**上,不在镜头上 —— 所以看的是 onRig。
  const rig = p.onRig.mock.calls[0][0];
  expect(rig.track[0]).toEqual({ time: 0, ...live });
  expect(rig.track.at(-1).target).toEqual(live.target);
  expect(rig.track.at(-1).position).toEqual([6, 2, 4]);
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
