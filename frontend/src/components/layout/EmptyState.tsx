import React from "react";

export function EmptyState({
  icon,
  title,
  body,
  badge,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  badge?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state m-auto grid max-w-[420px] justify-items-center gap-2 px-5 py-8 text-center [&_h2]:mt-0.5 [&_h2]:text-sm [&_h2]:font-[650] [&_p]:mb-1.5 [&_p]:mt-0 [&_p]:text-[13px] [&_p]:leading-[1.55] [&_p]:text-muted-foreground">
      <div className="grid h-11 w-11 place-items-center rounded-lg border border-[color-mix(in_oklab,var(--primary)_18%,var(--border))] bg-[color-mix(in_oklab,var(--primary)_6%,var(--panel))] text-primary">{icon}</div>
      {badge && <span className="rounded-full border border-border bg-secondary px-[9px] py-px text-[11px] font-semibold text-muted-foreground">{badge}</span>}
      <h2>{title}</h2>
      <p>{body}</p>
      {action}
    </div>
  );
}
