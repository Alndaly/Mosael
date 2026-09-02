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
    <div className="relative isolate -mt-20 flex min-h-[78svh] flex-col items-start justify-center overflow-hidden px-5 pt-28 pb-24 sm:px-8">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_20%_20%,rgba(114,87,233,0.2),transparent_38%),radial-gradient(circle_at_80%_70%,rgba(255,139,120,0.16),transparent_35%)]" />
      <div className="mx-auto w-full max-w-[88rem]">
      <p className="m-0 font-mono text-sm font-bold tracking-widest text-flame uppercase">404</p>
      <h1 className="mt-6 mb-5 font-display text-[clamp(2rem,7vw,4.5rem)] leading-none font-extrabold tracking-[-0.03em]">
        {t.title}
      </h1>
      <p className="mt-0 mb-10 max-w-xl text-lg text-muted-foreground">{t.body}</p>
      <Link href={localePath(DEFAULT_LOCALE)} className="inline-flex min-h-12 items-center rounded-full bg-primary px-6 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-85">
        {t.back}
      </Link>
      </div>
    </div>
  );
}
