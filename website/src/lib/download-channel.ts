/**
 * 下载走哪条路。**2026-10-30 起 R2 是境内外默认渠道** —— 维护者:「官网的境内外下载的默认渠道改为
 * R2,百度网盘和 GitHub 只是兜底用」。所以只要 R2 可用,谁打开都默认走它;R2 没配时退回旧规则
 * (国内走网盘、其余走 GitHub),两条都留着当兜底。
 * **按时区判,不按 IP 判。** IP 要么问第三方服务(把访客地址发出去、还多一个会挂的依赖),
 * 要么靠 CDN 的地理头(换了部署就没了)。时区是浏览器自己就知道的,不出网、不猜错大方向;
 * 在国内却把系统时区改成别处的人很少,而那种人通常也访问得了 GitHub。港澳台归 GitHub ——
 * 那边访问 GitHub 通常没有问题,网盘反而要多装一个客户端。
 *
 * 判错了也没关系:页面上两条路都在,访客自己选一次,之后记住(见 STORAGE_KEY)。
 *
 * 纯函数、不 import 任何东西:官网测试直接用 node 跑这个文件。
 */

export type Channel = "china" | "global" | "baidu";

export type ChinaMirror = { url: string; code: string };

export type DirectMirror = { url: string };

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

export function directAvailable(direct: DirectMirror): boolean {
  return direct.url.startsWith("https://");
}
export function chinaAvailable(mirror: ChinaMirror): boolean {
  return mirror.url.startsWith("https://");
}

export function detectChannel(
  { timeZone, languages }: { timeZone?: string; languages?: readonly string[] },
  mirror: ChinaMirror,
  direct: DirectMirror = { url: "" },
): Channel {
  //: **R2 是主源**:只要有它,全球访客都走它(不按时区挑 —— 挑只会让一半人落到慢的那条)。
  if (directAvailable(direct)) return "china";
  if (timeZone && CHINA_TIME_ZONES.has(timeZone)) {
    return chinaAvailable(mirror) ? "baidu" : "global";
  }
  if (timeZone) return "global";
  // 拿不到时区时才看语言:简体中文(zh-CN / zh-Hans)算国内,繁体(zh-TW / zh-HK / zh-Hant)不算。
  const first = (languages ?? [])[0]?.toLowerCase() ?? "";
  if (first !== "zh" && first !== "zh-cn" && !first.startsWith("zh-hans")) return "global";
  return chinaAvailable(mirror) ? "baidu" : "global";
}

/** 访客存过的选择;没存过、存的东西认不出、或国内渠道已不可用时返回 null。 */
export function storedChannel(raw: string | null, mirror: ChinaMirror, direct: DirectMirror = { url: "" }): Channel | null {
  if (raw === "global") return "global";
  if (raw === "china" && directAvailable(direct)) return "china";
  if (raw === "baidu" && chinaAvailable(mirror)) return "baidu";
  if (raw === "china" && chinaAvailable(mirror) && !directAvailable(direct)) return "china";
  return null;
}

/** 首屏(服务端渲染)用的默认值:有 R2 就一律它;没有时才按页面语言分(中文网盘 / 英文 GitHub)。 */
export function defaultChannel(locale: string, mirror: ChinaMirror, direct: DirectMirror = { url: "" }): Channel {
  if (directAvailable(direct)) return "china";
  if (locale !== "zh") return "global";
  return chinaAvailable(mirror) ? "baidu" : "global";
}

export function channelHref(channel: Channel, mirror: ChinaMirror, releases: string, direct: DirectMirror = { url: "" }): string {
  if (channel === "china" && directAvailable(direct)) return direct.url;
  if ((channel === "baidu" || channel === "china") && chinaAvailable(mirror)) return mirror.url;
  return releases;
}
