import type { PublishTask } from "./types";
import { resolvePlatform } from "./platforms";
import type { PageDriver } from "./pageDriver";
import type { PublishAdapter } from "./adapters/shared";
import { MockAdapter } from "./adapters/mock";
import { DouyinAdapter } from "./adapters/douyin";
import { XiaohongshuAdapter } from "./adapters/xiaohongshu";
import { WeixinChannelsAdapter } from "./adapters/weixinChannels";
import { BilibiliAdapter } from "./adapters/bilibili";
import { TiktokAdapter } from "./adapters/tiktok";
import { YoutubeAdapter } from "./adapters/youtube";

export type { PublishAdapter } from "./adapters/shared";
export { MockAdapter } from "./adapters/mock";
export { DouyinAdapter } from "./adapters/douyin";
export { XiaohongshuAdapter } from "./adapters/xiaohongshu";
export { WeixinChannelsAdapter } from "./adapters/weixinChannels";
export { BilibiliAdapter } from "./adapters/bilibili";
export { TiktokAdapter } from "./adapters/tiktok";
export { YoutubeAdapter } from "./adapters/youtube";

/** 唯一装配入口：平台注册表决定 Adapter，调用方不感知平台文件布局。 */
export const createAdapter = (platform: string, driver: PageDriver, task: PublishTask): PublishAdapter => {
  const normalized = resolvePlatform(platform).id;
  if (normalized === "douyin") return new DouyinAdapter(driver, task);
  if (normalized === "xiaohongshu") return new XiaohongshuAdapter(driver, task);
  if (normalized === "weixin-channels") return new WeixinChannelsAdapter(driver, task);
  if (normalized === "bilibili") return new BilibiliAdapter(driver, task);
  if (normalized === "tiktok") return new TiktokAdapter(driver, task);
  if (normalized === "youtube") return new YoutubeAdapter(driver, task);
  return new MockAdapter(driver, task);
};
