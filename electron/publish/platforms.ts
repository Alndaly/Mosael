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
  /**
   * 会话 cookie:「这个账号分区里有没有登录态」的**页面无关**判据。
   *
   * 为什么需要它:登录轮询(publishWorker.openLogin)是在**用户此刻停留的那个页面**上问
   * `checkLogin()` 的,而适配器原本只认得创作页的样子。登录流程结束后落在哪一页由平台决定 ——
   * YouTube 走完 Google 登录会把人送到 `www.youtube.com`(看视频的那个站,不是 Studio),
   * 那里既没有文件输入也没有「YouTube Studio」字样,于是**明明登上了却一直报未登录**。
   *
   * cookie 由 Electron 的 session 直接读(含 HttpOnly),不经页面 JS,所以停在哪一页都答得出来。
   * 只当**正向**信号用:在登录页上一律判未登录(见各适配器 checkLogin 的第一条),会话过期时
   * 服务端会跳登录页,那一条先命中,不会被这里盖过去。
   *
   * 只给「登录后不落在创作页」的平台配置。抖音/B 站/小红书登完就回创作页,页面判据已经够用,
   * 再叠一层只会让「会话失效但 cookie 还在」有机会被误报成已登录。
   */
  session?: { url: string; cookies: readonly string[] };
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
    // 登录成功后 TikTok 常把人留在 www.tiktok.com 的信息流,而不是 Studio。
    session: { url: "https://www.tiktok.com/", cookies: ["sessionid", "sessionid_ss"] },
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
    // Google 登录完成后跳的是 www.youtube.com,不是 Studio —— 页面上找不到任何 Studio 标志。
    // SAPISID / __Secure-3PAPISID 是 Google 已登录会话的标准标记(网页端据此算 SAPISIDHASH),
    // 登录态一建立就有,退出即失。
    session: {
      url: "https://www.youtube.com/",
      cookies: ["SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID"],
    },
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
