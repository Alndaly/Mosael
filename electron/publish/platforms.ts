export type SupportedPlatform =
  | "mock"
  | "douyin"
  | "xiaohongshu"
  | "weixin-channels"
  | "bilibili"
  | "tiktok"
  | "youtube";

export interface PlatformDefinition {
  id: SupportedPlatform;
  label: string;
  aliases: string[];
  loginUrl: string;
  dashboardUrl: string;
  publishUrl: string;
  manageUrl: string;
  titleMaxLength?: number;
  supportsShortTitle: boolean;
  supportsDescription: boolean;
  supportsTags: boolean;
}

export const PLATFORM_DEFINITIONS: PlatformDefinition[] = [
  {
    id: "mock",
    label: "Mock",
    aliases: ["mock"],
    loginUrl: "about:blank",
    dashboardUrl: "about:blank",
    publishUrl: "about:blank",
    manageUrl: "about:blank",
    supportsShortTitle: false,
    supportsDescription: false,
    supportsTags: true,
  },
  {
    id: "douyin",
    label: "抖音", // i18n-ok 平台页面的匹配文案/选择器/注入脚本,非产品文案
    aliases: ["douyin", "抖音"], // i18n-ok
    loginUrl: "https://creator.douyin.com/",
    dashboardUrl: "https://creator.douyin.com/creator-micro/home",
    publishUrl: "https://creator.douyin.com/creator-micro/content/upload",
    manageUrl: "https://creator.douyin.com/creator-micro/content/manage",
    titleMaxLength: 30,
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "xiaohongshu",
    label: "小红书", // i18n-ok
    aliases: ["xiaohongshu", "xhs", "rednote", "小红书"], // i18n-ok
    loginUrl: "https://creator.xiaohongshu.com/",
    dashboardUrl: "https://creator.xiaohongshu.com/new/home",
    publishUrl: "https://creator.xiaohongshu.com/publish/publish",
    manageUrl: "https://creator.xiaohongshu.com/new/notes",
    titleMaxLength: 20,
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "weixin-channels",
    label: "微信视频号", // i18n-ok
    aliases: [
      "weixin-channels",
      "weixin",
      "wechat",
      "channels",
      "shipinhao",
      "视频号", // i18n-ok
      "微信视频号", // i18n-ok
    ],
    loginUrl: "https://channels.weixin.qq.com/login.html?from=assistant",
    dashboardUrl: "https://channels.weixin.qq.com/platform/post/list",
    publishUrl: "https://channels.weixin.qq.com/platform/post/create",
    manageUrl: "https://channels.weixin.qq.com/platform/post/list",
    titleMaxLength: 16,
    supportsShortTitle: true,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "bilibili",
    label: "Bilibili",
    aliases: ["bilibili", "bili", "b站", "哔哩哔哩"], // i18n-ok
    loginUrl: "https://passport.bilibili.com/login",
    dashboardUrl: "https://member.bilibili.com/platform/home",
    publishUrl: "https://member.bilibili.com/platform/upload/video/frame",
    manageUrl: "https://member.bilibili.com/platform/upload-manager/article",
    titleMaxLength: 80,
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "tiktok",
    label: "TikTok",
    // **别把 tiktok 和 douyin 混成一个** —— 两个平台、两套账号,后端的别名表里曾经把
    // "tiktok" 指向抖音,说"发到 tiktok"会静默发进抖音。
    aliases: ["tiktok", "tk", "抖音国际版"], // i18n-ok
    loginUrl: "https://www.tiktok.com/login",
    dashboardUrl: "https://www.tiktok.com/tiktokstudio",
    publishUrl: "https://www.tiktok.com/tiktokstudio/upload",
    manageUrl: "https://www.tiktok.com/tiktokstudio/content",
    // TikTok 没有独立标题栏,这一栏是**文案**(caption)。
    titleMaxLength: 2200,
    supportsShortTitle: false,
    supportsDescription: false,
    supportsTags: true,
  },
  {
    id: "youtube",
    label: "YouTube",
    aliases: ["youtube", "yt", "油管"], // i18n-ok
    // 未登录时 studio.youtube.com 会跳到 accounts.google.com —— checkLogin 据此判定。
    loginUrl: "https://accounts.google.com/ServiceLogin?service=youtube",
    dashboardUrl: "https://studio.youtube.com/",
    publishUrl: "https://studio.youtube.com/",
    manageUrl: "https://studio.youtube.com/",
    titleMaxLength: 100,
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
  },
];

const PLATFORM_BY_ALIAS = new Map(
  PLATFORM_DEFINITIONS.flatMap((definition) =>
    definition.aliases.map((alias) => [alias.toLowerCase(), definition] as const),
  ),
);

export const resolvePlatform = (platform: string): PlatformDefinition => {
  return PLATFORM_BY_ALIAS.get(platform.trim().toLowerCase()) ?? PLATFORM_DEFINITIONS[0];
};

export const normalizePlatformId = (platform: string): SupportedPlatform => {
  return resolvePlatform(platform).id;
};
