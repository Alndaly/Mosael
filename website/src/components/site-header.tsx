import Image from "next/image";
import Link from "next/link";

import { GithubMark } from "@/components/icons";
import { LocaleSwitch } from "@/components/locale-switch";
import { NavLink } from "@/components/nav-link";
import { SearchDialog } from "@/components/search-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

/**
 * 站头。
 *
 * 不做磨玻璃 —— 半透明的顶栏是这两年每个站都长的样子,而且滚动时底下的图会把导航文字搅浑。
 * 这里是实色 + 一条 2px 的墨线,和整站的硬边一致:它是版面的一条边,不是浮在内容上的一层膜。
 *
 * 窄屏上导航横向滚动,不折成汉堡:三个入口不值得藏在一次点击后面。
 */
export function SiteHeader({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const links = [
    { href: localePath(locale, "/docs"), label: t.nav.docs },
    { href: localePath(locale, "/plugins"), label: t.nav.plugins },
    { href: localePath(locale, "/workflows"), label: t.nav.workflows },
  ];

  return (
    <header className="sticky top-0 z-50 border-b-2 border-ink bg-paper">
      <div className="mx-auto flex h-16 max-w-[96rem] items-center gap-6 px-5 sm:px-8">
        <Link href={localePath(locale)} className="flex shrink-0 items-center gap-3">
          <Image src="/mark.svg" alt="" width={32} height={32} />
          <span className="font-display text-lg font-extrabold tracking-tight uppercase">Open Studio</span>
        </Link>

        <nav className="-mx-1 flex min-w-0 items-center gap-1 overflow-x-auto px-1 text-sm font-medium [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {links.map((link) => (
            <NavLink key={link.href} href={link.href}>
              {link.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          <SearchDialog
            locale={locale}
            labels={{
              search: t.docs.search,
              placeholder: t.docs.searchPlaceholder,
              empty: t.docs.searchEmpty,
              hint: t.docs.searchHint,
              close: t.docs.searchClose,
            }}
          />
          <LocaleSwitch locale={locale} label={t.nav.language} />
          <ThemeToggle label={t.nav.theme} />
          <a
            href={SITE.repo}
            target="_blank"
            rel="noreferrer"
            aria-label={t.nav.github}
            title={t.nav.github}
            className="hidden size-9 items-center justify-center border-2 border-ink transition-colors hover:bg-ink hover:text-paper sm:inline-flex"
          >
            <GithubMark className="size-4" />
          </a>
          <a
            href={SITE.releases}
            target="_blank"
            rel="noreferrer"
            className="border-2 border-ink bg-flame px-4 py-2 text-sm font-bold text-primary-foreground transition-transform hover:-translate-y-0.5"
          >
            {t.nav.download}
          </a>
        </div>
      </div>
    </header>
  );
}
