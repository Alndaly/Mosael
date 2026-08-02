import Image from "next/image";
import Link from "next/link";

import { GithubMark } from "@/components/icons";
import { LocaleSwitch } from "@/components/locale-switch";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

/**
 * 站头。
 *
 * 现在只挂真实存在的去处 —— 下载和源码都是站外链接。文档 / 插件 / 工作流三项等对应的
 * 页面落地再加:一个指向 404 的导航比没有导航更糟。
 */
export function SiteHeader({ locale }: { locale: Locale }) {
  const t = getMessages(locale);

  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-3 px-6 sm:px-8">
        <Link href={localePath(locale)} className="flex items-center gap-2.5 font-medium">
          <Image src="/logo.svg" alt="" width={24} height={24} className="rounded-md" />
          <span className="tracking-tight">Open Studio</span>
        </Link>

        <div className="ml-auto flex items-center gap-0.5">
          <LocaleSwitch locale={locale} label={t.nav.language} />
          <ThemeToggle label={t.nav.theme} />
          <Button asChild variant="ghost" size="icon" title={t.nav.github}>
            <a href={SITE.repo} target="_blank" rel="noreferrer" aria-label={t.nav.github}>
              <GithubMark />
            </a>
          </Button>
          <Button asChild size="sm" className="ml-1.5">
            <a href={SITE.releases} target="_blank" rel="noreferrer">
              {t.nav.download}
            </a>
          </Button>
        </div>
      </div>
    </header>
  );
}
