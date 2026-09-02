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
    { href: `${localePath(locale)}#product`, label: t.nav.product },
    { href: localePath(locale, "/docs/guides/boards"), label: t.nav.canvas },
    { href: localePath(locale, "/workflows"), label: t.nav.workflows },
    { href: localePath(locale, "/plugins"), label: t.nav.plugins },
    { href: docHref(locale, firstDoc(locale)), label: t.nav.docs },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-border/70 bg-paper">
      <div className="mx-auto flex h-[4.5rem] max-w-[90rem] items-center gap-3 px-5 sm:gap-7 sm:px-8 lg:px-12">
        <Link href={localePath(locale)} className="flex shrink-0 items-center" aria-label="Mosael">
          <BrandWordmark className="w-28 sm:w-32" />
        </Link>

        {/* 窄屏藏起来,入口收进 MobileMenu —— 一行放不下站名 + 三个入口 + 四个动作,
            实测 390px 下右侧那组要溢出一百多像素。 */}
        <nav className="hidden min-w-0 items-center gap-1 text-sm font-medium lg:flex">
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
            className="hidden size-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground lg:inline-flex"
          >
            <GithubMark className="size-4" />
          </a>
          <a
            href={SITE.releases}
            target="_blank"
            rel="noreferrer"
            className="hidden min-h-10 items-center rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 lg:inline-flex"
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
