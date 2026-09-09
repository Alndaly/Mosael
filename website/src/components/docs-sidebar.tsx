"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export type SidebarGroup = {
  label: string;
  items: { href: string; title: string }[];
};

export function DocsLinks({ groups, onNavigate }: { groups: SidebarGroup[]; onNavigate?: () => void }) {
  const pathname = usePathname();
  return <div className="space-y-5">
    {groups.map((group) => <section key={group.label}>
      <h2 className="m-0 mb-1.5 px-2 text-xs font-semibold text-muted-foreground">{group.label}</h2>
      <ul className="m-0 list-none space-y-0.5 p-0">
        {group.items.map((item) => <li key={item.href}>
          <Link href={item.href} onClick={onNavigate} aria-current={pathname === item.href ? "page" : undefined}
            className={cn("block rounded-md px-2 py-2 text-sm leading-5 transition-colors focus-visible:outline-2 focus-visible:outline-ring",
              pathname === item.href ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground")}>
            {item.title}
          </Link>
        </li>)}
      </ul>
    </section>)}
  </div>;
}

export function DocsSidebar({ groups, label, className }: { groups: SidebarGroup[]; label: string; className?: string }) {
  return <nav aria-label={label} className={cn("hidden text-sm lg:block", className)}><DocsLinks groups={groups} /></nav>;
}
