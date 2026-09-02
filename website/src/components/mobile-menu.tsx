"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, Moon, Sun, X } from "lucide-react";
import { useTheme } from "next-themes";
import { createPortal } from "react-dom";

import { GithubMark } from "@/components/icons";
import { isNavLinkActive } from "@/components/nav-link";
import { LOCALE_LABEL, LOCALES, type Locale } from "@/i18n/config";
import { SITE } from "@/lib/site";
import { cn } from "@/lib/utils";

/**
 * 窄屏的导航。
 *
 * 手机上站头一行放不下「站名 + 三个入口 + 搜索 + 语言 + 主题 + GitHub + 下载」——
 * 实测在 390px 下右侧那一组会溢出 130px。所以窄屏只留站名、搜索、主题和这颗按钮,
 * 其余收进底下展开的一张面板。
 *
 * 展开时锁住页面滚动:面板是覆盖在内容上的,不锁的话手指一划底下的页面就跑了。
 * 换页自动收起 —— 点了链接还挂着一张菜单,是移动端最常见的那种"卡住了"的错觉。
 */
export function MobileMenu({
  locale,
  links,
  labels,
}: {
  locale: Locale;
  links: { href: string; match: string; exact?: boolean; label: string }[];
  labels: { menu: string; language: string; github: string; download: string; theme: string };
}) {
  const [open, setOpen] = React.useState(false);
  const [mounted, setMounted] = React.useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  const pathname = usePathname();

  React.useEffect(() => setMounted(true), []);
  const other = LOCALES.find((item) => item !== locale) ?? locale;
  const rest = pathname.split("/").slice(2).join("/");

  React.useEffect(() => setOpen(false), [pathname]);

  React.useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    const previous = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      root.style.overflow = previous;
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label={labels.menu}
        aria-expanded={open}
        className="inline-flex size-10 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground lg:hidden"
      >
        {open ? <X className="size-4" /> : <Menu className="size-4" />}
      </button>

      {mounted && open && createPortal(
        <div className="fixed inset-0 z-40 overflow-y-auto bg-paper/95 px-3 pt-24 backdrop-blur-xl lg:hidden">
          <nav className="mx-auto flex max-w-lg flex-col gap-1">
            {links.map((link) => {
              const active = isNavLinkActive(pathname, link.match, link.exact);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "rounded-2xl px-5 py-4 font-display text-xl font-semibold tracking-tight transition-colors",
                    active ? "bg-brand-soft text-primary" : "text-foreground hover:bg-secondary",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>

          <div className="mx-auto flex max-w-lg flex-col border-t border-border pt-4 pb-8">
            <Link
              href={`/${other}${rest ? `/${rest}` : ""}`}
              hrefLang={other}
              className="flex items-center justify-between border-b border-border px-1 py-3.5 font-medium"
            >
              {labels.language}
              <span className="font-mono text-xs tracking-wider uppercase">{LOCALE_LABEL[other]}</span>
            </Link>
            <button
              type="button"
              onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
              className="flex items-center justify-between border-b border-border px-1 py-3.5 font-medium"
            >
              {labels.theme}
              {/* 挂载前不画图标:服务端不知道用户的主题,直接画会 hydration 不一致。 */}
              {mounted ? (
                resolvedTheme === "dark" ? (
                  <Sun className="size-4" />
                ) : (
                  <Moon className="size-4" />
                )
              ) : (
                <span className="size-4" />
              )}
            </button>
            <a
              href={SITE.repo}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 border-b border-border px-1 py-3.5 font-medium"
            >
              <GithubMark className="size-4" />
              {labels.github}
            </a>
            <a
              href={SITE.releases}
              target="_blank"
              rel="noreferrer"
              className="mt-4 rounded-full bg-primary px-4 py-3 text-center font-semibold text-primary-foreground"
            >
              {labels.download}
            </a>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
