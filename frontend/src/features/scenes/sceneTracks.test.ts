import { describe, expect, it } from "vitest";

import { makeObject } from "./sceneGraph";
import {
  MAX_KEYS,
  moveSceneKeys,
  frameForObject,
  keyIndexAt,
  neighbourKeyTime,
  removeKeyAt,
  stillFrame,
  trackRows,
  upsertKey,
} from "./sceneTracks";
import type { Keyframe, SceneContent, SceneShot } from "@/api/domains/scenes";

const shot = (camera_id: string): SceneShot => ({
  id: "shot-1",
  name: "镜头 1",
  duration: 10,
  aspect: "16:9",
  easing: "smooth",
  camera_id,
});

describe("记一档", () => {
  it("只在指定时刻打帧，不偷偷补零秒帧", () => {
    const box = makeObject("box");
    expect(upsertKey([], stillFrame(box, 3))!.map(f => f.time)).toEqual([3]);
  });

  it("第一档就记在 0 秒时不补 —— 那一档自己就是起点", () => {
    const box = makeObject("box");
    expect(upsertKey([], stillFrame(box, 0))!.map((f) => f.time)).toEqual([0]);
  });

  it("同一刻再记一次是替换,不是又加一档", () => {
    const box = makeObject("box");
    const first = upsertKey([], stillFrame(box, 0))!;
    const again = upsertKey(first, stillFrame({ ...box, position: [1, 2, 3] }, 0))!;
    expect(again).toHaveLength(1);
    expect(again[0].position).toEqual([1, 2, 3]);
  });

  it("永远按时间排好序 —— 采样是按顺序找区间的,乱序就会插错段", () => {
    const box = makeObject("box");
    let track: Keyframe[] = [];
    for (const at of [4, 1, 9, 2]) track = upsertKey(track, stillFrame(box, at))!;
    expect(track.map((f) => f.time)).toEqual([1, 2, 4, 9]);
  });

  it("满了就返回 null,而不是悄悄丢一档", () => {
    const box = makeObject("box");
    const full = Array.from({ length: MAX_KEYS }, (_, i) => stillFrame(box, i));
    expect(upsertKey(full, stillFrame(box, 999))).toBeNull();
    // 落在已有的那一档上是替换,不增加长度 —— 满了也该让人改得动。
    expect(upsertKey(full, stillFrame(box, 3))).toHaveLength(MAX_KEYS);
  });

  it("相机和别的物体记的字段不同,而且不混着记", () => {
    // 给相机记一个 scale,采样时没人读它;给方块记一个 target 同理 —— 都是存进去就再也
    // 找不回来的字段,而它会让"这一档是什么"变得说不清。
    const camera = stillFrame(makeObject("camera"));
    expect(Object.keys(camera).sort()).toEqual(["fov", "position", "target", "time"]);
    const box = stillFrame(makeObject("box"));
    expect(Object.keys(box).sort()).toEqual(["position", "rotation", "scale", "time"]);
  });
});

describe("移除一档", () => {
  it("这一刻没有档就返回 null —— 调用方据此知道没什么可删的", () => {
    const box = makeObject("box");
    expect(removeKeyAt([stillFrame(box, 0), stillFrame(box, 5)], 2)).toBeNull();
  });

  it("只删指定帧，保留最后一帧及它的姿态", () => {
    const box = makeObject("box");
    expect(removeKeyAt([stillFrame(box, 0), stillFrame(box, 5)], 0)).toEqual([stillFrame(box, 5)]);
    expect(removeKeyAt([stillFrame(box, 5)], 5)).toEqual([]);
  });

  it("容差认得出同一刻 —— 时间是浮点算出来的,不会正好相等", () => {
    const box = makeObject("box");
    const track = [stillFrame(box, 0), stillFrame(box, 3), stillFrame(box, 7)];
    expect(keyIndexAt(track, 3.0000001)).toBe(1);
    expect(removeKeyAt(track, 3.0000001)).toHaveLength(2);
  });
});

describe("跳到上/下一档", () => {
  const times = [0, 2, 5.5, 9];
  it("跳的是**下一档**,不是最近的一档", () => {
    expect(neighbourKeyTime(times, 2, 1)).toBe(5.5);
    expect(neighbourKeyTime(times, 5.4, -1)).toBe(2);
  });
  it("正好停在某一档上时不原地不动", () => {
    expect(neighbourKeyTime(times, 5.5, -1)).toBe(2);
    expect(neighbourKeyTime(times, 5.5, 1)).toBe(9);
  });
  it("到头了返回 null —— 不循环回另一端", () => {
    expect(neighbourKeyTime(times, 9, 1)).toBeNull();
    expect(neighbourKeyTime(times, 0, -1)).toBeNull();
    expect(neighbourKeyTime([], 3, 1)).toBeNull();
  });
});

describe("关键帧视图的行", () => {
  const camera = makeObject("camera", { id: "cam", name: "机位" });
  const walker = makeObject("figure", { id: "walk", name: "人物", track: [stillFrame(makeObject("figure"), 0)] });
  const idle = makeObject("box", { id: "idle", name: "不动的方块" });
  const content = { objects: [idle, walker, camera] } as unknown as SceneContent;

  it("默认显示所有物体，切换选择不会改变轨道集合", () => {
    expect(trackRows(content, shot("cam")).map(row => row.object.id)).toEqual(["cam", "idle", "walk"]);
  });

  it("机位排在最上,而且和物体同列一张表", () => {
    const rows = trackRows(content, shot("cam"));
    expect(rows[0].isRig).toBe(true);
    expect(rows.slice(1).every((row) => !row.isRig)).toBe(true);
  });

  it("不动的机位也有一行 —— 那是「可以在这儿记一档」的位置", () => {
    expect(trackRows(content, shot("cam"))[0].times).toEqual([]);
  });
});

 describe("编辑关键帧", () => {
  const box = makeObject("box", { id: "box", track: [
    {time: 0, position: [0, 0, 0]}, {time: 2, position: [2, 0, 0]}, {time: 5, position: [5, 0, 0]},
  ] });
  const content = { objects: [box] } as unknown as SceneContent;
  it("多帧一起移动，保留间距、姿态和排序", () => {
    const moved = moveSceneKeys(content, [{id: "box", time: 0}, {id: "box", time: 2}], 1, 10)!;
    expect(moved.objects[0].track.map(f => f.time)).toEqual([1, 3, 5]);
    expect(moved.objects[0].track[1].position).toEqual([2, 0, 0]);
    expect(box.track[0].time).toBe(0);
  });
  it("遇到已有帧或越界时拒绝，不能覆盖另一帧", () => {
    expect(moveSceneKeys(content, [{id: "box", time: 2}], 3, 10)).toBeNull();
    expect(moveSceneKeys(content, [{id: "box", time: 0}], -1, 10)).toBeNull();
  });
  it("未手改时记录采样姿态，手改后记录修改的姿态", () => {
    const s = {...shot("cam"), easing: "linear" as const};
    expect(frameForObject(box, s, 1, false).position).toEqual([1, 0, 0]);
    expect(frameForObject({...box, position: [9, 0, 0]}, s, 1, true).position).toEqual([9, 0, 0]);
  });
});
