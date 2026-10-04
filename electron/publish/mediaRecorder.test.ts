/**
 * 媒体记录器:按会话挂一次观察钩子、按视图分桶,只记媒体类的响应,不记请求头。
 */
import { describe, expect, it } from "vitest";

import { MAX_RESPONSES_PER_VIEW, MediaRecorder } from "./mediaRecorder";

type Listener = (details: Record<string, unknown>) => void;

function fakeSession() {
  const calls: Array<{ filter: { urls: string[]; types?: string[] }; listener: Listener }> = [];
  return {
    calls,
    webRequest: {
      onResponseStarted(filter: { urls: string[]; types?: string[] }, listener: Listener) {
        calls.push({ filter, listener });
      },
    },
  };
}

const response = (url: string, type: string, extra: Record<string, unknown> = {}) => ({
  url,
  webContentsId: 7,
  statusCode: 200,
  responseHeaders: { "Content-Type": [type], "content-length": ["2048"], "Set-Cookie": ["sid=secret"] },
  ...extra,
});

describe("MediaRecorder", () => {
  it("watches a session once, only media and xhr requests", () => {
    const session = fakeSession();
    const recorder = new MediaRecorder();
    recorder.watch(session as never);
    recorder.watch(session as never);
    expect(session.calls).toHaveLength(1);
    expect(session.calls[0].filter.types).toEqual(["media", "xhr"]);
  });

  it("keeps media responses per view and nothing about the request beyond address, type and size", () => {
    const session = fakeSession();
    const recorder = new MediaRecorder();
    recorder.watch(session as never);
    const listener = session.calls[0].listener;
    listener(response("https://cdn.example.com/a.mp4", "video/mp4"));
    listener(response("https://cdn.example.com/live.m3u8", "application/vnd.apple.mpegurl", { webContentsId: 8 }));
    listener(response("https://api.example.com/feed.json", "application/json"));
    listener(response("https://cdn.example.com/b.mp4", "video/mp4", { statusCode: 403 }));
    expect(recorder.responses(7)).toEqual([{ url: "https://cdn.example.com/a.mp4", mime: "video/mp4", bytes: 2048 }]);
    expect(recorder.responses(8).map((one) => one.url)).toEqual(["https://cdn.example.com/live.m3u8"]);
    expect(JSON.stringify(recorder.responses(7))).not.toContain("secret");
    recorder.forget(7);
    expect(recorder.responses(7)).toEqual([]);
  });

  it("keeps only the most recent responses of a view", () => {
    const recorder = new MediaRecorder();
    for (let index = 0; index < MAX_RESPONSES_PER_VIEW + 10; index += 1) {
      recorder.record(1, { url: `https://cdn.example.com/${index}.mp4`, mime: "video/mp4", bytes: null });
    }
    const kept = recorder.responses(1);
    expect(kept).toHaveLength(MAX_RESPONSES_PER_VIEW);
    expect(kept.at(-1)?.url).toBe(`https://cdn.example.com/${MAX_RESPONSES_PER_VIEW + 9}.mp4`);
  });
});
