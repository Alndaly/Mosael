/**
 * 屏幕 + 麦克风混成一条轨。MediaRecorder 一个流只认一条音轨,所以混音必须在开始录之前做完。
 */
import { describe, expect, it, vi } from "vitest";

import { mixAudioTracks } from "./audioMix";

function stream(kind: "audio" | "video", live = true): MediaStream {
  const track = {
    kind,
    readyState: live ? "live" : "ended",
    stop: vi.fn(),
  } as unknown as MediaStreamTrack;
  return { getAudioTracks: () => (kind === "audio" ? [track] : []), getVideoTracks: () => (kind === "video" ? [track] : []) } as unknown as MediaStream;
}

function fakeContext() {
  const destination = { stream: stream("audio") };
  const disconnect = vi.fn();
  const connect = vi.fn();
  return {
    destination,
    disconnect,
    connect,
    createMediaStreamSource: vi.fn(() => ({ connect, disconnect })),
    createMediaStreamDestination: vi.fn(() => destination),
    close: vi.fn(async () => undefined),
    resume: vi.fn(async () => undefined),
  };
}

describe("mixAudioTracks", () => {
  it("系统声音 + 麦克风:两路都接进同一条输出轨", () => {
    const context = fakeContext();
    const mixed = mixAudioTracks(stream("audio"), stream("audio"), () => context);
    expect(mixed).not.toBeNull();
    expect(context.createMediaStreamSource).toHaveBeenCalledTimes(2);
    expect(context.createMediaStreamDestination).toHaveBeenCalledTimes(1);
    expect(context.connect).toHaveBeenCalledTimes(2);
    expect(mixed!.stream).toBe(context.destination.stream);
    mixed!.release();
    expect(context.disconnect).toHaveBeenCalledTimes(2);
    expect(context.close).toHaveBeenCalled();
  });

  it("只有一路时不必混,直接用它(也少一次重采样)", () => {
    const context = fakeContext();
    const microphone = stream("audio");
    const mixed = mixAudioTracks(null, microphone, () => context);
    expect(mixed!.stream).toBe(microphone);
    expect(context.createMediaStreamDestination).not.toHaveBeenCalled();
    mixed!.release();
  });

  it("两路都空 / 都不活:返回 null,让调用方保持原样(混音失败不该让整次录制失败)", () => {
    expect(mixAudioTracks(null, null)).toBeNull();
    expect(mixAudioTracks(stream("audio", false), null)).toBeNull();
    //: 运行时没有 Web Audio 时同样返回 null,而不是抛。
    expect(mixAudioTracks(stream("audio"), stream("audio"), () => null)).toBeNull();
  });
});
