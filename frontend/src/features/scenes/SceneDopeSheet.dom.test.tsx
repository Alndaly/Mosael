/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { SceneDopeSheet } from "./SceneDopeSheet";
import { makeObject } from "./sceneGraph";
import { stillFrame } from "./sceneTracks";
import type { SceneContent, SceneShot } from "@/api/domains/scenes";

const camera = makeObject("camera", {
  id: "cam",
  name: "主机位",
  track: [stillFrame(makeObject("camera"), 0), stillFrame(makeObject("camera"), 5)],
});
const walker = makeObject("figure", {
  id: "walk",
  name: "路人",
  track: [stillFrame(makeObject("figure"), 2)],
});
const content = { objects: [walker, camera] } as unknown as SceneContent;
const shot: SceneShot = {
  id: "s",
  name: "镜头 1",
  duration: 10,
  aspect: "16:9",
  easing: "smooth",
  camera_id: "cam",
};

function sheet(overrides: Partial<React.ComponentProps<typeof SceneDopeSheet>> = {}) {
  const props = {
    content,
    shot,
    time: 0,
    selectedId: null,
    playing: false,
    onSeek: vi.fn(),
    onSelect: vi.fn(),
    ...overrides,
  };
  return { ...render(<SceneDopeSheet {...props} />), props };
}

it("机位和物体同列一张表,机位在第一行", () => {
  sheet();
  const names = screen.getAllByRole("button").map((one) => one.textContent);
  expect(names).toEqual(["主机位", "路人"]);
});

it("每一档按时间落在轨道上 —— 位置即时间", () => {
  const { container } = sheet();
  const left = [...container.querySelectorAll<HTMLElement>(".scene-dope-key")].map(
    (one) => one.style.left,
  );
  // 相机 0s / 5s,人物 2s,镜头 10 秒长。
  expect(left).toEqual(["0%", "50%", "20%"]);
});

it("在轨道上点一下就把时间拨到那儿,并选中那一行", () => {
  const { container, props } = sheet();
  const lane = container.querySelector<HTMLElement>(".scene-dope-lane")!;
  // jsdom 里所有元素的宽度都是 0,量不出比例 —— 喂一个真实的矩形进去。
  lane.getBoundingClientRect = () => ({ left: 100, width: 200, right: 300, top: 0, bottom: 0, height: 0, x: 100, y: 0, toJSON: () => ({}) });
  fireEvent.pointerDown(lane, { clientX: 150 });
  expect(props.onSelect).toHaveBeenCalledWith("cam");
  expect(props.onSeek).toHaveBeenCalledWith(2.5);
});

it("播放头落在当前时刻上", () => {
  const { container } = sheet({ time: 4 });
  expect(container.querySelector<HTMLElement>(".scene-dope-playhead")!.style.left).toBe("40%");
});

it("时长为 0 时不算出 NaN%（那会让整张表失去定位）", () => {
  const { container } = sheet({ shot: { ...shot, duration: 0 }, time: 3 });
  expect(container.querySelector<HTMLElement>(".scene-dope-playhead")!.style.left).toBe("0%");
});
