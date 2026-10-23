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
import { XAdapter } from "./adapters/x";

export type { PublishAdapter } from "./adapters/shared";
export { MockAdapter } from "./adapters/mock";
export { DouyinAdapter } from "./adapters/douyin";
export { XiaohongshuAdapter } from "./adapters/xiaohongshu";
export { WeixinChannelsAdapter } from "./adapters/weixinChannels";
export { BilibiliAdapter } from "./adapters/bilibili";
export { TiktokAdapter } from "./adapters/tiktok";
export { YoutubeAdapter } from "./adapters/youtube";
export { XAdapter } from "./adapters/x";

/**
 * **唯一装配入口**:平台 id → 适配器构造器。
 *
 * 以前是一条 `if (normalized === "douyin") …` 的链:加一个平台要改函数体,而且这个函数的
 * "支持了谁"要靠读代码才知道。现在是一张表 —— 新平台加一行,漏加会落到 Mock(测试会红)。
 */
const ADAPTERS: Record<string, new (driver: PageDriver, task: PublishTask) => PublishAdapter> = {
  douyin: DouyinAdapter,
  xiaohongshu: XiaohongshuAdapter,
  "weixin-channels": WeixinChannelsAdapter,
  bilibili: BilibiliAdapter,
  tiktok: TiktokAdapter,
  youtube: YoutubeAdapter,
  x: XAdapter,
};

/** 每个适配器**声明**支持的形状(契约测试按它核对入口/文件框是否写全)。 */
export const ADAPTER_SUPPORTS: Record<string, readonly string[]> = {
  douyin: DouyinAdapter.KINDS,
  xiaohongshu: XiaohongshuAdapter.KINDS,
  "weixin-channels": WeixinChannelsAdapter.KINDS,
  bilibili: BilibiliAdapter.KINDS,
  tiktok: TiktokAdapter.KINDS,
  youtube: YoutubeAdapter.KINDS,
  x: XAdapter.KINDS,
  mock: MockAdapter.KINDS,
};

export const createAdapter = (platform: string, driver: PageDriver, task: PublishTask): PublishAdapter => {
  const Adapter = ADAPTERS[resolvePlatform(platform).id] ?? MockAdapter;
  return new Adapter(driver, task);
};
