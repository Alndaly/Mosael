/**
 * 下载页面里的视频:受保护的不给下;下载任务的产出从哪儿取。
 */
import { expect, it } from "vitest";

import { downloadable, jobAssetId } from "./videoActions";

it("受保护的视频不给下载;下载任务的产出从 result.asset_ids 里取", () => {
  expect(downloadable({ protection: "encrypted" } as never)).toBe(false);
  expect(downloadable({ protection: null } as never)).toBe(true);
  expect(jobAssetId({ result: { asset_ids: ["a1"] } } as never)).toBe("a1");
  expect(jobAssetId({ result: {} } as never)).toBeNull();
});
