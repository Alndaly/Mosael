/**
 * 下载走哪条路:国内用百度网盘,其余用 GitHub Releases。
 *
 * **按时区判,不按 IP 判。** IP 要么问第三方服务(把访客地址发出去、还多一个会挂的依赖),
 * 要么靠 CDN 的地理头(换了部署就没了)。时区是浏览器自己就知道的,不出网、不猜错大方向;
 * 在国内却把系统时区改成别处的人很少,而那种人通常也访问得了 GitHub。港澳台归 GitHub ——
 * 那边访问 GitHub 通常没有问题,网盘反而要多装一个客户端。
 *
 * 判错了也没关系:页面上两条路都在,访客自己选一次,之后记住(见 STORAGE_KEY)。
 *
 * 纯函数、不 import 任何东西:官网测试直接用 node 跑这个文件。
 */

export type Channel = "china" | "global";

export type ChinaMirror = { url: string; code: string };

/** 中国大陆的时区名(IANA)。Asia/Shanghai 是绝大多数系统的默认,其余是历史别名。 */
export const CHINA_TIME_ZONES = new Set([
  "Asia/Shanghai",
  "Asia/Chongqing",
  "Asia/Chungking",
  "Asia/Harbin",
  "Asia/Urumqi",
  "Asia/Kashgar",
  "PRC",
]);

/** 访客自己选过的渠道存在这里(localStorage)。 */
export const STORAGE_KEY = "mosael-download-channel";

/** 国内渠道**有链接**才算可用 —— 没配好之前不给访客一个点了打不开的按钮。 */
export function chinaAvailable(mirror: ChinaMirror): boolean {
  return mirror.url.startsWith("https://");
}

export function detectChannel(
  { timeZone, languages }: { timeZone?: string; languages?: readonly string[] },
  mirror: ChinaMirror,
): Channel {
  if (!chinaAvailable(mirror)) return "global";
  if (timeZone && CHINA_TIME_ZONES.has(timeZone)) return "china";
  if (timeZone) return "global";
  // 拿不到时区时才看语言:简体中文(zh-CN / zh-Hans)算国内,繁体(zh-TW / zh-HK / zh-Hant)不算。
  const first = (languages ?? [])[0]?.toLowerCase() ?? "";
  return first === "zh" || first === "zh-cn" || first.startsWith("zh-hans") ? "china" : "global";
}

/** 访客存过的选择;没存过、存的东西认不出、或国内渠道已不可用时返回 null。 */
export function storedChannel(raw: string | null, mirror: ChinaMirror): Channel | null {
  if (raw === "global") return "global";
  if (raw === "china" && chinaAvailable(mirror)) return "china";
  return null;
}

/** 首屏(服务端渲染)用的默认值:只知道页面语言。中文页默认国内,英文页默认 GitHub。 */
export function defaultChannel(locale: string, mirror: ChinaMirror): Channel {
  return locale === "zh" && chinaAvailable(mirror) ? "china" : "global";
}

export function channelHref(channel: Channel, mirror: ChinaMirror, releases: string): string {
  return channel === "china" && chinaAvailable(mirror) ? mirror.url : releases;
}
