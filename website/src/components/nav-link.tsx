"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * 站头导航项。当前区段用一条朱色底线标出 —— 按前缀判断,`/zh/docs/guides/x` 也算在「文档」里。
 * 用底线而不是换底色:顶栏本来就只有一条墨线和一个朱色按钮,再加一块底色会打架。
 */
export function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "border-b-2 px-2 py-1 whitespace-nowrap transition-colors",
        active ? "border-flame text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </Link>
  );
}
