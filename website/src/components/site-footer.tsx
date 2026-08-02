import Image from "next/image";
import Link from "next/link";

import { GithubMark } from "@/components/icons";
import { localePath, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { SITE } from "@/lib/site";

/**
 * 站脚。
 *
 * 三列的**分组按去处的性质分**,不按页面在导航里的位置分:
 *   文档 —— 读的东西
 *   社区 —— 可以往里加东西的地方(插件、工作流)
 *   项目 —— 关于这个软件本身(源码、下载、反馈)
 * 上一版把「工作流」挂在「插件」标题下面,那是拿第一项当了组名 —— 组里第二项一出现就说不通。
 */
export function SiteFooter({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const year = new Date().getFullYear();

  const columns = [
    {
      title: t.docs.title,
      links: [
        { label: t.docs.sections.start, href: localePath(locale, "/docs/start/intro") },
        { label: t.docs.sections.guides, href: localePath(locale, "/docs/guides/providers") },
        { label: t.docs.sections.about, href: localePath(locale, "/docs/about/project") },
      ],
    },
    {
      title: t.footer.community,
      links: [
        { label: t.nav.plugins, href: localePath(locale, "/plugins") },
        { label: t.nav.workflows, href: localePath(locale, "/workflows") },
      ],
    },
    {
      title: t.footer.project,
      links: [
        { label: t.footer.github, href: SITE.repo, external: true },
        { label: t.footer.download, href: SITE.releases, external: true },
        { label: t.footer.issues, href: `${SITE.repo}/issues`, external: true },
      ],
    },
  ];

  return (
    <footer className="border-t-2 border-ink bg-invert text-invert-foreground">
      <div className="mx-auto max-w-[96rem] px-5 py-16 sm:px-8">
        <div className="grid gap-12 md:grid-cols-2 lg:grid-cols-[1.4fr_repeat(3,1fr)] lg:gap-16">
          <div>
            <Link href={localePath(locale)} className="flex items-center gap-3">
              <Image src="/mark.svg" alt="" width={32} height={32} />
              <span className="font-display text-lg font-extrabold tracking-tight uppercase">Open Studio</span>
            </Link>
            <p className="mt-5 mb-0 max-w-xs text-invert-foreground/70">{t.footer.tagline}</p>
            <a
              className="mt-7 inline-flex items-center gap-2 border-2 border-invert-foreground bg-flame px-5 py-2.5 text-sm font-bold text-primary-foreground transition-transform hover:-translate-y-0.5"
              href={SITE.releases}
              target="_blank"
              rel="noreferrer"
            >
              {t.footer.download}
            </a>
          </div>

          {columns.map((column) => (
            <nav key={column.title} className="text-sm">
              <p className="m-0 mb-4 font-mono text-xs font-bold tracking-widest text-flame uppercase">
                {column.title}
              </p>
              <ul className="m-0 list-none space-y-3 p-0">
                {column.links.map((link) => (
                  <li key={link.href} className="m-0">
                    {"external" in link && link.external ? (
                      <a
                        className="inline-flex items-center gap-1.5 text-invert-foreground/70 transition-colors hover:text-invert-foreground"
                        href={link.href}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {link.label === t.footer.github && <GithubMark className="size-3.5" />}
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        className="text-invert-foreground/70 transition-colors hover:text-invert-foreground"
                        href={link.href}
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
      </div>

      <div className="border-t-2 border-invert-foreground/20">
        <div className="mx-auto flex max-w-[96rem] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-6 font-mono text-xs tracking-wider text-invert-foreground/50 uppercase sm:px-8">
          <span>
            © {year} Open Studio. {t.footer.rights}
          </span>
          <a className="ml-auto transition-colors hover:text-invert-foreground" href={SITE.email}>
            {t.footer.contact}
          </a>
        </div>
      </div>
    </footer>
  );
}
