import { describe, expect, it } from "vitest";

import { adjacentClip, adjacentEditPoint, editPoints, rippleTrimCuts, splitPointAt, splitPointsAcrossTracks } from "./editTargets";

const clip = (id: string, start: number, srcIn: number, srcOut: number, speed = 1) => ({
  id,
  timeline_start: start,
  src_in: srcIn,
  src_out: srcOut,
  speed,
});

describe("播放头上切谁", () => {
  const tracks = [
    { id: "V2", locked: true, clips: [clip("locked", 0, 0, 10)] },
    { id: "V1", clips: [clip("a", 0, 0, 4), clip("b", 4, 10, 30, 2)] },
    { id: "A1", clips: [clip("music", 0, 0, 20)] },
  ];

  it("跳过锁定的轨,按速度换成源时刻", () => {
    expect(splitPointAt(tracks, 6)).toEqual({ clipId: "b", srcTime: 14 });
  });

  it("指定了轨就只在那条轨上找(选中的片段被前一刀切开后 id 已经换了)", () => {
    expect(splitPointAt(tracks, 6, "A1")).toEqual({ clipId: "music", srcTime: 6 });
  });

  it("落在边缘上不切", () => {
    expect(splitPointAt(tracks, 4, "V1")).toBeNull();
  });

  it("⇧⌘K:链接组只报一段(组员由后端在同一刻跟着切、左右各自配对)", () => {
    const linked = [
      { id: "V1", clips: [{ ...clip("picture", 0, 0, 10), link_group: "g" }] },
      { id: "A1", clips: [{ ...clip("sound", 0, 0, 10), link_group: "g" }, clip("other", 0, 0, 10)] },
    ];
    expect(splitPointsAcrossTracks(linked, 3).map((point) => point.clipId)).toEqual(["picture", "other"]);
  });

  it("⌘K:每条未锁定轨上播放头下的片段各一刀", () => {
    expect(splitPointsAcrossTracks(tracks, 2)).toEqual([
      { clipId: "a", srcTime: 2 },
      { clipId: "music", srcTime: 2 },
    ]);
  });
});

describe("编辑点(↑ / ↓ 跳转)", () => {
  const tracks = [
    { id: "V1", clips: [clip("a", 0, 0, 4), clip("b", 6, 0, 2)] },
    { id: "A1", clips: [clip("m", 1, 0, 10, 2)] },
  ];

  it("所有轨上片段的头尾,去重排好", () => {
    expect(editPoints(tracks)).toEqual([0, 1, 4, 6, 8]);
  });

  it("往前 / 往后跳到最近的编辑点;正停在某一点上时跳过它", () => {
    const points = editPoints(tracks);
    expect(adjacentEditPoint(points, 5, 1)).toBe(6);
    expect(adjacentEditPoint(points, 5, -1)).toBe(4);
    expect(adjacentEditPoint(points, 4, 1)).toBe(6);
    expect(adjacentEditPoint(points, 4.001, -1, 0.01)).toBe(1);
    expect(adjacentEditPoint(points, 8, 1)).toBeNull();
    expect(adjacentEditPoint(points, 0, -1)).toBeNull();
  });
});

describe("Q / W 波纹修剪到播放头", () => {
  const tracks = [
    { id: "V1", clips: [clip("a", 0, 0, 4), clip("b", 6, 0, 2)] },
    { id: "V2", locked: true, clips: [clip("locked", 0, 0, 10)] },
    { id: "A1", clips: [clip("m", 1, 0, 20, 2)] },
  ];

  it("Q:剪掉上一个编辑点到播放头这一段,所有目标轨剪同样长(各轨保持同步)", () => {
    // 目标轨上的边缘:V1 的 0 / 4 / 6 / 8,A1 的 1 / 11;播放头 2 之前最近的是 1。
    expect(rippleTrimCuts(tracks, 2, "start", [])).toEqual({
      from: 1,
      to: 2,
      cuts: [
        { clipId: "a", srcStart: 1, srcEnd: 2 },
        { clipId: "m", srcStart: 0, srcEnd: 2 },
      ],
    });
  });

  it("W:剪掉播放头到下一个编辑点这一段", () => {
    expect(rippleTrimCuts(tracks, 2, "end", [])).toEqual({
      from: 2,
      to: 4,
      cuts: [
        { clipId: "a", srcStart: 2, srcEnd: 4 },
        { clipId: "m", srcStart: 2, srcEnd: 6 },
      ],
    });
  });

  it("选中的片段压在播放头上时,只动选中的那几条轨", () => {
    expect(rippleTrimCuts(tracks, 2, "start", ["m"])).toEqual({
      from: 1,
      to: 2,
      cuts: [{ clipId: "m", srcStart: 0, srcEnd: 2 }],
    });
  });

  it("播放头下没有片段:不剪", () => {
    expect(rippleTrimCuts(tracks, 30, "start", [])).toBeNull();
  });
});

describe("键盘移动选中(⌥ + 方向键)", () => {
  const tracks = [
    { id: "V2", clips: [clip("title", 3, 0, 2)] },
    { id: "V1", clips: [clip("b", 5, 0, 5), clip("a", 0, 0, 5)] },
    { id: "A1", clips: [] },
    { id: "A2", clips: [clip("music", 0, 0, 20)] },
  ];

  it("左右:同一轨上按时间顺序的前一段 / 后一段(到头就停)", () => {
    expect(adjacentClip(tracks, "a", "right")).toBe("b");
    expect(adjacentClip(tracks, "b", "left")).toBe("a");
    expect(adjacentClip(tracks, "b", "right")).toBeNull();
  });

  it("上下:相邻那条有片段的轨上,时间上最接近的一段(空轨跳过)", () => {
    expect(adjacentClip(tracks, "b", "up")).toBe("title");
    expect(adjacentClip(tracks, "a", "down")).toBe("music");
    expect(adjacentClip(tracks, "music", "up")).toBe("a");
    expect(adjacentClip(tracks, "title", "up")).toBeNull();
  });

  it("没有当前选中:从第一条轨的第一段开始", () => {
    expect(adjacentClip(tracks, null, "right")).toBe("title");
  });
});
