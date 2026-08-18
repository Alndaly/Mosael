import { describe, expect, it } from "vitest";
import type { Asset } from "@/api/client";
import { assetPreviewState, blockingPreviewState } from "@/features/editor/playback/previewReadiness";

const asset = (id: string, kind: string, proxy?: string): Asset =>
  ({ id, kind, media_info: proxy === undefined ? {} : { proxy_status: proxy } }) as unknown as Asset;

const none: ReadonlySet<string> = new Set();

describe("assetPreviewState", () => {
  it("图片永远可画:不经代理与解码器", () => {
    expect(assetPreviewState(asset("i", "image"), none)).toBe("ready");
    // 图片就算带着一个失败的代理状态也不受影响(代理只为视频而建)。
    expect(assetPreviewState(asset("i", "image", "failed"), none)).toBe("ready");
  });

  it("代理就绪的视频可画", () => {
    expect(assetPreviewState(asset("v", "video", "ready"), none)).toBe("ready");
  });

  it("本机解不动压过后端的 ready —— ready 只说明文件在,不说明这台机器放得了", () => {
    expect(assetPreviewState(asset("v", "video", "ready"), new Set(["v"]))).toBe("undecodable");
  });

  it("后端转码失败要报 failed(可重试)", () => {
    expect(assetPreviewState(asset("v", "video", "failed"), none)).toBe("failed");
  });

  it("pending / 缺失 / 未知状态一律当转码中", () => {
    expect(assetPreviewState(asset("v", "video", "pending"), none)).toBe("transcoding");
    expect(assetPreviewState(asset("v", "video"), none)).toBe("transcoding");
    // 未知值当「等一会儿」而不是「出错了」:显示成错误会让用户去点一个其实不需要的重试。
    expect(assetPreviewState(asset("v", "video", "who-knows"), none)).toBe("transcoding");
  });
});

describe("blockingPreviewState", () => {
  it("全部就绪返回 null", () => {
    expect(blockingPreviewState([asset("i", "image"), asset("v", "video", "ready")], none)).toBeNull();
  });

  it("空集合(画面上没有东西)不算被挡住", () => {
    expect(blockingPreviewState([], none)).toBeNull();
  });

  it("能动手的错误优先于只需等待", () => {
    const got = blockingPreviewState([asset("a", "video", "pending"), asset("b", "video", "failed")], none);
    expect(got?.state).toBe("failed");
    expect(got?.assets.map((a) => a.id)).toEqual(["b"]);
  });

  it("undecodable 比 failed 更具体,优先报它", () => {
    const got = blockingPreviewState(
      [asset("a", "video", "failed"), asset("b", "video", "ready")],
      new Set(["b"]),
    );
    expect(got?.state).toBe("undecodable");
    expect(got?.assets.map((a) => a.id)).toEqual(["b"]);
  });

  it("同一状态的素材全部带出来,便于逐个重试", () => {
    const got = blockingPreviewState([asset("a", "video", "pending"), asset("b", "video", "pending")], none);
    expect(got?.state).toBe("transcoding");
    expect(got?.assets.map((a) => a.id)).toEqual(["a", "b"]);
  });
});

describe("代理还没转好时,别说「本机无法解码」", () => {
  it("代理在转 + 解码失败 → 说的是「转码中」", () => {
    // 真机反馈:新建时间线、拖进刚导入的素材,监视器上默认就是「本机无法解码这个素材」。
    // 合成器对任何视频片段都会去取代理 URL,代理还没生成时那是个 404 —— 它说的是"文件
    // 还没好",不是"这台机器缺编解码器"。而后者还配着一个「重新生成代理」按钮,
    // 等于请用户去重做一件正在做的事。
    expect(assetPreviewState(asset("v", "video", "pending"), new Set(["v"]))).toBe("transcoding");
    expect(assetPreviewState(asset("v", "video", undefined), new Set(["v"]))).toBe("transcoding");
  });

  it("后端转码失败 + 解码失败 → 说的是后端那一条,它更靠上游", () => {
    expect(assetPreviewState(asset("v", "video", "failed"), new Set(["v"]))).toBe("failed");
  });

  it("代理已就绪 + 解码失败 → 这才真是「本机解不动」", () => {
    expect(assetPreviewState(asset("v", "video", "ready"), new Set(["v"]))).toBe("undecodable");
  });
});
