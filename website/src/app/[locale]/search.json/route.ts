import { LOCALES, isLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { buildSearchIndex } from "@/lib/search";

/**
 * 搜索索引,每种语言一份静态 JSON。
 *
 * `force-static` 让它在构建期就生成好、跟着页面一起进 CDN —— 搜索是纯前端的,不该因为
 * 少部署了一个服务就用不了。索引不进 JS 包:它比整站的代码还大,而多数访客根本不会搜。
 */
export const dynamic = "force-static";

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export async function GET(_request: Request, { params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (!isLocale(locale)) return new Response("Not found", { status: 404 });
  const index = buildSearchIndex(locale, getMessages(locale).docs.sections);
  return Response.json(index);
}
