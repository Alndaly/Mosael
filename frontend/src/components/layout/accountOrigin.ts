import type { MessageKey } from "@/app/messages";

//: 第三方登录方的名字是商标,不进文案表。清单外的原样显示 —— 后端多接一家时宁可露出 id,也不显示成空。
const PROVIDER_NAMES: Record<string, string> = { google: "Google", apple: "Apple" };

/**
 * 账号菜单里「这是哪儿的账号、怎么登进来的」那一行。
 *
 * 两半各有各的出处:账号**在哪台服务器上**只有前端知道(这个客户端连的是哪个后端),账号**怎么
 * 登录**只有后端知道(`oauth_providers`,来自 oauth_identities)。任何一半写死,连着团队服务器
 * 或用 Google 登进来的人都会被告知自己是「本地账号」。
 */
export function accountOrigin(
  t: (key: MessageKey) => string,
  serverHost: string | null,
  oauthProviders: readonly string[],
): string {
  const where = serverHost ? t("railServerAccount").replace("{server}", serverHost) : t("railLocalAccount");
  if (oauthProviders.length === 0) return where;
  const names = oauthProviders.map((id) => PROVIDER_NAMES[id] ?? id).join(" / ");
  return `${where} · ${t("railSignedInWith").replace("{provider}", names)}`;
}
