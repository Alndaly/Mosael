"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * 这一项在当前页上算不算「在这儿」。`match` 可以给几个前缀:一个导航项下面可以有几个分区 ——
 * 「社区」同时管着 /plugins 和 /workflows,两处的地址都不改(插件清单里的文档链接指着它们)。
 */
export function isNavLinkActive(pathname: string, match: string | readonly string[], exact = false) {
  const prefixes = typeof match === "string" ? [match] : match;
  return prefixes.some((prefix) =>
    exact ? pathname === prefix : pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/** 站头导航项。首页必须精确匹配；文档等栏目按路径前缀匹配。 */
export function NavLink({
  href,
  match,
  exact = false,
  children,
}: {
  href: string;
  match?: string | readonly string[];
  exact?: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const cleanHref = href.split("#")[0];
  const active = cleanHref !== "" && isNavLinkActive(pathname, match ?? cleanHref, exact);

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative rounded-full px-3.5 py-2 whitespace-nowrap transition-colors",
        active
          ? "bg-brand-soft text-primary"
          : "text-muted-foreground hover:bg-secondary/75 hover:text-foreground",
      )}
    >
      {children}
    </Link>
  );
}
