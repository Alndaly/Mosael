import { t } from "../../i18n.cjs";
import siteContracts from "../../../contracts/platform-contracts.json";

export type SupportedPlatform =
  | "mock"
  | "douyin"
  | "xiaohongshu"
  | "weixin-channels"
  | "bilibili"
  | "tiktok"
  | "youtube"
  | "x";

export interface PlatformDefinition {
  id: SupportedPlatform;
  /** 平台名的文案 key(见 electron/i18n.cjs 的 platform_*)。给人看的名字按界面语言翻,用 platformName()。 */
  nameKey: string;
  /** 认得出的叫法(后端 / 智能体 / 用户输入里可能出现的写法),含中文俗称 —— 是匹配用的,不是显示用的。 */
  aliases: string[];
  /** 登录入口 —— 读自站点契约(`contracts/platform-contracts.json`)。 */
  loginUrl: string;
  dashboardUrl: string;
  /** 发布页 —— 读自站点契约。 */
  publishUrl: string;
  manageUrl: string;
  /** 默认形状(视频)的标题上限 —— 读自站点契约;mock 没有。 */
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
  session?: {
    /** 读 cookie 用的 URL(Chromium 按域/路径/Secure 规则筛选)。 */
    url: string;
    cookies: readonly string[];
    /**
     * 这条判据**只在平台自己的站上算数**的域名后缀。
     *
     * cookie 说的是「这个分区里存着一个会话」,它不解释当前这一页是什么。用户点「用 Google 继续」
     * 时人在 accounts.google.com,而分区里可能躺着一枚过期的旧 cookie —— 那一刻判成"已登录"是错的,
     * 而且代价很实在:登录成功会自动收起内嵌浏览器,于是浏览器在人还在登录时凭空消失。
     * 限定在平台自己的域上,既保住了原本要解决的问题(登完停在 www.youtube.com / tiktok 信息流),
     * 又不必去枚举有哪些第三方授权方。
     */
    hosts: readonly string[];
  };
}

/**
 * 执行器独有的平台事实。登录入口、发布页、标题上限**不写在这里** —— 它们是站点契约的字段,
 * 后端测试与每日冒烟读的也是那一份;这里写一遍就会漂(2.6.14 之前视频号 / B 站 / YouTube 的
 * 登录入口就是两份各说各的)。
 */
type ExecutorFacts = Omit<PlatformDefinition, "loginUrl" | "publishUrl" | "titleMaxLength">;
type ContractPlatform = Exclude<SupportedPlatform, "mock">;

const SITE_CONTRACTS: Record<ContractPlatform, { loginUrl: string; publishUrl: string; limits: { titleMax: number } }> =
  siteContracts.platforms;

const MOCK: PlatformDefinition = {
  id: "mock",
  nameKey: "platform_mock",
  aliases: ["mock"],
  loginUrl: "about:blank",
  dashboardUrl: "about:blank",
  publishUrl: "about:blank",
  manageUrl: "about:blank",
  supportsShortTitle: false,
  supportsDescription: false,
  supportsTags: true,
};

const EXECUTOR_FACTS: (ExecutorFacts & { id: ContractPlatform })[] = [
  {
    id: "douyin",
    nameKey: "platform_douyin",
    aliases: ["douyin", "抖音"], // i18n-ok
    dashboardUrl: "https://creator.douyin.com/creator-micro/home",
    manageUrl: "https://creator.douyin.com/creator-micro/content/manage",
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "xiaohongshu",
    nameKey: "platform_xiaohongshu",
    aliases: ["xiaohongshu", "xhs", "rednote", "小红书"], // i18n-ok
    dashboardUrl: "https://creator.xiaohongshu.com/new/home",
    manageUrl: "https://creator.xiaohongshu.com/new/notes",
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "weixin-channels",
    nameKey: "platform_weixinChannels",
    aliases: [
      "weixin-channels",
      "weixin",
      "wechat",
      "channels",
      "shipinhao",
      "视频号", // i18n-ok
      "微信视频号", // i18n-ok
    ],
    dashboardUrl: "https://channels.weixin.qq.com/platform/post/list",
    manageUrl: "https://channels.weixin.qq.com/platform/post/list",
    supportsShortTitle: true,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "bilibili",
    nameKey: "platform_bilibili",
    aliases: ["bilibili", "bili", "b站", "哔哩哔哩"], // i18n-ok
    dashboardUrl: "https://member.bilibili.com/platform/home",
    manageUrl: "https://member.bilibili.com/platform/upload-manager/article",
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
  },
  {
    id: "tiktok",
    nameKey: "platform_tiktok",
    // **别把 tiktok 和 douyin 混成一个** —— 两个平台、两套账号,后端的别名表里曾经把
    // "tiktok" 指向抖音,说"发到 tiktok"会静默发进抖音。
    aliases: ["tiktok", "tk", "抖音国际版"], // i18n-ok
    dashboardUrl: "https://www.tiktok.com/tiktokstudio",
    manageUrl: "https://www.tiktok.com/tiktokstudio/content",
    // TikTok 没有独立标题栏,这一栏是**文案**(caption)。
    supportsShortTitle: false,
    supportsDescription: false,
    supportsTags: true,
    // 登录成功后 TikTok 常把人留在 www.tiktok.com 的信息流,而不是 Studio。
    session: {
      url: "https://www.tiktok.com/",
      cookies: ["sessionid", "sessionid_ss"],
      hosts: ["tiktok.com"],
    },
  },
  {
    id: "youtube",
    nameKey: "platform_youtube",
    aliases: ["youtube", "yt", "油管"], // i18n-ok
    //: 登录入口为什么是 Google 的 ServiceLogin,见站点契约的 notes。
    dashboardUrl: "https://studio.youtube.com/",
    manageUrl: "https://studio.youtube.com/",
    supportsShortTitle: false,
    supportsDescription: true,
    supportsTags: true,
    // Google 登录完成后跳的是 www.youtube.com,不是 Studio —— 页面上找不到任何 Studio 标志。
    // SAPISID / __Secure-3PAPISID 是 Google 已登录会话的标准标记(网页端据此算 SAPISIDHASH),
    // 登录态一建立就有,退出即失。
    session: {
      url: "https://www.youtube.com/",
      cookies: ["SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID"],
      hosts: ["youtube.com"],
    },
  },
  {
    id: "x",
    nameKey: "platform_x",
    aliases: ["x", "twitter", "X", "推特"], // i18n-ok
    dashboardUrl: "https://x.com/home",
    // X 没有「作品管理」页:发出的帖子落在个人主页时间线上。
    manageUrl: "https://x.com/home",
    // 「标题」一栏发出去就是帖子文案(和 TikTok 的 caption 同一角色),上限见契约。
    supportsShortTitle: false,
    // 没有独立描述/标签栏 —— 文案和 #hashtag 都写进正文。
    supportsDescription: false,
    supportsTags: false,
    // 登录态的页面无关判据:auth_token 是 HttpOnly 会话 cookie,登录即写 —— x.com 登完
    // 常把人留在首页/信息流,不在撰写页。
    session: {
      url: "https://x.com",
      cookies: ["auth_token"],
      hosts: ["x.com", "twitter.com"],
    },
  },
];

/** 站点契约 + 执行器独有事实 = 执行器用的平台定义。 */
export const PLATFORM_DEFINITIONS: PlatformDefinition[] = [
  MOCK,
  ...EXECUTOR_FACTS.map((facts) => {
    const site = SITE_CONTRACTS[facts.id];
    return { ...facts, loginUrl: site.loginUrl, publishUrl: site.publishUrl, titleMaxLength: site.limits.titleMax };
  }),
];

const PLATFORM_BY_ALIAS = new Map(
  PLATFORM_DEFINITIONS.flatMap((definition) =>
    definition.aliases.map((alias) => [alias.toLowerCase(), definition] as const),
  ),
);

export const resolvePlatform = (platform: string): PlatformDefinition => {
  return PLATFORM_BY_ALIAS.get(platform.trim().toLowerCase()) ?? PLATFORM_DEFINITIONS[0];
};

/** 平台给人看的名字,按当前界面语言。 */
export const platformName = (platform: string): string => t(resolvePlatform(platform).nameKey);

export const normalizePlatformId = (platform: string): SupportedPlatform => {
  return resolvePlatform(platform).id;
};
