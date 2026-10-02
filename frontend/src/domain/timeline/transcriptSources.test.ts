import { describe, expect, it } from "vitest";

import type { Track } from "@/api/client";
import { transcriptSourceClips } from "@/domain/timeline/transcriptSources";

const clip = (id: string, asset: string, extra: Record<string, unknown> = {}) => ({
  id, asset_id: asset, asset_kind: "video", asset_source: "imported", timeline_start: 0, src_in: 0, src_out: 10, speed: 1, ...extra,
});

describe("逐字稿看哪些片段", () => {
  it("不算配音轨、不算分离出来的人声/背景音,同一段素材在视频轨和分离音频上只算一份", () => {
    const tracks = [
      { id: "v1", kind: "video", role: "", clips: [clip("video", "footage", { muted: true })] },
      { id: "a1", kind: "audio", role: "", clips: [clip("detached", "footage", { asset_kind: "video" })] },
      { id: "a2", kind: "audio", role: "", clips: [clip("stem", "bg", { asset_kind: "audio", asset_source: "separated" })] },
      { id: "dub", kind: "audio", role: "dub", clips: [clip("voice", "tts1", { asset_kind: "audio", asset_source: "tts" })] },
      { id: "a3", kind: "audio", role: "", clips: [clip("narration", "vo", { asset_kind: "audio", timeline_start: 12 })] },
    ] as unknown as Track[];
    expect(transcriptSourceClips(tracks).map((one) => one.id)).toEqual(["video", "narration"]);
  });

  it("同一素材用在不同位置的两段都算(那是两次出现,不是重复)", () => {
    const tracks = [
      { id: "v1", kind: "video", role: "", clips: [clip("a", "footage"), clip("b", "footage", { timeline_start: 10, src_in: 20, src_out: 30 })] },
    ] as unknown as Track[];
    expect(transcriptSourceClips(tracks).map((one) => one.id)).toEqual(["a", "b"]);
  });
});
