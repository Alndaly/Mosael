import Link from "next/link";

import { DEFAULT_LOCALE, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

/**
 * 语言段内的 404。
 *
 * 这里拿不到 `[locale]` 参数 —— not-found 边界不接 params —— 所以文案退到默认语言。
 * 英文访客看到一句中文的"这一页不在了"不理想,但比一个空白页好;等社区页开始出现单语内容、
 * 404 变得常见时再考虑按语言分别建页。
 */
export default function NotFound() {
  const t = getMessages(DEFAULT_LOCALE).notFound;

  return (
    <div className="mx-auto flex max-w-[96rem] flex-col items-start px-5 py-32 sm:px-8">
      <p className="m-0 font-mono text-sm font-bold tracking-widest text-flame uppercase">404</p>
      <h1 className="mt-6 mb-5 font-display text-[clamp(2rem,7vw,4.5rem)] leading-none font-extrabold tracking-[-0.03em]">
        {t.title}
      </h1>
      <p className="mt-0 mb-10 max-w-xl text-lg text-muted-foreground">{t.body}</p>
      <Link
        href={localePath(DEFAULT_LOCALE)}
        className="border-2 border-ink bg-flame px-6 py-3 font-bold text-primary-foreground shadow-block transition-transform hover:translate-x-1 hover:translate-y-1 hover:shadow-none"
      >
        {t.back}
      </Link>
    </div>
  );
}
