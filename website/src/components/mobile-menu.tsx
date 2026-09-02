"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, Moon, Sun, X } from "lucide-react";
import { useTheme } from "next-themes";

import { GithubMark } from "@/components/icons";
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
  links: { href: string; label: string }[];
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
        className="inline-flex size-10 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground lg:hidden"
      >
        {open ? <X className="size-4" /> : <Menu className="size-4" />}
      </button>

      {open && (
        <div className="fixed inset-x-0 top-[4.5rem] bottom-0 z-40 overflow-y-auto border-t border-border bg-paper lg:hidden">
          <nav className="flex flex-col px-5 pt-6">
            {links.map((link) => {
              const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "rounded-xl px-4 py-4 font-display text-xl font-semibold tracking-tight transition-colors",
                    active ? "bg-brand-soft text-primary" : "text-foreground hover:bg-secondary",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex flex-col gap-2 px-5 pt-6 pb-8">
            <Link
              href={`/${other}${rest ? `/${rest}` : ""}`}
              hrefLang={other}
              className="flex items-center justify-between rounded-xl border border-border px-4 py-3 font-medium"
            >
              {labels.language}
              <span className="font-mono text-xs tracking-wider uppercase">{LOCALE_LABEL[other]}</span>
            </Link>
            <button
              type="button"
              onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
              className="flex items-center justify-between rounded-xl border border-border px-4 py-3 font-medium"
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
              className="flex items-center gap-2 rounded-xl border border-border px-4 py-3 font-medium"
            >
              <GithubMark className="size-4" />
              {labels.github}
            </a>
            <a
              href={SITE.releases}
              target="_blank"
              rel="noreferrer"
              className="rounded-xl bg-primary px-4 py-3 text-center font-semibold text-primary-foreground"
            >
              {labels.download}
            </a>
          </div>
        </div>
      )}
    </>
  );
}
