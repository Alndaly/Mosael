/**
 * 视频探测:分类(直链 / HLS / DASH)、加密识别、候选合成,以及在本地静态测试页(fixtures/page-tools)上跑探测脚本。
 *
 * | 页面 | 期望 |
 * | --- | --- |
 * | direct.html | 一条直链 mp4,可下载 |
 * | hls.html | 一条 HLS 清单,未加密,可下载 |
 * | hls-locked.html | HLS 清单带 `#EXT-X-KEY`(AES-128):受保护 |
 * | none.html | 没有视频 |
 * | drm.html | 播放器挂了 ClearKey 的 MediaKeys(EME):受 DRM 保护 |
 *
 * 真 Electron 里由页面自己的 ClearKey 脚本挂上 MediaKeys(见回报里的实跑步骤);jsdom 不实现 EME,由用例补上。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

import {
  VIDEO_SCAN_SCRIPT,
  classifyMedia,
  dashIsProtected,
  hlsFirstVariant,
  hlsIsEncrypted,
  mediaIdentity,
  mergeVideoCandidates,
  type PageVideoScan,
} from "./videoProbe";

const PAGE = { url: "https://example.com/watch", title: "Example" };

const FIXTURES = join(import.meta.dirname, "fixtures", "page-tools");
const ORIGIN = "http://127.0.0.1:47011";

/** 静态测试页装进 jsdom。jsdom 不加载媒体、不实现 EME、不解码图片 —— 这几样由用例按页面声明补上。 */
function open(name: string): JSDOM {
  return new JSDOM(readFileSync(join(FIXTURES, name), "utf8"), {
    url: `${ORIGIN}/${name}`,
    runScripts: "outside-only",
  });
}

function probe(name: string, prepare: (dom: JSDOM) => void = () => undefined) {
  const dom = open(name);
  prepare(dom);
  const scan = dom.window.eval(VIDEO_SCAN_SCRIPT) as PageVideoScan;
  return mergeVideoCandidates({ url: dom.window.location.href, title: dom.window.document.title }, [scan], []);
}

describe("视频分类", () => {
  it("认得直链、HLS、DASH(看响应类型,也看地址)", () => {
    expect(classifyMedia("https://cdn.example.com/a.mp4")).toBe("direct");
    expect(classifyMedia("https://cdn.example.com/play?id=1", "video/webm")).toBe("direct");
    expect(classifyMedia("https://cdn.example.com/live/index.m3u8?token=x")).toBe("hls");
    expect(classifyMedia("https://cdn.example.com/v", "application/vnd.apple.mpegurl; charset=utf-8")).toBe("hls");
    expect(classifyMedia("https://cdn.example.com/manifest.mpd")).toBe("dash");
  });

  it("分段流的分段不算一条视频(哪怕响应头写着 video/mp4)", () => {
    expect(classifyMedia("https://cdn.example.com/seg-12.m4s", "video/mp4")).toBeNull();
    expect(classifyMedia("https://cdn.example.com/segment0.ts", "video/mp2t")).toBeNull();
    expect(classifyMedia("https://cdn.example.com/video.mp4?range=0-1000", "video/mp4")).toBeNull();
  });

  it("不是 http(s) 的、不是视频的都不算", () => {
    expect(classifyMedia("blob:https://example.com/123")).toBeNull();
    expect(classifyMedia("https://example.com/page.html", "text/html")).toBeNull();
    expect(classifyMedia("https://example.com/data.json", "application/json")).toBeNull();
  });

  it("同一条视频按 Range 分段取的几个请求合成一条", () => {
    expect(mediaIdentity("https://cdn.example.com/a.mp4?bytes=0-99#t=3")).toBe(mediaIdentity("https://cdn.example.com/a.mp4"));
  });
});

describe("加密流识别", () => {
  it("HLS:#EXT-X-KEY 的 METHOD 不是 NONE 就是加密流,不分 AES-128 还是 SAMPLE-AES", () => {
    expect(hlsIsEncrypted('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXTINF:2,\na.ts')).toBe(true);
    expect(hlsIsEncrypted('#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://x",KEYFORMAT="com.apple.streamingkeydelivery"')).toBe(true);
    expect(hlsIsEncrypted('#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="data:x"')).toBe(true);
    expect(hlsIsEncrypted("#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n#EXTINF:2,\na.ts")).toBe(false);
    expect(hlsIsEncrypted("#EXTM3U\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST")).toBe(false);
  });

  it("HLS 主清单:找出第一条媒体清单(加密信息常常只写在那里)", () => {
    const master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nlow/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2000000\nhigh/index.m3u8";
    expect(hlsFirstVariant(master, "https://cdn.example.com/v/master.m3u8")).toBe("https://cdn.example.com/v/low/index.m3u8");
    expect(hlsFirstVariant("#EXTM3U\n#EXTINF:2,\na.ts", "https://cdn.example.com/v.m3u8")).toBeNull();
  });

  it("DASH:带 ContentProtection 就是 DRM", () => {
    expect(dashIsProtected('<MPD><Period><AdaptationSet><ContentProtection schemeIdUri="urn:uuid:edef8ba9"/></AdaptationSet></Period></MPD>')).toBe(true);
    expect(dashIsProtected("<MPD><Period><AdaptationSet><cenc:ContentProtection/></AdaptationSet></Period></MPD>")).toBe(true);
    expect(dashIsProtected("<MPD><Period><AdaptationSet/></Period></MPD>")).toBe(false);
  });
});

describe("合成视频候选", () => {
  const video = (srcs: string[], extra: Partial<{ encrypted: boolean; width: number; height: number }> = {}) => ({
    srcs,
    width: extra.width ?? 1280,
    height: extra.height ?? 720,
    duration: 12,
    encrypted: extra.encrypted ?? false,
  });

  it("直链:播放器在放的 mp4 是一条候选,网络里同一条的大小补上来", () => {
    const probe = mergeVideoCandidates(
      PAGE,
      [{ videos: [video(["https://cdn.example.com/a.mp4"])], meta: [] }],
      [{ url: "https://cdn.example.com/a.mp4", mime: "video/mp4", bytes: 1234 }],
    );
    expect(probe.candidates).toEqual([
      expect.objectContaining({ url: "https://cdn.example.com/a.mp4", kind: "direct", from: "element", bytes: 1234, width: 1280, protection: null }),
    ]);
    expect(probe.drm).toBe(false);
  });

  it("HLS:MSE 播放器挂的是 blob:,真正的清单从网络响应里来", () => {
    const probe = mergeVideoCandidates(
      PAGE,
      [{ videos: [video(["blob:https://example.com/1"])], meta: [] }],
      [
        { url: "https://cdn.example.com/live/index.m3u8", mime: "application/vnd.apple.mpegurl", bytes: 300 },
        { url: "https://cdn.example.com/live/seg1.ts", mime: "video/mp2t", bytes: 90000 },
      ],
    );
    expect(probe.candidates.map((one) => [one.kind, one.url])).toEqual([["hls", "https://cdn.example.com/live/index.m3u8"]]);
    expect(probe.streamOnly).toBe(false);
  });

  it("没有视频:候选为空;有 MSE 播放器却没看到地址时说「只有分段流」", () => {
    expect(mergeVideoCandidates(PAGE, [{ videos: [], meta: [] }], [])).toMatchObject({ candidates: [], drm: false, streamOnly: false });
    expect(mergeVideoCandidates(PAGE, [{ videos: [video(["blob:x"])], meta: [] }], [])).toMatchObject({ candidates: [], streamOnly: true });
  });

  it("DRM:播放器挂着 MediaKeys 时整页标成受 DRM 保护,它的地址也一并标上", () => {
    const probe = mergeVideoCandidates(
      PAGE,
      [{ videos: [video(["https://cdn.example.com/a.mp4"], { encrypted: true })], meta: [] }],
      [],
    );
    expect(probe.drm).toBe(true);
    expect(probe.candidates[0].protection).toBe("drm");
  });

  it("每个 frame 都算(播放器常在 iframe 里),og:video 也算", () => {
    const probe = mergeVideoCandidates(
      PAGE,
      [
        { videos: [], meta: ["https://cdn.example.com/og.mp4"] },
        { videos: [video(["https://player.example.net/v.webm"])], meta: [] },
      ],
      [],
    );
    expect(probe.candidates.map((one) => [one.from, one.url])).toEqual([
      ["meta", "https://cdn.example.com/og.mp4"],
      ["element", "https://player.example.net/v.webm"],
    ]);
  });
});

describe("视频探测(静态测试页)", () => {
  it("直链:找到那一条 mp4,地址补全成绝对地址", () => {
    const result = probe("direct.html");
    expect(result.candidates).toEqual([expect.objectContaining({ url: `${ORIGIN}/clip.mp4`, kind: "direct", protection: null })]);
    expect(result.drm).toBe(false);
  });

  it("HLS:<source> 里的清单认成 HLS;清单本身未加密", () => {
    const result = probe("hls.html");
    expect(result.candidates).toEqual([expect.objectContaining({ url: `${ORIGIN}/stream/index.m3u8`, kind: "hls" })]);
    expect(hlsIsEncrypted(readFileSync(join(FIXTURES, "stream", "index.m3u8"), "utf8"))).toBe(false);
  });

  it("加密 HLS:清单带 #EXT-X-KEY,认成加密流", () => {
    const result = probe("hls-locked.html");
    expect(result.candidates.map((one) => one.kind)).toEqual(["hls"]);
    expect(hlsIsEncrypted(readFileSync(join(FIXTURES, "locked", "index.m3u8"), "utf8"))).toBe(true);
  });

  it("无视频:候选为空", () => {
    expect(probe("none.html")).toMatchObject({ candidates: [], drm: false, streamOnly: false });
  });

  it("DRM:播放器挂着 MediaKeys,整页标成受保护", () => {
    const result = probe("drm.html", (dom) => {
      // 页面里的 ClearKey 脚本在真浏览器里做的事:给播放器挂上 MediaKeys。
      Object.defineProperty(dom.window.document.getElementById("player"), "mediaKeys", { value: {} });
    });
    expect(result.drm).toBe(true);
    expect(result.candidates[0]).toMatchObject({ url: `${ORIGIN}/clip.mp4`, protection: "drm" });
  });
});
