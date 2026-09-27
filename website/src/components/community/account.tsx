"use client";

/**
 * 「我的账号」:资料、密码、设备与会话、我的提交、我的分享。全在浏览器里取 —— 这些接口要令牌,
 * 而令牌只在内存里。
 *
 * 各块的锚点(#sessions、#submissions、#shares)和站头账号菜单里的链接对应。
 */
import Link from "next/link";
import { Check, Copy, ExternalLink, Laptop, Trash2 } from "lucide-react";
import * as React from "react";

import { Avatar } from "@/components/community/header-menus";
import { useRequireSession, type Session } from "@/components/community/session-provider";
import { BUTTON, Field, INPUT, Notice, Spinner, SubmitButton, errorText, useCopy } from "@/components/community/ui";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { fill, formatDate, formatDateTime } from "@/lib/community/format";
import { validHandle, validPassword } from "@/lib/community/input";
import { uploadBlob } from "@/lib/community/upload";
import type { Page, SessionInfo, ShareSummary, Submission, User, Visibility } from "@/lib/community/types";
import { cn } from "@/lib/utils";

/** 一个游标分页的列表:取第一页、加载更多、就地改删。 */
export function usePaged<T>(session: Pick<Session, "status" | "communityFetch">, path: string) {
  const { status, communityFetch } = session;
  const [items, setItems] = React.useState<T[] | null>(null);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [loading, setLoading] = React.useState(false);

  // 第一页:登录好了就取。状态只在请求回来之后改(effect 里不同步 setState)。
  React.useEffect(() => {
    if (status !== "authenticated") return;
    let cancelled = false;
    communityFetch<Page<T>>(path).then(
      (page) => {
        if (cancelled) return;
        setItems(page.items);
        setCursor(page.next_cursor);
        setError(null);
      },
      (caught: unknown) => {
        if (!cancelled) setError(caught);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [status, communityFetch, path]);

  const loadMore = async () => {
    if (!cursor) return;
    setLoading(true);
    setError(null);
    try {
      const separator = path.includes("?") ? "&" : "?";
      const page = await communityFetch<Page<T>>(`${path}${separator}cursor=${encodeURIComponent(cursor)}`);
      setItems((current) => [...(current ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(caught);
    } finally {
      setLoading(false);
    }
  };

  return { items, setItems, cursor, error, loading: loading || (items === null && !error), loadMore: () => void loadMore() };
}

function Panel({ id, title, lede, children }: { id: string; title: string; lede?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="grid scroll-mt-28 gap-4">
      <div className="grid gap-1 border-b border-border pb-3">
        <h2 className="m-0 text-lg font-semibold tracking-tight">{title}</h2>
        {lede && <p className="m-0 text-sm text-muted-foreground">{lede}</p>}
      </div>
      {children}
    </section>
  );
}

function ListState({ locale, loading, error, empty, onMore, hasMore }: { locale: Locale; loading: boolean; error: unknown; empty?: string | null; onMore: () => void; hasMore: boolean }) {
  const t = getMessages(locale).community;
  return (
    <>
      {error ? <Notice tone="error">{errorText(error, t.genericError, t.networkError)}</Notice> : null}
      {empty && <p className="m-0 rounded-2xl border border-dashed border-border px-5 py-8 text-center text-sm text-muted-foreground">{empty}</p>}
      {loading && <Spinner className="text-muted-foreground" />}
      {hasMore && !loading && (
        <button type="button" onClick={onMore} className={cn(BUTTON.secondary, "w-fit")}>
          {t.loadMore}
        </button>
      )}
    </>
  );
}

function ProfilePanel({ locale, session, user }: { locale: Locale; session: Session; user: User }) {
  const t = getMessages(locale);
  const [displayName, setDisplayName] = React.useState(user.display_name);
  const [handle, setHandle] = React.useState(user.handle);
  const [avatar, setAvatar] = React.useState<File | null>(null);
  const [pending, setPending] = React.useState(false);
  const [message, setMessage] = React.useState<{ tone: "error" | "success"; text: string } | null>(null);
  const changeable = user.handle_changeable !== false;
  const handleInvalid = handle !== user.handle && !validHandle(handle);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (handleInvalid) return;
    const changes: Record<string, string> = {};
    if (displayName.trim() !== user.display_name) changes.display_name = displayName.trim();
    if (changeable && handle !== user.handle) changes.handle = handle;
    setPending(true);
    setMessage(null);
    try {
      // 头像先按 ADR 的直传流程传到存储(按内容哈希去重),再在资料里指向那个哈希。
      if (avatar) changes.avatar_sha256 = await uploadBlob(session.communityFetch, avatar);
      const updated = await session.communityFetch<User>(ENDPOINTS.me.self, { method: "PATCH", json: changes });
      session.client?.updateUser(updated);
      setAvatar(null);
      setMessage({ tone: "success", text: t.account.saved });
    } catch (caught) {
      setMessage({ tone: "error", text: errorText(caught, t.community.genericError, t.community.networkError) });
    } finally {
      setPending(false);
    }
  };

  return (
    <Panel id="profile" title={t.account.profile}>
      <form className="grid gap-5" onSubmit={(event) => void save(event)}>
        <div className="flex items-center gap-4">
          <Avatar user={user} size="lg" />
          <label className={cn(BUTTON.secondary, "cursor-pointer")}>
            {t.account.chooseAvatar}
            <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(event) => setAvatar(event.target.files?.[0] ?? null)} />
          </label>
          {avatar && <span className="min-w-0 truncate text-xs text-muted-foreground">{avatar.name}</span>}
        </div>
        <Field label={t.account.displayName} htmlFor="account-name">
          <input id="account-name" maxLength={40} value={displayName} onChange={(event) => setDisplayName(event.target.value)} className={INPUT} />
        </Field>
        <Field
          label={t.account.handle}
          htmlFor="account-handle"
          hint={changeable ? `${t.auth.handleHint} · ${t.account.handleOnce}` : t.account.handleLocked}
          error={handleInvalid ? t.auth.invalidHandle : null}
        >
          <input
            id="account-handle"
            value={handle}
            disabled={!changeable}
            autoCapitalize="none"
            spellCheck={false}
            onChange={(event) => setHandle(event.target.value.toLowerCase())}
            className={cn(INPUT, "font-mono")}
          />
        </Field>
        <Field label={t.account.phone}>
          <p className="m-0 font-mono text-sm text-muted-foreground">{user.phone || t.account.notBound}</p>
        </Field>
        {message && <Notice tone={message.tone}>{message.text}</Notice>}
        <SubmitButton pending={pending} pendingLabel={t.account.saving} className="w-fit">
          {t.account.save}
        </SubmitButton>
      </form>
    </Panel>
  );
}

function PasswordPanel({ locale, session, user }: { locale: Locale; session: Session; user: User }) {
  const t = getMessages(locale);
  const hasPassword = user.has_password !== false;
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [message, setMessage] = React.useState<{ tone: "error" | "success"; text: string } | null>(null);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setMessage(null);
    if (!validPassword(next)) return setMessage({ tone: "error", text: t.auth.invalidPassword });
    setPending(true);
    try {
      await session.communityFetch(ENDPOINTS.me.password, { method: "POST", json: { ...(hasPassword ? { current_password: current } : {}), new_password: next } });
      session.client?.updateUser({ ...user, has_password: true });
      setCurrent("");
      setNext("");
      setMessage({ tone: "success", text: t.account.passwordChanged });
    } catch (caught) {
      setMessage({ tone: "error", text: errorText(caught, t.community.genericError, t.community.networkError) });
    } finally {
      setPending(false);
    }
  };

  return (
    <Panel id="password" title={t.account.security} lede={hasPassword ? undefined : t.account.noPasswordYet}>
      <form className="grid gap-5" onSubmit={(event) => void save(event)}>
        {/* 给密码管理器一个用户名字段,它才知道这是哪个账号的密码。 */}
        <input type="text" autoComplete="username" value={user.handle} readOnly hidden />
        {hasPassword && (
          <Field label={t.account.currentPassword} htmlFor="account-current">
            <input id="account-current" type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} className={INPUT} />
          </Field>
        )}
        <Field label={t.account.newPassword} htmlFor="account-new" hint={t.auth.passwordHint}>
          <input id="account-new" type="password" autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} className={INPUT} />
        </Field>
        {message && <Notice tone={message.tone}>{message.text}</Notice>}
        <SubmitButton pending={pending} className="w-fit">
          {hasPassword ? t.account.changePassword : t.account.setPassword}
        </SubmitButton>
      </form>
    </Panel>
  );
}

function SessionsPanel({ locale, session }: { locale: Locale; session: Session }) {
  const t = getMessages(locale);
  const list = usePaged<SessionInfo>(session, ENDPOINTS.me.sessions);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<unknown>(null);

  const revoke = async (one: SessionInfo) => {
    if (!window.confirm(t.account.revokeConfirm)) return;
    setBusy(one.id);
    setError(null);
    try {
      await session.communityFetch(ENDPOINTS.me.session(one.id), { method: "DELETE" });
      if (one.current) {
        session.client?.forget();
        return;
      }
      list.setItems((items) => items?.filter((item) => item.id !== one.id) ?? null);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel id="sessions" title={t.account.sessions} lede={t.account.sessionsLede}>
      {list.items && list.items.length > 0 && (
        <ul className="m-0 grid list-none gap-0 overflow-hidden rounded-2xl border border-border bg-card p-0">
          {list.items.map((one) => (
            <li key={one.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-border px-5 py-4 not-last:border-b">
              <Laptop className="size-5 shrink-0 text-muted-foreground" aria-hidden />
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                  <span className="truncate">{one.device_name || one.user_agent || t.account.unknownDevice}</span>
                  {one.current && <span className="rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-primary">{t.account.thisDevice}</span>}
                </span>
                <span className="text-xs text-muted-foreground">
                  {t.account.lastUsed} {formatDateTime(one.last_used_at, locale)}
                  {one.ip ? ` · ${one.ip}` : ""} · {t.account.signedIn} {formatDate(one.created_at, locale)}
                </span>
              </div>
              <button type="button" onClick={() => void revoke(one)} disabled={busy === one.id} className={cn(BUTTON.danger, "min-h-9 px-4")}>
                {busy === one.id && <Spinner />}
                {t.account.revoke}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error ? <Notice tone="error">{errorText(error, t.community.genericError, t.community.networkError)}</Notice> : null}
      <ListState locale={locale} loading={list.loading} error={list.error} onMore={list.loadMore} hasMore={Boolean(list.cursor)} />
    </Panel>
  );
}

type ShownStatus = "pending" | "approved" | "published" | "rejected" | "hidden";

const STATUS_CLASS: Record<ShownStatus, string> = {
  pending: "bg-secondary text-muted-foreground",
  approved: "bg-brand-soft text-primary",
  published: "bg-brand-soft text-primary",
  rejected: "bg-destructive/10 text-destructive",
  hidden: "bg-destructive/10 text-destructive",
};

/** 给人看的状态:被下架的整项优先;工作流通过即发布,叫「已发布」;插件叫「已通过」。 */
function shownStatus(one: Submission): ShownStatus {
  if (one.hidden) return "hidden";
  if (one.status === "approved") return one.kind === "workflow" ? "published" : "approved";
  return one.status ?? "pending";
}

function SubmissionsPanel({ locale, session }: { locale: Locale; session: Session }) {
  const t = getMessages(locale);
  const list = usePaged<Submission>(session, ENDPOINTS.me.submissions);
  return (
    <Panel id="submissions" title={t.account.submissions} lede={t.account.submissionsLede}>
      <div className="flex flex-wrap gap-2">
        <Link href={localePath(locale, "/workflows/new")} className={cn(BUTTON.secondary, "min-h-9")}>
          {t.workflows.submit}
        </Link>
        <Link href={localePath(locale, "/plugins/new")} className={cn(BUTTON.secondary, "min-h-9")}>
          {t.plugins.submit}
        </Link>
      </div>
      {list.items && list.items.length > 0 && (
        <ul className="m-0 grid list-none gap-0 overflow-hidden rounded-2xl border border-border bg-card p-0">
          {list.items.map((one) => {
            const status = shownStatus(one);
            const visible = status === "approved" || status === "published";
            const href = localePath(locale, one.path);
            return (
              <li key={one.id} className="grid gap-1.5 border-border px-5 py-4 not-last:border-b">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-xs text-muted-foreground">{t.account.kind[one.kind]}</span>
                  {visible ? (
                    <Link href={href} className="font-semibold hover:text-primary">
                      {one.title}
                    </Link>
                  ) : (
                    <span className="font-semibold">{one.title}</span>
                  )}
                  <span className="font-mono text-xs text-muted-foreground">v{one.version}</span>
                  <span className={cn("ml-auto rounded-full px-2.5 py-0.5 text-xs font-medium", STATUS_CLASS[status])}>{t.account.status[status]}</span>
                </div>
                <span className="text-xs text-muted-foreground">{formatDate(one.created_at, locale)}</span>
                {one.review_note && <p className="m-0 text-sm text-muted-foreground">{fill(t.account.reason, { reason: one.review_note })}</p>}
              </li>
            );
          })}
        </ul>
      )}
      <ListState
        locale={locale}
        loading={list.loading}
        error={list.error}
        empty={list.items && list.items.length === 0 ? t.account.noSubmissions : null}
        onMore={list.loadMore}
        hasMore={Boolean(list.cursor)}
      />
    </Panel>
  );
}

function ShareRow({ locale, share, session, onChange, onRemove }: { locale: Locale; share: ShareSummary; session: Session; onChange: (next: ShareSummary) => void; onRemove: () => void }) {
  const t = getMessages(locale);
  const [copied, copy] = useCopy();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const href = localePath(locale, `/b/${share.slug}`);

  const setVisibility = async (visibility: Visibility) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await session.communityFetch<ShareSummary | undefined>(ENDPOINTS.shares.detail(share.slug), { method: "PATCH", json: { visibility } });
      onChange(updated ?? { ...share, visibility });
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!window.confirm(t.account.revokeShareConfirm)) return;
    setBusy(true);
    setError(null);
    try {
      await session.communityFetch(ENDPOINTS.shares.detail(share.slug), { method: "DELETE" });
      onRemove();
    } catch (caught) {
      setError(caught);
      setBusy(false);
    }
  };

  return (
    <li className="grid gap-2 border-border px-5 py-4 not-last:border-b">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* 整页加载进分享页,它的 CSP 才生效(见 cards.tsx 的 BoardCard)。 */}
        <a href={href} className="min-w-0 truncate font-semibold hover:text-primary">
          {share.title || t.boards.untitled}
        </a>
        <span className="text-xs text-muted-foreground">
          {t.account.visibility[share.visibility]} · {formatDate(share.updated_at, locale)}
        </span>
        <div className="ml-auto flex flex-wrap gap-1.5">
          <button type="button" onClick={() => copy(`${window.location.origin}${href}`)} className={cn(BUTTON.ghost, "min-h-8")}>
            {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
            {copied ? t.account.copied : t.account.copyLink}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void setVisibility(share.visibility === "public" ? "unlisted" : "public")}
            className={cn(BUTTON.ghost, "min-h-8")}
          >
            <ExternalLink className="size-4" aria-hidden />
            {share.visibility === "public" ? t.account.makeUnlisted : t.account.makePublic}
          </button>
          <button type="button" disabled={busy} onClick={() => void revoke()} className={cn(BUTTON.ghost, "min-h-8 hover:text-destructive")}>
            <Trash2 className="size-4" aria-hidden />
            {t.account.revokeShare}
          </button>
        </div>
      </div>
      {error ? <Notice tone="error">{errorText(error, t.community.genericError, t.community.networkError)}</Notice> : null}
    </li>
  );
}

function SharesPanel({ locale, session }: { locale: Locale; session: Session }) {
  const t = getMessages(locale);
  const list = usePaged<ShareSummary>(session, ENDPOINTS.me.shares);
  return (
    <Panel id="shares" title={t.account.shares} lede={t.account.sharesLede}>
      {list.items && list.items.length > 0 && (
        <ul className="m-0 grid list-none gap-0 overflow-hidden rounded-2xl border border-border bg-card p-0">
          {list.items.map((share) => (
            <ShareRow
              key={share.slug}
              locale={locale}
              share={share}
              session={session}
              onChange={(next) => list.setItems((items) => items?.map((item) => (item.slug === share.slug ? next : item)) ?? null)}
              onRemove={() => list.setItems((items) => items?.filter((item) => item.slug !== share.slug) ?? null)}
            />
          ))}
        </ul>
      )}
      <ListState
        locale={locale}
        loading={list.loading}
        error={list.error}
        empty={list.items && list.items.length === 0 ? t.account.noShares : null}
        onMore={list.loadMore}
        hasMore={Boolean(list.cursor)}
      />
    </Panel>
  );
}

export function AccountPage({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const session = useRequireSession(locale);
  const { user, status } = session;

  // 从站头菜单点「我的分享」进来时,列表是异步取到的:取到之后再滚到锚点。
  React.useEffect(() => {
    if (status !== "authenticated" || !window.location.hash) return;
    const timer = window.setTimeout(() => document.getElementById(window.location.hash.slice(1))?.scrollIntoView(), 300);
    return () => window.clearTimeout(timer);
  }, [status]);

  if (status !== "authenticated" || !user) {
    return (
      <p className="m-0 inline-flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        {t.auth.checking}
      </p>
    );
  }

  const nav = [
    { id: "profile", label: t.account.profile },
    { id: "password", label: t.account.security },
    { id: "sessions", label: t.account.sessions },
    { id: "submissions", label: t.account.submissions },
    { id: "shares", label: t.account.shares },
  ];

  return (
    <div className="grid gap-10 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-14">
      <nav aria-label={t.account.title} className="lg:sticky lg:top-sticky lg:self-start">
        <ul className="m-0 flex list-none gap-1 overflow-x-auto p-0 lg:grid">
          {nav.map((item) => (
            <li key={item.id} className="shrink-0">
              <a href={`#${item.id}`} className="block rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-secondary hover:text-foreground">
                {item.label}
              </a>
            </li>
          ))}
          <li className="shrink-0">
            <Link href={localePath(locale, `/u/${user.handle}`)} className="block rounded-xl px-3 py-2 text-sm font-medium text-primary hover:bg-secondary">
              @{user.handle}
            </Link>
          </li>
        </ul>
      </nav>
      <div className="grid min-w-0 gap-14">
        <ProfilePanel key={`${user.handle}-${user.display_name}`} locale={locale} session={session} user={user} />
        <PasswordPanel locale={locale} session={session} user={user} />
        <SessionsPanel locale={locale} session={session} />
        <SubmissionsPanel locale={locale} session={session} />
        <SharesPanel locale={locale} session={session} />
      </div>
    </div>
  );
}
