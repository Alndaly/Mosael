"use client";

/**
 * 详情页上要登录的几个动作:点赞、举报、作者本人才看得到的「发布新版本」。
 *
 * 页面本身在服务端以匿名身份渲染(令牌只在浏览器内存里),「我赞过没有」「我是不是作者」
 * 只能在浏览器里补上:登录着的话,带令牌再读一次详情拿 `liked`。
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Flag, Heart, Upload } from "lucide-react";
import * as React from "react";

import { useSession } from "@/components/community/session-provider";
import { BUTTON, Field, Modal, Notice, SubmitButton, TEXTAREA, errorText } from "@/components/community/ui";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS, REQUESTED } from "@/lib/community/endpoints";
import { formatCount } from "@/lib/community/format";
import type { ItemKind } from "@/lib/community/types";
import { cn } from "@/lib/utils";

function useLoginRedirect(locale: Locale) {
  const router = useRouter();
  const pathname = usePathname();
  return React.useCallback(() => router.push(`${localePath(locale, "/login")}?next=${encodeURIComponent(pathname)}`), [router, pathname, locale]);
}

export function LikeButton({ locale, kind, slug, likes }: { locale: Locale; kind: ItemKind; slug: string; likes: number }) {
  const t = getMessages(locale).community;
  const { status, communityFetch } = useSession();
  const toLogin = useLoginRedirect(locale);
  const [liked, setLiked] = React.useState(false);
  const [count, setCount] = React.useState(likes);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (status !== "authenticated") return;
    let cancelled = false;
    communityFetch<{ liked?: boolean | null; likes?: number }>(ENDPOINTS.items.detail(kind, slug))
      .then((detail) => {
        if (cancelled) return;
        setLiked(Boolean(detail.liked));
        if (typeof detail.likes === "number") setCount(detail.likes);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [status, communityFetch, kind, slug]);

  const toggle = async () => {
    if (status !== "authenticated") return toLogin();
    const next = !liked;
    setBusy(true);
    setLiked(next);
    setCount((value) => value + (next ? 1 : -1));
    try {
      const result = await communityFetch<{ likes?: number } | undefined>(ENDPOINTS.items.like(kind, slug), { method: next ? "POST" : "DELETE" });
      if (result && typeof result.likes === "number") setCount(result.likes);
    } catch {
      setLiked(!next);
      setCount((value) => value + (next ? -1 : 1));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy}
      aria-pressed={liked}
      title={status === "authenticated" ? undefined : t.likeNeedsLogin}
      className={cn(BUTTON.secondary, liked && "border-primary/40 text-primary")}
    >
      <Heart className={cn("size-4", liked && "fill-current")} aria-hidden />
      {liked ? t.liked : t.like}
      <span className="font-mono text-xs tabular-nums opacity-75">{formatCount(Math.max(0, count), locale)}</span>
    </button>
  );
}

/** 和社区服务的 `REPORT_REASONS` 同一组。`likeness`(冒用肖像)只在资产上列出:别的条目里没有谁的脸。 */
const REASONS = ["spam", "malware", "copyright", "inappropriate", "broken", "likeness", "other"] as const;
const reasonsFor = (kind: ItemKind | "share") => REASONS.filter((one) => one !== "likeness" || kind === "asset");

export function ReportButton({ locale, kind, slug }: { locale: Locale; kind: ItemKind | "share"; slug: string }) {
  const t = getMessages(locale).community;
  const { status, communityFetch } = useSession();
  const toLogin = useLoginRedirect(locale);
  const [open, setOpen] = React.useState(false);
  const [reason, setReason] = React.useState<(typeof REASONS)[number]>("spam");
  const [detail, setDetail] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await communityFetch(REQUESTED.report(kind, slug), { method: "POST", json: { reason, detail: detail.trim() || undefined } });
      setDone(true);
    } catch (caught) {
      setError(errorText(caught, t.genericError, t.networkError));
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => (status === "authenticated" ? setOpen(true) : toLogin())}
        title={status === "authenticated" ? undefined : t.reportNeedsLogin}
        className="inline-flex items-center gap-1.5 px-1 text-xs font-medium text-muted-foreground hover:text-destructive"
      >
        <Flag className="size-3.5" aria-hidden />
        {t.report}
      </button>
      <Modal
        open={open}
        onOpenChange={(value) => {
          setOpen(value);
          if (!value) {
            setDone(false);
            setError(null);
          }
        }}
        title={t.reportTitle}
        closeLabel={t.close}
      >
        {done ? (
          <Notice tone="success">{t.reportDone}</Notice>
        ) : (
          <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
            <fieldset className="m-0 grid gap-2 border-0 p-0">
              <legend className="mb-2 text-sm font-medium">{t.reportReason}</legend>
              {reasonsFor(kind).map((one) => (
                <label key={one} className="flex items-center gap-2.5 text-sm">
                  <input type="radio" name="reason" value={one} checked={reason === one} onChange={() => setReason(one)} className="accent-[var(--primary)]" />
                  {t.reportReasons[one]}
                </label>
              ))}
            </fieldset>
            <Field label={t.reportDetail} htmlFor="report-detail">
              <textarea id="report-detail" maxLength={1000} value={detail} onChange={(event) => setDetail(event.target.value)} className={TEXTAREA} />
            </Field>
            {error && <Notice tone="error">{error}</Notice>}
            <div className="flex justify-end gap-2">
              <button type="button" className={BUTTON.ghost} onClick={() => setOpen(false)}>
                {t.cancel}
              </button>
              <SubmitButton pending={pending} variant="danger">
                {t.reportSubmit}
              </SubmitButton>
            </div>
          </form>
        )}
      </Modal>
    </>
  );
}

/** 作者本人看到「发布新版本」。 */
export function NewVersionLink({ locale, kind, slug, authorHandle }: { locale: Locale; kind: ItemKind; slug: string; authorHandle: string }) {
  const { user } = useSession();
  if (!user || user.handle !== authorHandle) return null;
  return (
    <Link href={localePath(locale, `/${kind === "workflow" ? "workflows" : "plugins"}/${slug}/new-version`)} className={BUTTON.secondary}>
      <Upload className="size-4" aria-hidden />
      {getMessages(locale).community.newVersion}
    </Link>
  );
}
