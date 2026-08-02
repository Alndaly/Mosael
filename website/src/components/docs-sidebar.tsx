"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * 文档侧边栏。
 *
 * 是客户端组件,只为了一件事:知道当前在哪一页。
 *
 * 分组和顺序在服务端算好了当 props 传进来 —— 这里**不能**从 `@/lib/docs` 里 import 任何
 * 东西,哪怕只是一个常量数组:那个模块 import 了 `node:fs`,而客户端组件的 import 会被
 * 整个打进浏览器包,构建直接失败。
 */
export type SidebarGroup = {
  label: string;
  items: { href: string; title: string }[];
};

export function DocsSidebar({ groups, className }: { groups: SidebarGroup[]; className?: string }) {
  const pathname = usePathname();

  return (
    <nav className={cn("font-sans text-sm", className)}>
      {groups.map((group) => (
        <div key={group.label} className="mb-7">
          <p className="m-0 mb-2 text-xs font-medium tracking-wide text-muted-foreground">{group.label}</p>
          <ul className="m-0 list-none space-y-px p-0">
            {group.items.map((item) => {
              const active = pathname === item.href;
              return (
                <li key={item.href} className="m-0">
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "-ml-2 block rounded-md px-2 py-1.5 transition-colors",
                      active
                        ? "bg-muted font-medium text-foreground"
                        : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                    )}
                  >
                    {item.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
