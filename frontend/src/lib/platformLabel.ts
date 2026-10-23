import type { MessageKey } from "@/app/messages";

/**
 * 平台 id → **给人看的中文/英文短名**。
 *
 * 这一份原本长在统计页的图表里(`StatisticsCharts`),发布记录那边又需要同一件事 —— 于是抽出来
 * 共用,而不是各自再写一张表。它是「平台」这件事的**第四份**表(后端 `PUBLISH_PLATFORMS`、
 * Electron `PLATFORM_DEFINITIONS`、图表图例),但用途不同:这里要的是"能塞进一行字里的短名",
 * 后端那份是下拉与说明用的完整名。加新平台时记得同步;漏了这里的后果很轻 —— 退回显示裸 id。
 */
const PLATFORM_LABELS: Record<string, MessageKey> = {
  folder: "homeChartPlatformFolder",
  webhook: "homeChartPlatformWebhook",
  douyin: "homeChartPlatformDouyin",
  bilibili: "homeChartPlatformBilibili",
  xiaohongshu: "homeChartPlatformXiaohongshu",
  "weixin-channels": "homeChartPlatformWeixinChannels",
  tiktok: "homeChartPlatformTiktok",
  youtube: "homeChartPlatformYoutube",
};

/** 认得的平台翻成短名;认不得的原样返回(显示裸 id 也胜过显示空白)。 */
export function platformLabel(platform: string, t: (key: MessageKey) => string): string {
  const known = PLATFORM_LABELS[platform];
  return known ? t(known) : platform;
}
