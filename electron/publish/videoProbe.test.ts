/**
 * 视频探测:分类(直链 / HLS / DASH)、加密识别、候选合成,以及在本地静态测试页(fixtures/page-tools)上跑探测脚本。
 *
 * | 页面 | 期望 |
 * | --- | --- |
 * | direct.html | 一条直链 mp4,可下载 |
 * | hls.html | 一条 HLS 清单,未加密,可下载 |
 * | hls-locked.html | HLS 清单带 `#EXT-X-KEY`(AES-128):加密**但可导入**(导入时 yt-dlp 解) |
 * | none.html | 没有视频 |
 * | drm.html | 播放器挂了 ClearKey 的 MediaKeys(EME):受 DRM 保护 |
 *
 * 加密和受保护**不是一回事**:`METHOD=AES-128`(标准密钥)yt-dlp 能解,页面面板要说「可导入」;
 * 其余方法(SAMPLE-AES / SAMPLE-AES-CTR / FairPlay 的 KEYFORMAT…)是真 DRM,仍然受保护。
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
  hlsKeyKind,
  hlsProtection,
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
  const AES_128 = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXTINF:2,\na.ts';
  const FAIRPLAY = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://x",KEYFORMAT="com.apple.streamingkeydelivery"';
  const WIDEVINE = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES-CTR,URI="data:x",KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"';

  it("AES-128:加密但可导入,不是「受保护」", () => {
    // 后端交给 yt-dlp,AES-128 它自己解 —— 页面扫描不该判成下不了。KEYFORMAT=identity 是标准密钥。
    expect(hlsKeyKind(AES_128)).toBe("aes128");
    expect(hlsProtection(AES_128)).toBe("encrypted");
    expect(hlsProtection('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k",KEYFORMAT="identity"')).toBe("encrypted");
  });

  it("不是 AES-128 的一律受保护(这条守卫不许放宽)", () => {
    // FairPlay / Widevine / SAMPLE-AES:标准 AES-128 之外的钥匙,yt-dlp 解不了,也不能假装能。
    expect(hlsKeyKind(FAIRPLAY)).toBe("drm");
    expect(hlsProtection(FAIRPLAY)).toBe("drm");
    expect(hlsProtection(WIDEVINE)).toBe("drm");
    expect(hlsProtection('#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="data:x"')).toBe("drm");
    // 名义上写 AES-128、钥匙却是 FairPlay 的 —— 不是普通 AES-128。
    expect(hlsProtection('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="skd://x",KEYFORMAT="com.apple.streamingkeydelivery"')).toBe("drm");
    // 认不出的写法(没有 METHOD、AES-256):不猜,按受保护算。
    expect(hlsProtection("#EXTM3U\n#EXT-X-KEY:BOGUS")).toBe("drm");
    expect(hlsProtection('#EXTM3U\n#EXT-X-KEY:METHOD=AES-256,URI="k"')).toBe("drm");
  });

  it("METHOD=NONE / 没有 KEY:普通,可下载(回归)", () => {
    expect(hlsKeyKind("#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n#EXTINF:2,\na.ts")).toBe("none");
    expect(hlsProtection("#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n#EXTINF:2,\na.ts")).toBeNull();
    expect(hlsProtection("#EXTM3U\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST")).toBeNull();
  });

  it("同一份清单里既有 AES-128 又有 DRM 钥匙:按受保护算", () => {
    expect(hlsProtection('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://x"')).toBe("drm");
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
    expect(hlsProtection(readFileSync(join(FIXTURES, "stream", "index.m3u8"), "utf8"))).toBeNull();
  });

  it("加密 HLS:AES-128 的清单标成「可导入(加密)」", () => {
    const result = probe("hls-locked.html");
    expect(result.candidates.map((one) => one.kind)).toEqual(["hls"]);
    const manifest = readFileSync(join(FIXTURES, "locked", "index.m3u8"), "utf8");
    expect(hlsKeyKind(manifest)).toBe("aes128");
    expect(hlsProtection(manifest)).toBe("encrypted");
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
