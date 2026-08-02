import Image from "next/image";
import Link from "next/link";

import { GithubMark } from "@/components/icons";
import { LocaleSwitch } from "@/components/locale-switch";
import { NavLink } from "@/components/nav-link";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

/**
 * 站头。
 *
 * 窄屏上导航只是横向滚动的一条,不折成汉堡菜单 —— 三个入口不值得藏在一次点击后面。
 */
export function SiteHeader({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const links = [
    { href: localePath(locale, "/docs"), label: t.nav.docs },
    { href: localePath(locale, "/plugins"), label: t.nav.plugins },
    { href: localePath(locale, "/workflows"), label: t.nav.workflows },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-4 px-6 sm:px-8">
        <Link href={localePath(locale)} className="flex shrink-0 items-center gap-2.5 font-medium">
          <Image src="/logo.svg" alt="" width={24} height={24} className="rounded-md" />
          <span className="tracking-tight">Open Studio</span>
        </Link>

        <nav className="flex min-w-0 gap-1 overflow-x-auto font-sans text-sm [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {links.map((link) => (
            <NavLink key={link.href} href={link.href}>
              {link.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <LocaleSwitch locale={locale} label={t.nav.language} />
          <ThemeToggle label={t.nav.theme} />
          <Button asChild variant="ghost" size="icon" title={t.nav.github}>
            <a href={SITE.repo} target="_blank" rel="noreferrer" aria-label={t.nav.github}>
              <GithubMark />
            </a>
          </Button>
          <Button asChild size="sm" className="ml-1.5 hidden sm:inline-flex">
            <a href={SITE.releases} target="_blank" rel="noreferrer">
              {t.nav.download}
            </a>
          </Button>
        </div>
      </div>
    </header>
  );
}
