import { describe, expect, it } from "vitest";

import { splitPointAt, splitPointsAcrossTracks } from "./editTargets";

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
