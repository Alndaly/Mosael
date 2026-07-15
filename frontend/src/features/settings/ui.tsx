import React from "react";

/**
 * Shared settings building blocks: every section is a Group (title +
 * description + optional header actions) containing Rows (label +
 * description on the left, control on the right). Keeps all five sections
 * on one consistent grid instead of ad-hoc card layouts.
 */

export function SettingsGroup({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="sg">
      <header className="sg-head">
        <div className="sg-head-text">
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {actions && <div className="sg-head-actions">{actions}</div>}
      </header>
      <div className="sg-body">{children}</div>
    </section>
  );
}

export function SettingsRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="sg-row">
      <div className="sg-row-text">
        <span>{label}</span>
        {description && <small>{description}</small>}
      </div>
      {children && <div className="sg-row-control">{children}</div>}
    </div>
  );
}

/** Full-width slot inside a group (forms, QR panels, lists). */
export function SettingsBlock({ children }: { children: React.ReactNode }) {
  return <div className="sg-block">{children}</div>;
}
