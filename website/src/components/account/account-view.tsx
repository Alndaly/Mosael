"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, LockKeyhole, LogOut, ShieldAlert, Trash2 } from "lucide-react";

import { FormAlert } from "@/components/account/form-controls";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";
import { invalidateAfterSignOut } from "@/lib/query-invalidation";
import { useViewer } from "@/lib/queries";

type Phase = "loading" | "anonymous" | "signed" | "error";

/**
 * 账号页:**只知道云端身份**。
 *
 * 它不请求本地后端、不显示工作区 / 素材 / 本地用户名 —— 那属于本机 Mosael,这一页是 MosaelCloud 的。
 *
 * 设备绑定机制已经拆掉;这一页只剩身份、退出与删号,以及登录回跳(`ResumeLoginReturn`)。
 *
 * 四态都当成正式界面来画:加载是骨架、未登录有入口、失败能重试、已登录是身份 + 危险操作。
 * 删号永远藏在最后一块,并且要点两次。
 */
export function AccountView({
  locale,
  copy,
  oauthOutcome = "",
}: {
  locale: Locale;
  copy: Messages["account"];
  /** 刚通过 GitHub / Google 回到这一页时,Cloud 用 `?oauth=created|existing` 说清结果。 */
  oauthOutcome?: "" | "created" | "existing";
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // 身份只有一份来源:和站头同一个 viewer 查询缓存(键见 lib/queryKeys.ts)。
  // 401 在 fetchViewer 里已经是 null(未登录),不会把这一页推进错误态。
  const viewerQuery = useViewer();
  const user = viewerQuery.data ?? null;
  const phase: Phase = user
    ? "signed"
    : viewerQuery.isPending || (viewerQuery.isFetching && !viewerQuery.isError)
      ? "loading"
      : viewerQuery.isError
        ? "error"
        : "anonymous";
  const loadError = viewerQuery.isError
    ? viewerQuery.error instanceof CloudApiError
      ? viewerQuery.error.text(locale)
      : copy.loadFailed
    : "";

  // 从 GitHub / Google 回来时,「已创建 / 已绑定」是一过性成功通知 —— 等身份真的读出来
  // (signed)再弹一次 toast;ref 保证 StrictMode 的重放不会弹第二遍。
  const oauthToasted = useRef(false);
  useEffect(() => {
    if (phase !== "signed" || !oauthOutcome || oauthToasted.current) return;
    oauthToasted.current = true;
    toast({ title: oauthOutcome === "created" ? copy.oauthCreated : copy.oauthExisting });
  }, [phase, oauthOutcome, copy.oauthCreated, copy.oauthExisting]);

  const signOut = async () => {
    setBusy("logout");
    try {
      await cloudAccount.logout();
    } catch {
      // 本地无状态可清:cookie 由服务端撤销;即使请求失败,离开这一页也不显示旧账号。
    }
    // 退出后站头 / 角标 / 通知都必须换掉,否则还挂着上一个账号。
    await invalidateAfterSignOut(queryClient);
    router.push(`/${locale}/login`);
  };

  const remove = async () => {
    setBusy("delete");
    setError("");
    try {
      await cloudAccount.deleteAccount();
      await invalidateAfterSignOut(queryClient);
      router.push(`/${locale}`);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
      setBusy("");
    }
  };

  if (phase === "loading") {
    return (
      <div aria-busy="true" aria-live="polite" className="grid gap-4">
        <span className="sr-only">{copy.loading}</span>
        <div className="rounded-3xl border border-border bg-card p-6">
          <div className="h-3 w-24 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
          <div className="mt-5 h-7 w-3/5 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
          <div className="mt-3 h-3 w-2/5 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
        </div>
        <div className="rounded-3xl border border-border bg-card p-6">
          <div className="h-3 w-20 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
          <div className="mt-5 h-14 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" />
          <div className="mt-2.5 h-14 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" />
        </div>
      </div>
    );
  }

  if (phase === "anonymous") {
    return (
      <div className="rounded-3xl border border-border bg-card p-6 motion-safe:animate-[auth-rise_450ms_ease-out_both] sm:p-8">
        <span className="inline-flex size-11 items-center justify-center rounded-2xl bg-brand-soft text-accent">
          <LockKeyhole className="size-5" aria-hidden />
        </span>
        <h2 className="mt-5 font-display text-2xl font-semibold tracking-[-0.035em]">{copy.loginRequired}</h2>
        <p className="mt-3 max-w-[38ch] text-sm leading-7 text-muted-foreground">{copy.accountLede}</p>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Button asChild className="min-h-11 rounded-full px-5 text-sm font-semibold">
            <Link href={`/${locale}/login`}>{copy.signIn}</Link>
          </Button>
          <Button asChild variant="outline" className="min-h-11 rounded-full px-5 text-sm font-semibold">
            <Link href={`/${locale}/signup`}>{copy.signup}</Link>
          </Button>
        </div>
      </div>
    );
  }

  if (phase === "error" || !user) {
    return (
      <div role="alert" className="rounded-3xl border border-destructive/25 bg-card p-6 sm:p-8">
        <span className="inline-flex size-11 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
          <AlertTriangle className="size-5" aria-hidden />
        </span>
        <h2 className="mt-5 font-display text-2xl font-semibold tracking-[-0.035em]">{copy.formErrorTitle}</h2>
        <p className="mt-3 text-sm leading-7 text-muted-foreground">{loadError || copy.loadFailed}</p>
        <Button
          variant="outline"
          className="mt-6 min-h-11 rounded-full px-5 text-sm font-semibold"
          onClick={() => {
            setError("");
            // 重试就是让同一个 viewer 查询再跑一次;骨架由 isFetching 决定。
            void viewerQuery.refetch();
          }}
        >
          {copy.retry}
        </Button>
      </div>
    );
  }

  const initial = user.email.slice(0, 1).toUpperCase();

  return (
    <div className="grid gap-4 motion-safe:animate-[auth-rise_450ms_ease-out_both]">
      {error && (
        <FormAlert id="account-error" title={copy.formErrorTitle}>
          {error}
        </FormAlert>
      )}

      <section aria-labelledby="account-identity" className="rounded-3xl border border-border bg-card p-6 sm:p-7">
        <div className="flex flex-wrap items-start gap-4">
          <span
            aria-hidden
            className="inline-flex size-12 shrink-0 items-center justify-center rounded-2xl bg-brand-soft font-display text-xl font-semibold text-primary"
          >
            {initial}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="m-0 text-[13px] font-medium text-muted-foreground">{copy.accountIdentity}</p>
              <span className="inline-flex items-center gap-1 rounded-full bg-brand-soft px-2.5 py-1 text-[11px] font-medium text-accent">
                <CheckCircle2 className="size-3.5" aria-hidden />
                {copy.signedInLabel}
              </span>
              {user.email_verified_at && (
                <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2.5 py-1 text-[11px] font-medium text-foreground">
                  <CheckCircle2 className="size-3.5" aria-hidden />
                  {copy.emailVerified}
                </span>
              )}
            </div>
            <h2
              id="account-identity"
              className="mt-2 font-display text-lg font-semibold tracking-[-0.03em] [overflow-wrap:anywhere] sm:text-xl"
            >
              {user.email}
            </h2>
          </div>
          <Button
            variant="outline"
            disabled={busy === "logout"}
            aria-busy={busy === "logout"}
            onClick={() => void signOut()}
            className="min-h-10 w-full rounded-full px-4 text-[13px] font-semibold sm:ml-auto sm:w-auto"
          >
            <LogOut className="size-3.5" aria-hidden />
            {busy === "logout" ? copy.signingOut : copy.signOut}
          </Button>
        </div>
      </section>

      <section
        aria-labelledby="account-danger"
        className="rounded-3xl border border-destructive/25 bg-destructive/[0.04] p-6 sm:p-7"
      >
        <div className="flex items-start gap-3">
          <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
            <ShieldAlert className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2
              id="account-danger"
              className="font-display text-xl font-semibold tracking-[-0.03em] text-destructive"
            >
              {copy.dangerZone}
            </h2>
            <p className="mt-1 text-sm leading-7 text-muted-foreground">{copy.deleteConfirm}</p>
          </div>
        </div>
        {confirmingDelete ? (
          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <Button
              variant="destructive"
              disabled={busy === "delete"}
              aria-busy={busy === "delete"}
              onClick={() => void remove()}
              className="min-h-11 rounded-full px-5 text-sm font-semibold"
            >
              <Trash2 className="size-4" aria-hidden />
              {busy === "delete" ? copy.deleting : copy.deleteYes}
            </Button>
            <Button
              variant="ghost"
              onClick={() => setConfirmingDelete(false)}
              className="min-h-11 rounded-full px-5 text-sm font-semibold"
            >
              {copy.cancel}
            </Button>
          </div>
        ) : (
          <Button
            variant="destructive"
            onClick={() => setConfirmingDelete(true)}
            className="mt-5 min-h-11 rounded-full px-5 text-sm font-semibold"
          >
            <Trash2 className="size-4" aria-hidden />
            {copy.deleteAccount}
          </Button>
        )}
      </section>
    </div>
  );
}
