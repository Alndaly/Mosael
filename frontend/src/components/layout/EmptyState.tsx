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
    <div className="empty-state">
      <div className="empty-state-icon">{icon}</div>
      {badge && <span className="empty-state-badge">{badge}</span>}
      <h2>{title}</h2>
      <p>{body}</p>
      {action}
    </div>
  );
}
