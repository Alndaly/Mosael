/**
 * 画面代理按 Range 分块读:一小时的代理,看第 30 分钟只取那附近几个 GOP;顺着播,缓存按这份代理
 * 自己的码率封顶。此前每个片段都整份 `fetch` 一遍代理、整份常驻内存。
 *
 * 样本表换成合成的「一小时、每秒一个 GOP」(真文件解析见 mp4Index.test.ts);RangeReader 与取数、
 * 缓存逻辑都是真的,fetch 是一个按 Range 回字节的假服务端。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./mp4Index", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./mp4Index")>();
  return { ...actual, readTrackIndex: vi.fn() };
});

import { readTrackIndex, type SampleRef, type TrackIndex } from "./mp4Index";
import { ProxyMedia } from "./ProxyVideoSource";

const FPS = 30;
const SAMPLE_BYTES = 8 * 1024; // 30 帧 × 8KB ≈ 2Mbps,720p 代理的量级
const HOUR = 3600;
const MOOV_END = 1024 * 1024;

function hourLongIndex(): TrackIndex {
  const samples: SampleRef[] = [];
  for (let i = 0; i < HOUR * FPS; i++) {
    samples.push({ offset: MOOV_END + i * SAMPLE_BYTES, size: SAMPLE_BYTES, time: i / FPS, duration: 1 / FPS, sync: i % FPS === 0 });
  }
  return { codec: "avc1.64001f", samples, width: 1280, height: 720, sampleRate: 0, channels: 0 };
}

let requested: { start: number; end: number }[] = [];
beforeEach(() => {
  requested = [];
  vi.mocked(readTrackIndex).mockResolvedValue(hourLongIndex());
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      const range = (init?.headers as Record<string, string> | undefined)?.Range ?? "";
      const match = /bytes=(\d+)-(\d+)/.exec(range)!;
      const start = Number(match[1]);
      const end = Number(match[2]) + 1;
      requested.push({ start, end });
      return new Response(new Uint8Array(end - start), { status: 206 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const requestedBytes = () => requested.reduce((sum, r) => sum + (r.end - r.start), 0);

async function sampleWhenLoaded(media: ProxyMedia, i: number): Promise<Uint8Array> {
  let data = media.sampleData(i);
  await vi.waitFor(() => {
    data = media.sampleData(i);
    expect(data).not.toBeNull();
  });
  return data!;
}

describe("画面代理按 GOP 取字节", () => {
  it("一小时的代理,跳到第 30 分钟:只取那附近几个 GOP,不碰整份文件", async () => {
    const media = new ProxyMedia("/proxy");
    await media.ready;
    const i = 1800 * FPS + 7;
    const data = await sampleWhenLoaded(media, i);
    expect(data.byteLength).toBe(SAMPLE_BYTES);

    const gopBytes = FPS * SAMPLE_BYTES;
    // 当前 GOP + 往前预取的两个。
    expect(requestedBytes()).toBeLessThanOrEqual(3 * gopBytes);
    expect(Math.min(...requested.map((r) => r.start))).toBe(MOOV_END + 1800 * FPS * SAMPLE_BYTES);
    // 整份是 ~844MB。
    expect(requestedBytes()).toBeLessThan((HOUR * FPS * SAMPLE_BYTES) / 1000);
  });

  it("顺着播两分钟:缓存按这份代理的码率封顶(约 30 秒的内容),不随播放时长增长", async () => {
    const media = new ProxyMedia("/proxy");
    await media.ready;
    for (let second = 0; second < 120; second++) await sampleWhenLoaded(media, second * FPS);
    const bytesPerSecond = FPS * SAMPLE_BYTES;
    const indexEstimate = HOUR * FPS * 64;
    // 30 秒 × 码率 = 7.2MB,低于下限 8MB,按下限算;再加一个刚取回、还没来得及挤掉的 GOP 的余量。
    expect(media.retainedBytes - indexEstimate).toBeLessThanOrEqual(8 * 1024 * 1024 + 3 * bytesPerSecond);
    expect(requestedBytes()).toBeGreaterThan(100 * bytesPerSecond);
  });

  it("读不出样本表:判为这里解不了(ok=false),而不是整份下载兜底", async () => {
    vi.mocked(readTrackIndex).mockRejectedValueOnce(new Error("no moov"));
    const media = new ProxyMedia("/proxy");
    await media.ready;
    expect(media.ok).toBe(false);
    expect(media.sampleData(0)).toBeNull();
  });
});
