/**
 * 服务端读社区服务。**只在 server component / route handler 里 import。**
 *
 * 官网的形态(ADR §8):文档、下载、更新日志构建期静态生成,不碰这里;社区页在请求时渲染,
 * 经 `COMMUNITY_API_URL` 直连社区服务。没配这个变量就是「社区未开放」—— 页面据此显示空态,
 * 不回退到仓库里的静态索引。
 *
 * 服务端只读**公开数据**:访问令牌只在浏览器内存里,刷新令牌的 cookie 限定在 `/auth` 路径下,
 * 页面请求根本带不到它。和「我」有关的一切都在浏览器里经 session 客户端取。
 */
import { HTML_LANG, type Locale } from "@/i18n/config";
import { API_PREFIX } from "@/lib/community/endpoints";
import { CommunityError, errorFromResponse, networkError } from "@/lib/community/errors";

/** 社区服务的基址(不带 `/api/community/v1`)。空 = 社区未开放。 */
export function communityApiUrl(): string | null {
  const value = process.env.COMMUNITY_API_URL?.trim();
  return value ? value.replace(/\/+$/, "") : null;
}

export function communityEnabled(): boolean {
  return communityApiUrl() !== null;
}

export type Result<T> = { ok: true; data: T } | { ok: false; error: CommunityError };

/**
 * 取一份公开数据。失败不抛:详情页要区分 404(notFound)、410(已撤回)和服务挂了(错误态)。
 *
 * `no-store`:社区内容随时在变(下载数、新提交),而这些页本来就是请求时渲染的。
 */
export async function serverGet<T>(path: string, locale: Locale): Promise<Result<T>> {
  const base = communityApiUrl();
  if (!base) return { ok: false, error: new CommunityError(503, "community_unavailable", "") };
  let response: Response;
  try {
    response = await fetch(`${base}${API_PREFIX}${path}`, {
      cache: "no-store",
      headers: { Accept: "application/json", "Accept-Language": HTML_LANG[locale] },
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    return { ok: false, error: networkError() };
  }
  if (!response.ok) return { ok: false, error: await errorFromResponse(response) };
  return { ok: true, data: (await response.json()) as T };
}
