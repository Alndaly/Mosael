/**
 * 发出去的那一条作品在平台上叫什么:从**平台自己的发布接口的返回**里读作品 ID。
 *
 * 为什么从接口读,不从页面读:发布成功后各平台落在哪一页、页面上有没有作品链接,各不相同
 * (B 站原地换成功页、抖音跳内容管理列表、小红书只弹一句「发布成功」),而平台的前端点下发布时
 * 拿到的那个响应里一定有作品 ID —— 它自己后面也要用。读的是**本次**提交的响应,不会把列表里
 * 别的作品认成这一条。
 *
 * 为什么用正则扫原文、不用 JSON.parse:抖音 / TikTok 的作品 ID 是 19 位整数,超过 JS 的安全
 * 整数范围,平台要是按数字返回,parse 一次末几位就变了 —— 拿错的 ID 去查,查到的是别人的作品。
 *
 * 每个平台的 ID 都有**形状校验**:接口里叫 `id` 的字段不止一个,形状对不上的一律不收。
 * 读不到就交空 —— 后端记空 post_id,不编(见 backend/app/domain/publish/post.py)。
 */
import type { SupportedPlatform } from "./platforms";

export interface CapturedResponse {
  url: string;
  body: string;
}

export interface PublishedPost {
  post_id: string;
  url: string;
  ids: Record<string, string>;
}

interface PostSource {
  /** 平台的发布接口(提交稿件那一个请求)。 */
  endpoint: RegExp;
  /** 按优先级:第一个读到的当 post_id,读到的全部进 ids。 */
  keys: readonly string[];
  /** 这个平台的作品 ID 长什么样。 */
  shape: RegExp;
  /** 作品页链接;平台没有按 ID 直达的公开页就不给。 */
  link?: (id: string) => string;
}

export const POST_SOURCES: Partial<Record<SupportedPlatform, PostSource>> = {
  douyin: {
    endpoint: /creator\.douyin\.com\/web\/api\/media\/aweme\/create/,
    keys: ["item_id", "aweme_id"],
    shape: /^\d{15,21}$/,
    link: (id) => `https://www.douyin.com/video/${id}`,
  },
  xiaohongshu: {
    endpoint: /\/web_api\/sns\/v\d+\/note(?:[/?]|$)/,
    keys: ["note_id", "id"],
    shape: /^[0-9a-f]{24}$/,
    link: (id) => `https://www.xiaohongshu.com/explore/${id}`,
  },
  bilibili: {
    endpoint: /member\.bilibili\.com\/x\/vu\/web\/add/,
    keys: ["bvid", "aid"],
    shape: /^(BV[0-9A-Za-z]{10}|\d{1,20})$/,
    link: (id) => `https://www.bilibili.com/video/${/^\d+$/.test(id) ? `av${id}` : id}`,
  },
  tiktok: {
    endpoint: /tiktok\.com\/tiktok\/web\/project\/post/,
    keys: ["item_id", "aweme_id"],
    shape: /^\d{15,21}$/,
  },
  youtube: {
    endpoint: /studio\.youtube\.com\/youtubei\/v1\/upload\/createvideo/,
    keys: ["videoId"],
    shape: /^[\w-]{11}$/,
    link: (id) => `https://www.youtube.com/watch?v=${id}`,
  },
  "weixin-channels": {
    endpoint: /mmfinderassistant-bin\/post\/post_create/,
    keys: ["exportId", "objectId"],
    shape: /^[\w-]{8,128}$/,
  },
};

/** 这个平台要监听哪些响应;不认识的平台(mock)不监听。 */
export function postEndpoint(platform: SupportedPlatform): RegExp | null {
  return POST_SOURCES[platform]?.endpoint ?? null;
}

function valuesOf(body: string, key: string): string[] {
  // "key": "value" 或 "key": 12345 —— 数字按原文取,不经 JSON 数字。
  const pattern = new RegExp(`"${key}"\\s*:\\s*(?:"([^"\\\\]{1,128})"|(\\d{1,24}))`, "g");
  return [...body.matchAll(pattern)].map((match) => match[1] ?? match[2] ?? "");
}

/**
 * 从截获的响应里认出作品。`known` 是适配器自己在页面上已经确认过的 ID(YouTube 的详情页
 * 会显示 youtu.be 链接),两路都有时以接口为准,页面那条补空。
 */
export function findPost(
  platform: SupportedPlatform,
  responses: readonly CapturedResponse[],
  known: string | null = null,
): PublishedPost | null {
  const source = POST_SOURCES[platform];
  if (!source) return null;
  const ids: Record<string, string> = {};
  for (const response of responses) {
    if (!source.endpoint.test(response.url)) continue;
    for (const key of source.keys) {
      if (ids[key]) continue;
      const value = valuesOf(response.body, key).find((candidate) => source.shape.test(candidate));
      if (value) ids[key] = value;
    }
  }
  let postId = source.keys.map((key) => ids[key]).find(Boolean) ?? "";
  if (!postId && known && source.shape.test(known)) {
    postId = known;
    ids[source.keys[0]] = known;
  }
  if (!postId) return null;
  return { post_id: postId, url: source.link ? source.link(postId) : "", ids };
}
