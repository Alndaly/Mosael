"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * 一套轻量 shadcn sidebar：左侧固定导航，窄屏折叠成抽屉。
 * 不引入额外依赖；视觉和交互交给 Tailwind + Button。
 */
type SidebarContextValue = { open: boolean; setOpen: (open: boolean) => void };
const SidebarContext = React.createContext<SidebarContextValue | null>(null);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  return (
    <SidebarContext.Provider value={{ open, setOpen }}>
      <div className="flex min-h-dvh w-full">{children}</div>
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  const value = React.useContext(SidebarContext);
  if (!value) throw new Error("useSidebar must be used inside SidebarProvider");
  return value;
}

export function Sidebar({ className, children }: { className?: string; children: React.ReactNode }) {
  const { open, setOpen } = useSidebar();
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <aside
        data-slot="sidebar"
        className={cn(
          "z-40 w-64 shrink-0 border-r border-border bg-card shadow-xl",
          "fixed inset-y-0 left-0 flex flex-col transition-transform md:sticky md:top-0 md:h-dvh md:self-start md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
          className,
        )}
      >
        {children}
      </aside>
    </>
  );
}

export function SidebarTrigger({ className, children, ...props }: Omit<React.ComponentProps<typeof Button>, "variant" | "size">) {
  const { setOpen } = useSidebar();
  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      className={cn("md:hidden", className)}
      onClick={() => setOpen(true)}
      {...props}
    >
      {children ?? "☰"}
    </Button>
  );
}

export function SidebarHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-header" className={cn("flex flex-col gap-1 border-b border-border p-4", className)} {...props} />;
}

export function SidebarContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-content" className={cn("flex-1 overflow-y-auto p-3", className)} {...props} />;
}

export function SidebarFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-footer" className={cn("border-t border-border p-3", className)} {...props} />;
}

export function SidebarGroup({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-group" className={cn("grid gap-1", className)} {...props} />;
}

export function SidebarGroupLabel({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-group-label" className={cn("px-2 py-2 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase", className)} {...props} />;
}

export function SidebarMenu({ className, ...props }: React.ComponentProps<"ul">) {
  return <ul data-slot="sidebar-menu" className={cn("m-0 grid list-none gap-1 p-0", className)} {...props} />;
}

export function SidebarMenuItem({ className, ...props }: React.ComponentProps<"li">) {
  return <li data-slot="sidebar-menu-item" className={cn("min-w-0", className)} {...props} />;
}

export function SidebarMenuButton({
  className,
  isActive = false,
  ...props
}: Omit<React.ComponentProps<typeof Button>, "variant" | "size"> & { isActive?: boolean }) {
  return (
    <Button
      type="button"
      variant="ghost"
      data-active={isActive ? "" : undefined}
      className={cn(
        "h-auto w-full justify-start gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium text-muted-foreground data-[active]:bg-secondary data-[active]:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function SidebarInset({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="sidebar-inset" className={cn("min-w-0 flex-1", className)} {...props} />;
}
