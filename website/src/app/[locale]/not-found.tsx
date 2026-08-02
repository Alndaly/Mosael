import Link from "next/link";

import { Button } from "@/components/ui/button";
import { DEFAULT_LOCALE, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

/**
 * 语言段内的 404。
 *
 * 这里拿不到 `[locale]` 参数 —— not-found 边界不接 params —— 所以文案退到默认语言。
 * 英文访客看到一句中文的"这一页不在了"不理想,但比一个空白页好;等文档页落地、
 * 404 变得常见时再考虑用 middleware 或按语言分别建页。
 */
export default function NotFound() {
  const t = getMessages(DEFAULT_LOCALE).notFound;

  return (
    <div className="prose-cn mx-auto flex max-w-5xl flex-col items-start px-6 py-32 font-serif sm:px-8">
      <h1 className="mt-0 mb-4 text-3xl font-semibold">{t.title}</h1>
      <p className="mt-0 mb-8 text-muted-foreground">{t.body}</p>
      <Button asChild className="font-sans">
        <Link href={localePath(DEFAULT_LOCALE)}>{t.back}</Link>
      </Button>
    </div>
  );
}
