/**
 * 第三方登录的浏览器侧小逻辑。
 *
 * **配置的唯一来源是 Cloud 的 `/oauth/providers`**,官网不在构建期重复一份环境变量:
 * 两处各配一次,迟早会出现"按钮在、点下去报没启用"或反过来的错位。官网只在拿到 true
 * 的那一项上渲染按钮;请求失败也按"没启用"处理 —— 宁可不画,也不画一个点了就错的按钮。
 */

import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";

import { CLOUD_API } from "./cloud";

export type OAuthProviderName = "github" | "google";

/** 渲染顺序。也是 `/oauth/providers` 里认的键。 */
export const OAUTH_PROVIDERS: readonly OAuthProviderName[] = ["github", "google"];

export type OAuthReturnPage = "login" | "signup";

/** `/oauth/providers` 的响应 → 真正要渲染的按钮。别的键、非 true 的值一律忽略。 */
export function enabledOAuthProviders(value: unknown): OAuthProviderName[] {
  const providers = (value as { providers?: unknown } | null | undefined)?.providers;
  if (!providers || typeof providers !== "object") return [];
  const known = providers as Record<string, unknown>;
  return OAUTH_PROVIDERS.filter((name) => known[name] === true);
}

/** 同源 GET:Cloud 生成 state / PKCE 后 302 到第三方。成功 / 失败都回到官网。 */
export function oauthStartUrl(
  provider: OAuthProviderName,
  locale: Locale,
  from: OAuthReturnPage,
): string {
  const query = new URLSearchParams({ locale, from });
  return `${CLOUD_API}/oauth/${provider}/start?${query.toString()}`;
}

/** 后端稳定错误码 → 页面文案 key。未知错误码统一落到通用那一句。 */
const OAUTH_ERROR_KEYS = {
  oauth_not_configured: "oauthErrorNotEnabled",
  oauth_state_invalid: "oauthErrorStateInvalid",
  oauth_callback_invalid: "oauthErrorCallbackInvalid",
  oauth_denied: "oauthErrorDenied",
  oauth_code_rejected: "oauthErrorCodeRejected",
  oauth_email_unverified: "oauthErrorEmailUnverified",
  oauth_identity_conflict: "oauthErrorConflict",
  oauth_provider_error: "oauthErrorProvider",
} as const satisfies Record<string, keyof Messages["account"]>;

export type OAuthErrorCopyKey =
  | (typeof OAUTH_ERROR_KEYS)[keyof typeof OAUTH_ERROR_KEYS]
  | "oauthErrorGeneric";

export function oauthErrorCopyKey(code: string): OAuthErrorCopyKey {
  return OAUTH_ERROR_KEYS[code as keyof typeof OAUTH_ERROR_KEYS] ?? "oauthErrorGeneric";
}
