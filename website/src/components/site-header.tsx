import Link from "next/link";

import { BrandWordmark } from "@/components/brand-logo";
import { GithubMark } from "@/components/icons";
import { LocaleSwitch } from "@/components/locale-switch";
import { MobileMenu } from "@/components/mobile-menu";
import { NavLink } from "@/components/nav-link";
import { SearchDialog } from "@/components/search-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { docHref, firstDoc } from "@/lib/docs";
import { SITE } from "@/lib/site";

/** 悬浮站头。它脱离文档流，首页的品牌色因此能一直延伸到视口顶部。 */
export function SiteHeader({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const links = [
    { href: localePath(locale), match: localePath(locale), exact: true, label: t.nav.product },
    { href: localePath(locale, "/workflows"), match: localePath(locale, "/workflows"), label: t.nav.workflows },
    { href: localePath(locale, "/plugins"), match: localePath(locale, "/plugins"), label: t.nav.plugins },
    { href: docHref(locale, firstDoc(locale)), match: localePath(locale, "/docs"), label: t.nav.docs },
  ];

  return (
    <header className="fixed inset-x-0 top-0 z-50 px-3 pt-3 sm:px-5 sm:pt-4">
      <div className="mx-auto flex h-14 max-w-[82rem] items-center gap-3 rounded-full border border-white/35 bg-paper/64 px-4 backdrop-blur-2xl sm:gap-6 sm:px-5 dark:border-white/10 dark:bg-paper/62">
        <Link href={localePath(locale)} className="flex shrink-0 items-center" aria-label="Mosael">
          <BrandWordmark className="w-24 sm:w-28" />
        </Link>

        <nav className="hidden min-w-0 items-center gap-1 text-sm font-medium lg:flex">
          {links.map((link) => (
            <NavLink key={link.href} href={link.href} match={link.match} exact={link.exact}>
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
          <span className="hidden lg:inline-flex">
            <LocaleSwitch locale={locale} label={t.nav.language} />
          </span>
          {/* 主题开关窄屏收进菜单:留在这里的话站名会被挤到要截断,而换主题不是高频动作。 */}
          <span className="hidden lg:inline-flex">
            <ThemeToggle label={t.nav.theme} />
          </span>
          <a
            href={SITE.repo}
            target="_blank"
            rel="noreferrer"
            aria-label={t.nav.github}
            title={t.nav.github}
            className="hidden size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground lg:inline-flex"
          >
            <GithubMark className="size-4" />
          </a>
          <a
            href={SITE.releases}
            target="_blank"
            rel="noreferrer"
            className="hidden min-h-10 items-center rounded-full bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/88 lg:inline-flex"
          >
            {t.nav.download}
          </a>
          <MobileMenu
            locale={locale}
            links={links}
            labels={{
              menu: t.nav.menu,
              language: t.nav.language,
              github: t.nav.github,
              download: t.nav.download,
              theme: t.nav.theme,
            }}
          />
        </div>
      </div>
    </header>
  );
}
