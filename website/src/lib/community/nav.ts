import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

/**
 * 站头「社区」下面的四个分区。**普通模块**:服务端的站头(传给窄屏菜单)和客户端的下拉都用它。
 */
export type CommunitySectionId = "workflows" | "plugins" | "boards" | "stats";

export function communityLinks(locale: Locale): { id: CommunitySectionId; href: string; label: string }[] {
  const t = getMessages(locale).nav;
  return [
    { id: "workflows", href: localePath(locale, "/workflows"), label: t.workflows },
    { id: "plugins", href: localePath(locale, "/plugins"), label: t.plugins },
    { id: "boards", href: localePath(locale, "/boards"), label: t.boards },
    { id: "stats", href: localePath(locale, "/community/stats"), label: t.stats },
  ];
}

/** 「社区」这一格在哪些路径下算高亮:四个分区,加上作者主页与画板查看页。 */
export function communityMatch(locale: Locale): string[] {
  return ["/workflows", "/plugins", "/boards", "/community", "/u", "/b"].map((path) => localePath(locale, path));
}
