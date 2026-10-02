/**
 * 音频代理按块解码:只取那一块的 AAC 帧(外加两帧预解)的字节,按输出时间戳把 PCM 摆进块里。
 *
 * 文件是 ffmpeg 生成的真音频代理(proxyFixtures.ts),Range 取数是真的;AudioDecoder 换成一个按输入
 * 时间戳吐「标了帧号的 PCM」的假解码器(jsdom 没有 WebCodecs),于是能看清每个采样从哪一帧来。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AudioProxySource, type DecoderFactory } from "./audioProxySource";
import { TINY_AUDIO_PROXY } from "./proxyFixtures";

class FakeEncodedAudioChunk {
  readonly type: string;
  readonly timestamp: number;
  readonly duration: number;
  readonly data: Uint8Array;
  constructor(init: { type: string; timestamp: number; duration: number; data: Uint8Array }) {
    this.type = init.type;
    this.timestamp = init.timestamp;
    this.duration = init.duration;
    this.data = init.data;
  }
}

let ranges: [number, number][] = [];
let decodedTimestamps: number[] = [];
beforeEach(() => {
  ranges = [];
  decodedTimestamps = [];
  vi.stubGlobal("EncodedAudioChunk", FakeEncodedAudioChunk);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      const range = (init?.headers as Record<string, string> | undefined)?.Range ?? "";
      const match = /bytes=(\d+)-(\d+)/.exec(range)!;
      const start = Number(match[1]);
      const end = Math.min(Number(match[2]) + 1, TINY_AUDIO_PROXY.byteLength);
      ranges.push([start, end]);
      if (start >= TINY_AUDIO_PROXY.byteLength) return new Response(null, { status: 416 });
      return new Response(TINY_AUDIO_PROXY.slice(start, end), { status: 206 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

/** 每个输入帧吐 1024 个采样,值 = 这一帧的时间戳(微秒),左右声道一样。 */
const markingDecoder: DecoderFactory = (_config, onOutput) => {
  const queued: FakeEncodedAudioChunk[] = [];
  return {
    decode: (chunk) => queued.push(chunk as unknown as FakeEncodedAudioChunk),
    flush: async () => {
      for (const chunk of queued) {
        decodedTimestamps.push(chunk.timestamp);
        onOutput({
          timestamp: chunk.timestamp,
          numberOfFrames: 1024,
          numberOfChannels: 2,
          copyTo: (dest: Float32Array) => dest.fill(chunk.timestamp),
          close: () => undefined,
        } as unknown as AudioData);
      }
    },
    close: () => undefined,
  };
};

describe("音频代理按块解码", () => {
  it("一块 = 从块头起的 PCM;块头之前的预解帧被切掉,采样按输出时间戳就位", async () => {
    const source = new AudioProxySource("/a", markingDecoder);
    await source.ready;
    source.request(0);
    await vi.waitFor(() => expect(source.chunk(0)).not.toBeNull());
    const chunk = source.chunk(0)!;
    // 素材 0.5s:第 0 块就是整段,48k。
    expect(chunk.sampleRate).toBe(48000);
    expect(chunk.frames).toBe(Math.round(source.duration * 48000));
    expect(chunk.channels).toHaveLength(2);
    // 第一个 AAC 帧是编码器预延迟(时间 -21.3ms):它的采样落在块头之前,被切掉。块的第 0 个采样
    // 来自时间戳 0 的那一帧,第 1024 个来自下一帧(21333µs)。
    expect(decodedTimestamps[0]).toBe(Math.round((-1024 / 48000) * 1e6));
    expect(chunk.channels[0][0]).toBe(0);
    expect(chunk.channels[0][1024]).toBe(Math.round((1024 / 48000) * 1e6));
    expect(chunk.channels[1][1024]).toBe(chunk.channels[0][1024]);
  });

  it("超出素材长度的块是空的,不发请求也不出错", async () => {
    const source = new AudioProxySource("/a", markingDecoder);
    await source.ready;
    const before = ranges.length;
    source.request(5);
    await vi.waitFor(() => expect(source.chunk(5)).not.toBeNull());
    expect(source.chunk(5)!.frames).toBe(0);
    expect(ranges.length).toBe(before);
    expect(source.ok).toBe(true);
  });

  it("解码器不可用 / 解坏了:整份记成 ok=false,之后不再取、不再解", async () => {
    const source = new AudioProxySource("/a", () => null);
    await source.ready;
    source.request(0);
    await vi.waitFor(() => expect(source.ok).toBe(false));
    const after = ranges.length;
    source.request(0);
    source.request(1);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(ranges.length).toBe(after);
  });

  it("放掉用不到的块:只留 keep 里的和最近用过的几块", async () => {
    const source = new AudioProxySource("/a", markingDecoder);
    await source.ready;
    // 素材只有 0.5s,只有第 0 块有内容;后面几块是空块,也照样占位、照样能被放掉。
    for (const k of [0, 1, 2, 3]) source.request(k);
    await vi.waitFor(() => expect(source.chunk(3)).not.toBeNull());
    source.retain(new Set([0]), 1);
    expect(source.chunk(0)).not.toBeNull();
    expect([1, 2, 3].filter((k) => source.chunk(k) !== null)).toHaveLength(1);
  });
});
