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
 * 东西,哪怕只是一个常量数组:那个模块 import 了 `node:fs`,而 client component 的 import
 * 会被整个打进浏览器包,构建直接失败。
 */
export type SidebarGroup = {
  label: string;
  items: { href: string; title: string }[];
};

export function DocsSidebar({
  groups,
  label,
  className,
}: {
  groups: SidebarGroup[];
  /** 窄屏折叠起来之后,那一行写什么。 */
  label: string;
  className?: string;
}) {
  const pathname = usePathname();

  const list = (
    <>
      {groups.map((group) => (
        <div key={group.label} className="mb-8">
          <p className="m-0 mb-3 font-mono text-xs font-bold tracking-widest text-flame uppercase">{group.label}</p>
          <ul className="m-0 list-none border-l-2 border-ink p-0">
            {group.items.map((item) => {
              const active = pathname === item.href;
              return (
                <li key={item.href} className="m-0">
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "-ml-0.5 block border-l-2 py-1.5 pl-4 transition-colors",
                      active
                        ? "border-flame font-bold text-foreground"
                        : "border-transparent text-muted-foreground hover:border-ink hover:text-foreground",
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
    </>
  );

  return (
    <>
      {/* 手机上把整棵目录塞在正文前面,要滚过两屏导航才看得到内容。折起来,想翻再点开。
          `<details>` 而不是自己写一套开合状态:无 JS 也能用,键盘和读屏软件都认。 */}
      <details className="border-2 border-ink text-sm lg:hidden">
        <summary className="cursor-pointer list-none px-4 py-3 font-display font-bold tracking-tight">{label}</summary>
        <div className="border-t-2 border-ink px-4 pt-4 pb-1">{list}</div>
      </details>
      <nav className={cn("hidden text-sm lg:block", className)}>{list}</nav>
    </>
  );
}
