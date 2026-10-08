import type { ProviderProfile } from "@/api/client";

/**
 * 这条连接**对我**现在用不了的原因(没有就是能用)。连接列表那一行、默认模型那一行用同一份判断 ——
 * 此前列表上写着「未授权」,默认模型那一行却毫无提示,AI Studio、智能体用默认模型时才报错(体检 UM-23)。
 *
 * 插件管着的连接(ADR 0020)钥匙在插件实例上,这里不判。
 */
export type ProviderProblem = "disabled" | "unauthorized" | "expired" | "noKey";

export function providerProblem(profile: ProviderProfile): ProviderProblem | null {
  if (!profile.enabled) return "disabled";
  if (profile.plugin_instance_id) return null;
  if (profile.auth_type === "oauth") {
    if (!profile.oauth_linked) return "unauthorized";
    return profile.oauth_expired ? "expired" : null;
  }
  //: 看的是「有没有我自己的那份凭据」(`is_mine`),和后端放不放行同一个判据(providers/credentials.resolve_connection)。
  //: 不看尾四位:本机 Ollama 这类不要钥匙的端点,存下的是一份空钥匙 —— 没有尾数,却照样能用。
  return profile.is_mine ? null : "noKey";
}

/** 行内那颗修它的按钮挂这个属性:默认模型那一行的「去处理」滚到连接那一行、把焦点交给它。 */
export const PROVIDER_FIX_ATTR = "data-provider-fix";

export function providerRowId(profileId: string): string {
  return `provider-profile-${profileId}`;
}
