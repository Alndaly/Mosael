/**
 * 代理文件的样本表:按 Range 读开头解析出来,之后只取要解的那几个样本的字节。
 *
 * 用两份 ffmpeg 生成的真代理(proxyFixtures.ts),不是桩 —— 偏移、关键帧、编辑列表的预延迟都要和
 * 真文件对得上。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { RangeReader, byteSpan, readTrackIndex, sampleIndexAt } from "./mp4Index";
import { TINY_AUDIO_PROXY, TINY_VIDEO_PROXY } from "./proxyFixtures";

/** 按 Range 回 206 的文件服务;`honourRange: false` 模拟不认 Range 的服务端(回 200 整份)。 */
function serve(file: Uint8Array, { honourRange = true } = {}) {
  const ranges: string[] = [];
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const range = (init?.headers as Record<string, string> | undefined)?.Range ?? "";
    ranges.push(range);
    if (!honourRange) return new Response(file.slice(), { status: 200 });
    const match = /bytes=(\d+)-(\d+)/.exec(range);
    if (!match) return new Response(file.slice(), { status: 200 });
    const start = Number(match[1]);
    if (start >= file.byteLength) return new Response(null, { status: 416 });
    return new Response(file.slice(start, Math.min(Number(match[2]) + 1, file.byteLength)), { status: 206 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { ranges, fetchMock };
}

afterEach(() => vi.unstubAllGlobals());

describe("音频代理的样本表", () => {
  it("AAC 48k 立体声;时间扣掉了编码器预延迟(编辑列表),样本首尾相接", async () => {
    serve(TINY_AUDIO_PROXY);
    const index = await readTrackIndex(new RangeReader("/a"), "audio");
    expect(index.codec).toBe("mp4a.40.2");
    expect(index.sampleRate).toBe(48000);
    expect(index.channels).toBe(2);
    expect(index.description?.byteLength).toBeGreaterThan(0);
    // 第一个 AAC 帧是预延迟:展示时间 -1024/48000,第二帧从 0 开始。
    expect(index.samples[0].time).toBeCloseTo(-1024 / 48000, 6);
    expect(index.samples[1].time).toBeCloseTo(0, 6);
    for (let i = 1; i < index.samples.length; i++) {
      expect(index.samples[i].time).toBeCloseTo(index.samples[i - 1].time + index.samples[i - 1].duration, 6);
    }
    const span = byteSpan(index.samples, 0, index.samples.length - 1);
    expect(span.end).toBeLessThanOrEqual(TINY_AUDIO_PROXY.byteLength);
  });
});

describe("画面代理的样本表", () => {
  it("H.264、尺寸、每 3 帧一个关键帧;按时间二分找到覆盖它的样本", async () => {
    serve(TINY_VIDEO_PROXY);
    const index = await readTrackIndex(new RangeReader("/v"), "video");
    expect(index.codec.startsWith("avc1")).toBe(true);
    expect([index.width, index.height]).toEqual([64, 64]);
    expect(index.samples.length).toBe(6);
    expect(index.samples.map((s) => s.sync)).toEqual([true, false, false, true, false, false]);
    expect(index.description?.byteLength).toBeGreaterThan(0);
    expect(sampleIndexAt(index.samples, 0.25)).toBe(2);
    expect(sampleIndexAt(index.samples, -1)).toBe(0);
  });

  it("样本字节按 Range 取到的和整份文件里的一模一样", async () => {
    serve(TINY_VIDEO_PROXY);
    const reader = new RangeReader("/v");
    const index = await readTrackIndex(reader, "video");
    const span = byteSpan(index.samples, 3, 5);
    const bytes = await reader.read(span.start, span.end);
    expect([...bytes]).toEqual([...TINY_VIDEO_PROXY.subarray(span.start, span.end)]);
  });
});

describe("RangeReader", () => {
  it("服务端不认 Range(回 200 整份):只下一次,之后都从内存里切", async () => {
    const { fetchMock } = serve(TINY_VIDEO_PROXY, { honourRange: false });
    const reader = new RangeReader("/v");
    const index = await readTrackIndex(reader, "video");
    const span = byteSpan(index.samples, 0, 2);
    const bytes = await reader.read(span.start, span.end);
    expect([...bytes]).toEqual([...TINY_VIDEO_PROXY.subarray(span.start, span.end)]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(reader.retainedBytes).toBe(TINY_VIDEO_PROXY.byteLength);
  });

  it("不是代理(读不出 moov):报错,而不是一路把整份文件读下去", async () => {
    serve(new Uint8Array(1024));
    await expect(readTrackIndex(new RangeReader("/x"), "video")).rejects.toThrow();
  });
});
