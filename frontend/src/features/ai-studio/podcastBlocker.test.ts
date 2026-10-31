import { describe, expect, it } from "vitest";

import { MAX_TURN_CHARS } from "@/features/ai-studio/podcastScript";
import { podcastBlocker, type PodcastDraft } from "@/features/ai-studio/voicedCreation";

/**
 * 播客那一下为什么交不出去。发送键的 disabled 和悬停说明都只看这个答案(见 GenerateWorkspace 的 submitBlocker),
 * 所以每一种灰着的情况都要能说出一句对应的话,而不是只有「点不了」。
 */
function draft(over: Partial<PodcastDraft>): PodcastDraft {
  return { mode: "summarize", turns: [{ speaker: 0, text: "" }], pair: ["a", "b"], ...over } as PodcastDraft;
}

describe("podcastBlocker", () => {
  it("引擎还没配好:先说引擎", () => {
    expect(podcastBlocker(draft({}), "聊聊", { ready: false } as never)).toBe("createEngineNotReady");
  });

  it("照稿念:看稿子和第一位发音人", () => {
    const read = (turns: PodcastDraft["turns"], pair: PodcastDraft["pair"] = ["a", ""]) =>
      podcastBlocker(draft({ mode: "read", turns, pair }), "", undefined);

    expect(read([{ speaker: 0, text: "  " }])).toBe("podcastBlockedEmptyScript");
    expect(read([{ speaker: 0, text: "字".repeat(MAX_TURN_CHARS + 1) }])).toBe("podcastBlockedTurnTooLong");
    expect(read([{ speaker: 0, text: "开场" }], ["", ""])).toBe("podcastBlockedPickSpeaker");
    expect(read([{ speaker: 0, text: "开场" }])).toBeNull();
  });

  it("提炼、调研:要一段字和两位不同的发音人", () => {
    expect(podcastBlocker(draft({}), "  ", undefined)).toBe("podcastBlockedNeedsTopic");
    expect(podcastBlocker(draft({ pair: ["a", ""] }), "聊聊", undefined)).toBe("podcastBlockedPickTwoSpeakers");
    expect(podcastBlocker(draft({ pair: ["a", "a"] }), "聊聊", undefined)).toBe("podcastBlockedSameSpeakers");
    expect(podcastBlocker(draft({}), "聊聊", undefined)).toBeNull();
  });
});
