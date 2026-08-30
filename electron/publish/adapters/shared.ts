import type { PublishTask } from "../types";
import type { SupportedPlatform } from "../platforms";
import { resolvePlatform } from "../platforms";
import type { PageDriver } from "../pageDriver";
import { plog } from "../log";

export interface PublishAdapter {
  openCreatorPage(): Promise<void>;
  checkLogin(): Promise<boolean>;
  uploadVideo(videoPath: string): Promise<void>;
  fillTitle(title: string): Promise<void>;
  fillTags(tags: string[]): Promise<void>;
  submit(): Promise<void>;
  waitResult(): Promise<void>;
}

export const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

// 站内文案:拿去和真实中文站点做文本匹配的**选择器**,不是本应用的 UI 文案 —— 翻译了就点不中。
// 提成常量而不是行内字面量:行内时 `// i18n-ok` 只能挂在 `{` 后面,prettier 会把它挪进块内,
// 而 check-i18n 的豁免是逐行判的(规则 5),挪走就漏判。属性/声明后的行尾注释 prettier 不动
// (与下方各平台配置里 submitText 等的写法一致)。
export const TEXT_PUBLISH_VIDEO = "发布视频"; // i18n-ok
export const TEXT_NEW_TOPIC = "新建话题"; // i18n-ok

// Generous because real video uploads/transcoding can take minutes.
export const UPLOAD_TIMEOUT = 10 * 60 * 1000;
export const RESULT_TIMEOUT = 2 * 60 * 1000;
export const ACTION_TIMEOUT = 30 * 1000;
export const HUMAN_INTERVENTION_TIMEOUT = 10 * 60 * 1000;

/** 收尾判定失败时,把「当时页面究竟是什么」记下来:URL + 正文开头。
 *
 * 没有这条,故障在日志里只剩一句 `did not confirm publish`,而「平台改版导致文案/选择器失配」
 * 和「按钮点了但没生效」是两种完全不同的原因,却长得一模一样——只能靠猜。 */
export async function plogPageState(tag: string, driver: PageDriver): Promise<void> {
  const text = await driver
    .evaluate<string>(`(document.body?.innerText || '').slice(0, 300)`)
    .catch(() => "");
  plog(tag, { url: driver.url(), text });
}

/**
 * 填字段:**优先真实按键**(isTrusted=true),落不稳再退回 DOM 事件那条。
 *
 * 为什么值得:`fillCss` / `fillField` / `insertText` 都是「native value setter + 派发 input/change」
 * 或 `dispatchEvent`,事件 isTrusted=false —— 而标题、简介恰恰是平台最会审查的字段。真实按键走的是
 * 和人手打字同一条输入管线。
 *
 * 为什么必须能降级:真实输入会触发平台自己的输入处理 —— @提及 / #话题 的自动补全弹层、长度截断、
 * 富文本编辑器改写,都可能让最终文本和期望不一致。typeInto 因此自带校验,校验不过就抛;这里接住并
 * 降级。**宁可 isTrusted=false,也不能把文案写坏。**
 */
export async function typeOrFill(
  driver: PageDriver,
  what: string,
  selector: string,
  text: string,
  fallback: () => Promise<unknown>,
): Promise<void> {
  try {
    await driver.typeInto(selector, text);
    plog(`${what}: typed (trusted)`);
  } catch (error) {
    plog(`${what}: 真实按键未落稳,降级到 DOM 事件 —`, String(error).replace(/^Error: /, "").slice(0, 130));
    await fallback();
  }
}

/**
 * 按文案点击:**先可信、后降级**。
 *
 * pointerClickByText 发真实鼠标事件(isTrusted=true),但依赖真实布局与命中测试 —— 视图挂成悬浮面板
 * 之后才具备(见 publishWorker 里 panelAttach 早于 openCreatorPage)。挂不上或被遮挡时它会**显式抛错**,
 * 这里接住并退回 el.click():isTrusted 为 false,但点得到。
 */
export async function clickTextPreferTrusted(
  driver: PageDriver,
  text: string,
  options?: { exact?: boolean; selector?: string },
): Promise<void> {
  try {
    await driver.pointerClickByText(text, options);
  } catch {
    await driver.clickByText(text, options);
  }
}

/**
 * 「这个账号分区里存着登录态吗」——**页面无关**的那一条判据。
 *
 * 登录轮询在用户此刻停留的页面上反复问 `checkLogin()`,而各平台登录完落在哪一页由它们自己决定:
 * YouTube 走完 Google 登录会把人送到 `www.youtube.com`(看视频那个站),那里既没有文件输入、
 * 也没有任何 Studio 字样 —— 只认创作页长相的判据在这里必然答错,于是**登上了却一直显示未登录**。
 *
 * 只用作正向补充,且必须排在「当前在登录页」之后:会话过期时平台会把人重定向回登录页,那一条
 * 先命中,残留 cookie 不会把已失效的会话说成有效。没配 `session` 的平台原样返回 false。
 */
export async function hasStoredSession(driver: PageDriver, platform: SupportedPlatform): Promise<boolean> {
  const { session } = resolvePlatform(platform);
  if (!session) return false;
  // **只在平台自己的站上算数。** cookie 说的是「分区里存着一个会话」,它不解释当前这一页是什么:
  // 用户点「用 Google 继续」时人在 accounts.google.com,而分区里可能还躺着一枚过期的旧 cookie。
  // 那一刻判成已登录不只是显示错 —— 登录成功会自动收起内嵌浏览器,人还在登录,窗口就没了。
  if (!onPlatformSite(driver.url(), session.hosts)) return false;
  const ok = await driver.hasCookie(session.url, session.cookies);
  if (ok) plog(`${platform} checkLogin: 会话 cookie 命中(与当前页面无关)`);
  return ok;
}

/** 当前页面是不是这个平台自己的站(按域名后缀,子域算)。 */
function onPlatformSite(url: string, hosts: readonly string[]): boolean {
  let hostname: string;
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return false; // about:blank / 空串 —— 谈不上"在平台站上"
  }
  return hosts.some((host) => hostname === host || hostname.endsWith(`.${host}`));
}

export const normalizeTag = (tag: string): string => tag.replace(/^#/, "").trim();

export const escapeHtml = (value: string): string =>
  value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export const stringOption = (task: PublishTask, key: string): string | null => {
  const value = task.platformOptions[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

/**
 * 平台自己的发布选项(可见性、允许评论…),取值范围由后端 PLATFORM_OPTIONS 定义并在建任务时校验,
 * 所以这里拿到的一定是合法值。**兜底值必须取最保守的那档** —— 万一真拿不到(老任务、字段缺失),
 * 宁可发成私享让用户去改,也不能默认公开:误发公开是收不回的。
 */
export const enumOption = <T extends string>(task: PublishTask, key: string, fallback: T, allowed: readonly T[]): T => {
  const value = task.platformOptions[key];
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
};

export const boolOption = (task: PublishTask, key: string, fallback: boolean): boolean => {
  const value = task.platformOptions[key];
  return typeof value === "boolean" ? value : fallback;
};
