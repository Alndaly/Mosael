/**
 * 下载页面里的视频:**真 DRM 才不给下**;AES-128 加密的 HLS 能下(导入时 yt-dlp 解);
 * 下载任务的产出从哪儿取。
 */
import { expect, it } from "vitest";

import { downloadable, jobAssetId } from "./videoActions";

it("AES-128 加密的 HLS 可导入;真 DRM 不给下;没保护的照常", () => {
  // 加密 ≠ 不能下:标准 AES-128 的密钥 yt-dlp 会取、会解,页面面板说「可导入」才是事实。
  expect(downloadable({ protection: "encrypted" } as never)).toBe(true);
  // 守卫:Widevine / FairPlay / PlayReady 这类真 DRM 仍然不给 —— 这一条不许跟着放宽。
  expect(downloadable({ protection: "drm" } as never)).toBe(false);
  expect(downloadable({ protection: null } as never)).toBe(true);
});

it("下载任务的产出从 result.asset_ids 里取", () => {
  expect(jobAssetId({ result: { asset_ids: ["a1"] } } as never)).toBe("a1");
  expect(jobAssetId({ result: {} } as never)).toBeNull();
});
