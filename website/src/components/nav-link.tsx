"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

export function isNavLinkActive(pathname: string, match: string, exact = false) {
  return exact ? pathname === match : pathname === match || pathname.startsWith(`${match}/`);
}

/** 站头导航项。首页必须精确匹配；文档等栏目按路径前缀匹配。 */
export function NavLink({
  href,
  match,
  exact = false,
  children,
}: {
  href: string;
  match?: string;
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
