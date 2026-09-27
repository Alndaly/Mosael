"use client";

/**
 * 审核(moderator 以上):插件上架前的队列、用户举报。
 *
 * 一份提交并排摊开与上一版的差异(ADR 0026 §4):权限增减、文件增删改、清单逐行 —— 审核的人要回答的
 * 问题是「这一版比上一版多要了什么、多带了什么」,而不是从头读一遍整个包。
 */
import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import * as React from "react";

import { usePaged } from "@/components/community/account";
import { isModerator, useRequireSession, type Session } from "@/components/community/session-provider";
import { BUTTON, INPUT, Notice, Segmented, Spinner, StatePanel, TEXTAREA, errorText } from "@/components/community/ui";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { diffLines, stableJson } from "@/lib/community/diff";
import { ENDPOINTS, REQUESTED, collection } from "@/lib/community/endpoints";
import { fill, formatBytes, formatDateTime } from "@/lib/community/format";
import type { QueueItem, Report, ReviewDiff } from "@/lib/community/types";
import { cn } from "@/lib/utils";

function DiffBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="grid min-w-0 gap-2">
      <h4 className="m-0 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h4>
      {children}
    </section>
  );
}

function PermissionDiff({ locale, current, added, removed }: { locale: Locale; current: string[]; added: string[]; removed: string[] }) {
  const t = getMessages(locale).admin;
  const fresh = new Set(added);
  const chip = "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-mono text-xs";
  if (current.length === 0 && removed.length === 0) return <span className="text-sm text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {/* 新要的权限最要紧:标红排前面。 */}
      {current
        .filter((one) => fresh.has(one))
        .map((one) => (
          <span key={`+${one}`} className={cn(chip, "border-destructive/40 bg-destructive/8 text-destructive")} title={t.added}>
            + {one}
          </span>
        ))}
      {removed.map((one) => (
        <span key={`-${one}`} className={cn(chip, "border-border text-muted-foreground line-through")} title={t.removed}>
          {one}
        </span>
      ))}
      {current
        .filter((one) => !fresh.has(one))
        .map((one) => (
          <span key={one} className={cn(chip, "border-border")} title={t.unchanged}>
            {one}
          </span>
        ))}
    </div>
  );
}

/**
 * 服务只给这一版的清单和顶层键的增删改;把上一版拼回来,再逐行比 —— 审核的人看到的是熟悉的行级差异,
 * 而不是一张键值表。
 */
function previousManifest(current: Record<string, unknown>, diff: ReviewDiff["manifest"]): Record<string, unknown> {
  const previous: Record<string, unknown> = { ...current };
  for (const key of Object.keys(diff.added)) delete previous[key];
  for (const [key, value] of Object.entries(diff.removed)) previous[key] = value;
  for (const [key, change] of Object.entries(diff.changed)) previous[key] = change.from;
  return previous;
}

function QueueCard({ locale, item, session, onDone }: { locale: Locale; item: QueueItem; session: Session; onDone: () => void }) {
  const t = getMessages(locale);
  const [rejecting, setRejecting] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const diff = item.diff;
  const hasPrevious = Boolean(diff?.previous_version);
  const manifest = item.manifest ?? {};
  const lines = diffLines(stableJson(hasPrevious && diff ? previousManifest(manifest, diff.manifest) : manifest), stableJson(manifest));
  const addedFiles = new Set(hasPrevious ? (diff?.files.added ?? []) : []);
  const changedFiles = new Set(diff?.files.changed ?? []);
  const touched = hasPrevious ? addedFiles.size + changedFiles.size + (diff?.files.removed.length ?? 0) : item.files.length;
  const marked = (path: string) => Number(addedFiles.has(path) || changedFiles.has(path));
  const files = [...item.files].sort((a, b) => marked(b.path) - marked(a.path));
  const newTools = new Set(hasPrevious ? (diff?.tools.added ?? []) : []);
  const effectTools = new Set(diff?.tools.effects_changed ?? []);

  const act = async (action: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      const path = action === "approve" ? ENDPOINTS.admin.approve(item.id) : ENDPOINTS.admin.reject(item.id);
      await session.communityFetch(path, { method: "POST", json: { note: action === "reject" ? reason.trim() : "" } });
      onDone();
    } catch (caught) {
      setError(caught);
      setBusy(false);
    }
  };

  return (
    <article className="grid gap-5 rounded-2xl border border-border bg-card p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid min-w-0 gap-1">
          <span className="text-xs text-muted-foreground">
            {t.account.kind[item.kind]} · {formatDateTime(item.created_at, locale)}
          </span>
          <h3 className="m-0 flex flex-wrap items-baseline gap-x-2 text-base font-semibold">
            <Link href={localePath(locale, item.item.path)} className="hover:text-primary">
              {item.item.title}
            </Link>
            <span className="font-mono text-sm font-normal text-muted-foreground">v{item.version}</span>
          </h3>
          <span className="flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
            {t.admin.submittedBy}
            <Link href={localePath(locale, `/u/${item.submitter.handle}`)} className="font-medium text-foreground hover:underline">
              @{item.submitter.handle}
            </Link>
          </span>
        </div>
        <span className="rounded-full bg-secondary px-2.5 py-1 text-xs text-muted-foreground">
          {hasPrevious && diff ? fill(t.admin.comparedTo, { version: diff.previous_version ?? "" }) : t.admin.firstVersion}
        </span>
      </header>

      {item.changelog && <p className="m-0 text-sm leading-6 whitespace-pre-line text-muted-foreground">{item.changelog}</p>}

      {item.kind === "asset" ? (
        <AssetReview locale={locale} item={item} />
      ) : (
        <>
        <DiffBlock title={t.admin.permissionsDiff}>
          <PermissionDiff locale={locale} current={item.permissions} added={diff?.permissions.added ?? []} removed={diff?.permissions.removed ?? []} />
        </DiffBlock>

        {(item.tools.length > 0 || (diff?.tools.removed.length ?? 0) > 0) && (
          <DiffBlock title={t.admin.toolsDiff}>
            <ul className="m-0 grid list-none gap-1 p-0 text-sm">
              {item.tools.map((tool) => (
                <li key={tool.name} className="flex flex-wrap items-baseline gap-x-2">
                  <code className={cn("rounded bg-secondary px-1.5 py-0.5 font-mono text-xs", newTools.has(tool.name) && "bg-primary/12 text-primary")}>
                    {newTools.has(tool.name) ? "+ " : ""}
                    {tool.name}
                  </code>
                  {effectTools.has(tool.name) && <span className="text-xs font-medium text-destructive">{t.admin.effectsChanged}</span>}
                </li>
              ))}
              {diff?.tools.removed.map((name) => (
                <li key={`-${name}`}>
                  <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs text-muted-foreground line-through">{name}</code>
                </li>
              ))}
            </ul>
          </DiffBlock>
        )}

        <DiffBlock title={`${t.admin.filesDiff} · ${touched}/${item.files.length}`}>
          <ul className="m-0 grid max-h-64 list-none gap-0.5 overflow-auto rounded-xl bg-secondary/40 p-3 font-mono text-xs">
            {files.map((file) => {
              const status = addedFiles.has(file.path) ? "added" : changedFiles.has(file.path) ? "changed" : "same";
              return (
                <li key={file.path} className="flex min-w-0 justify-between gap-4">
                  <span className={cn("truncate", status === "added" && "text-primary", status === "changed" && "text-[color:var(--tile-4)]")}>
                    {status === "added" ? "+ " : status === "changed" ? "~ " : "  "}
                    {file.path}
                  </span>
                  <span className="shrink-0 text-muted-foreground">{formatBytes(file.size)}</span>
                </li>
              );
            })}
            {diff?.files.removed.map((path) => (
              <li key={`-${path}`} className="truncate text-destructive line-through">
                − {path}
              </li>
            ))}
          </ul>
        </DiffBlock>

        {item.manifest && (
          <DiffBlock title={t.admin.manifestDiff}>
            <pre className="m-0 max-h-96 overflow-auto rounded-xl bg-secondary/40 p-3 font-mono text-xs leading-5">
              {lines.map((line, index) => (
                <div
                  key={index}
                  className={cn("whitespace-pre", line.kind === "added" && "bg-primary/10 text-primary", line.kind === "removed" && "bg-destructive/10 text-destructive")}
                >
                  {line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}
                  {line.text}
                </div>
              ))}
            </pre>
          </DiffBlock>
        )}
        </>
      )}

      {error ? <Notice tone="error">{errorText(error, t.community.genericError, t.community.networkError)}</Notice> : null}
      {rejecting ? (
        <div className="grid gap-3">
          <label className="grid gap-1.5 text-sm font-medium">
            {t.admin.rejectReason}
            <textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={5000} className={TEXTAREA} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy || !reason.trim()} onClick={() => void act("reject")} className={BUTTON.danger}>
              {busy && <Spinner />}
              {t.admin.reject}
            </button>
            <button type="button" disabled={busy} onClick={() => setRejecting(false)} className={BUTTON.ghost}>
              {t.community.cancel}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => void act("approve")} className={BUTTON.primary}>
            {busy && <Spinner />}
            {t.admin.approve}
          </button>
          <button type="button" disabled={busy} onClick={() => setRejecting(true)} className={BUTTON.secondary}>
            {t.admin.reject}
          </button>
        </div>
      )}
    </article>
  );
}

/**
 * 资产的审核(只有声明为真人的人物会进队列):授权声明,和参考图墙 —— 审核员对着图判断「这是不是本人 /
 * 有没有同意公开」,所以图要大到看得清脸,不是一排缩略图。
 */
function AssetReview({ locale, item }: { locale: Locale; item: QueueItem }) {
  const t = getMessages(locale);
  const bundle = item.bundle;
  if (!bundle) return null;
  const references = [...bundle.references, ...(bundle.variants ?? []).flatMap((variant) => variant.references)];
  return (
    <>
      <DiffBlock title={t.admin.consentTitle}>
        <p className="m-0 text-sm leading-6">
          <strong className="font-semibold">
            {item.consent_kind === "self" ? t.admin.consentSelf : item.consent_kind === "authorized" ? t.admin.consentAuthorized : t.admin.consentMissing}
          </strong>
        </p>
        <p className="mt-1 mb-0 text-xs leading-5 text-muted-foreground">{t.admin.assetReviewNote}</p>
      </DiffBlock>
      <DiffBlock title={`${t.assets.referencesTitle} · ${references.length}`}>
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-2 p-0">
          {references.map((reference) => {
            const url = item.media?.[reference.sha256]?.url;
            const role = t.assets.roles[reference.role as keyof typeof t.assets.roles] ?? reference.role;
            return (
              <li key={reference.sha256} className="relative overflow-hidden rounded-xl border border-border bg-secondary/40">
                {url ? (
                  // oxlint-disable-next-line nextjs/no-img-element
                  <img src={url} alt={role} loading="lazy" className="aspect-square w-full object-cover" />
                ) : (
                  <span className="grid aspect-square place-items-center text-xs text-muted-foreground">{reference.sha256.slice(0, 8)}</span>
                )}
                <span className="absolute bottom-1.5 left-1.5 rounded-full bg-background/85 px-2 py-0.5 text-[0.6875rem] font-medium">{role}</span>
              </li>
            );
          })}
        </ul>
      </DiffBlock>
      {bundle.prompt && (
        <DiffBlock title={t.assets.prompt}>
          <p className="m-0 font-mono text-xs leading-5 text-muted-foreground">{bundle.prompt}</p>
        </DiffBlock>
      )}
    </>
  );
}

function ReportCard({ locale, report, session, onDone }: { locale: Locale; report: Report; session: Session; onDone: () => void }) {
  const t = getMessages(locale);
  const [hiding, setHiding] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const { kind, slug, title } = report.target;
  const href = slug ? (kind === "share" ? `/b/${slug}` : `${collection(kind)}/${slug}`) : null;
  const reasonLabel = (t.community.reportReasons as Record<string, string>)[report.reason] ?? report.reason;

  const run = async (path: string, body: unknown) => {
    setBusy(true);
    setError(null);
    try {
      await session.communityFetch(path, { method: "POST", json: body });
      onDone();
    } catch (caught) {
      setError(caught);
      setBusy(false);
    }
  };

  return (
    <article className="grid gap-3 rounded-2xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {href ? (
          // 整页加载:举报的可能是分享画板,它的 CSP 要随文档一起到(见 cards.tsx 的 BoardCard)。
          <a href={localePath(locale, href)} className="font-semibold hover:text-primary">
            {title ?? slug}
          </a>
        ) : (
          <span className="font-semibold text-muted-foreground">—</span>
        )}
        <span className="text-xs text-muted-foreground">{kind === "share" ? t.nav.boards : t.account.kind[kind]}</span>
        <span className="rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-medium text-destructive">{reasonLabel}</span>
        <span className="ml-auto text-xs text-muted-foreground">{formatDateTime(report.created_at, locale)}</span>
      </div>
      {report.detail && <p className="m-0 text-sm leading-6 whitespace-pre-line text-muted-foreground">{report.detail}</p>}
      {report.reporter && (
        <span className="flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
          {t.admin.reportedBy}
          <span>@{report.reporter.handle}</span>
        </span>
      )}
      {error ? <Notice tone="error">{errorText(error, t.community.genericError, t.community.networkError)}</Notice> : null}
      {hiding && slug ? (
        <div className="grid gap-3">
          <label className="grid gap-1.5 text-sm font-medium">
            {t.admin.hideReason}
            <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} className={INPUT} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy || !reason.trim()}
              onClick={() => void run(ENDPOINTS.admin.hide(kind, slug), { hidden: true, reason: reason.trim() })}
              className={BUTTON.danger}
            >
              {busy && <Spinner />}
              {t.admin.confirm}
            </button>
            <button type="button" disabled={busy} onClick={() => setHiding(false)} className={BUTTON.ghost}>
              {t.community.cancel}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {slug && (
            <button type="button" onClick={() => setHiding(true)} className={BUTTON.danger}>
              {t.admin.hide}
            </button>
          )}
          <button type="button" disabled={busy} onClick={() => void run(REQUESTED.dismissReport(report.id), {})} className={BUTTON.ghost}>
            {t.admin.dismiss}
          </button>
        </div>
      )}
    </article>
  );
}

function Queue({ locale, session }: { locale: Locale; session: Session }) {
  const t = getMessages(locale);
  const list = usePaged<QueueItem>(session, ENDPOINTS.admin.queue);
  if (list.error) return <Notice tone="error">{errorText(list.error, t.community.genericError, t.community.networkError)}</Notice>;
  if (!list.items) return <Spinner className="text-muted-foreground" />;
  if (list.items.length === 0) return <StatePanel title={t.admin.emptyQueue} />;
  return (
    <div className="grid gap-5">
      {list.items.map((item) => (
        <QueueCard key={item.id} locale={locale} item={item} session={session} onDone={() => list.setItems((items) => items?.filter((one) => one.id !== item.id) ?? null)} />
      ))}
      {list.cursor && (
        <button type="button" onClick={list.loadMore} disabled={list.loading} className={cn(BUTTON.secondary, "w-fit")}>
          {t.community.loadMore}
        </button>
      )}
    </div>
  );
}

function Reports({ locale, session }: { locale: Locale; session: Session }) {
  const t = getMessages(locale);
  const list = usePaged<Report>(session, ENDPOINTS.admin.reports);
  if (list.error) return <Notice tone="error">{errorText(list.error, t.community.genericError, t.community.networkError)}</Notice>;
  if (!list.items) return <Spinner className="text-muted-foreground" />;
  if (list.items.length === 0) return <StatePanel title={t.admin.emptyReports} />;
  return (
    <div className="grid gap-4">
      {list.items.map((report) => (
        <ReportCard
          key={report.id}
          locale={locale}
          report={report}
          session={session}
          onDone={() => list.setItems((items) => items?.filter((one) => one.id !== report.id) ?? null)}
        />
      ))}
      {list.cursor && (
        <button type="button" onClick={list.loadMore} disabled={list.loading} className={cn(BUTTON.secondary, "w-fit")}>
          {t.community.loadMore}
        </button>
      )}
    </div>
  );
}

export function AdminPage({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const session = useRequireSession(locale);
  const [tab, setTab] = React.useState<"queue" | "reports">("queue");

  if (session.status !== "authenticated") {
    return (
      <p className="m-0 inline-flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        {t.auth.checking}
      </p>
    );
  }
  if (!isModerator(session.user)) {
    return <StatePanel icon={<ShieldAlert className="size-7 text-muted-foreground" aria-hidden />} title={t.admin.forbidden} />;
  }

  return (
    <div className="grid gap-6">
      <div className="max-w-xs">
        <Segmented
          label={t.admin.title}
          value={tab}
          onChange={setTab}
          options={[
            { id: "queue", label: t.admin.queue },
            { id: "reports", label: t.admin.reports },
          ]}
        />
      </div>
      {tab === "queue" ? <Queue locale={locale} session={session} /> : <Reports locale={locale} session={session} />}
    </div>
  );
}
