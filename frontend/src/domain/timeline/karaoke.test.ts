import { describe, expect, it } from "vitest";

import { tokenTimelineRange } from "./karaoke";

/**
 * 「正在播的那个词」不该靠"猜哪个片段是当前片段"来定。
 *
 * 此前的做法:遍历所有片段,取**第一个**时间上覆盖播放头的,再拿它的 id 去和句子比对。
 * 而视频轨和音频轨在时间上本来就是重叠的 —— 逐字稿来自音频片段(那段录音),而视频片段
 * 排在列表前面,于是"当前片段"永远命中视频那一个,和逐字稿对不上:要么一个词都不亮,
 * 要么在多片段共用同一个素材时亮错行。
 *
 * 判据换个方向:**不问"当前是哪个片段",而是问"这个词落在时间线的哪一段"**。
 * 词自己知道它属于哪个片段、在源时间的哪个位置,映回时间线是确定的一步。
 */

const clip = { id: "c1", asset_id: "a1", timeline_start: 10, src_in: 4, src_out: 14, speed: 1 };

describe("tokenTimelineRange", () => {
  it("把词的源时间映到时间线上", () => {
    expect(tokenTimelineRange(clip, { start_time: 5, end_time: 6 })).toEqual([11, 12]);
  });

  it("倍速片段里,源里的一秒不是时间线上的一秒", () => {
    const fast = { ...clip, speed: 2 };
    expect(tokenTimelineRange(fast, { start_time: 6, end_time: 8 })).toEqual([11, 12]);
  });

  it("片段不在了就没有位置可言 —— 不编一个 0", () => {
    expect(tokenTimelineRange(undefined, { start_time: 5, end_time: 6 })).toBeNull();
  });

  it("重叠的轨道不再互相干扰:同一时刻,只有真正落在那儿的词才算当前", () => {
    // 视频片段 c1 覆盖 10–20,音频片段 c2 也覆盖 10–20,而逐字稿属于 c2。
    const audio = { id: "c2", asset_id: "a2", timeline_start: 10, src_in: 0, src_out: 10, speed: 1 };
    const [start, end] = tokenTimelineRange(audio, { start_time: 3, end_time: 4 })!;

    expect(start).toBe(13);
    expect(end).toBe(14);
  });
});
