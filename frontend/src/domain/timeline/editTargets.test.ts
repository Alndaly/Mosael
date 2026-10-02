import { describe, expect, it } from "vitest";

import { adjacentEditPoint, editPoints, splitPointAt, splitPointsAcrossTracks } from "./editTargets";

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
