"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, LockKeyhole, LogOut, ShieldAlert, Trash2 } from "lucide-react";

import { FormAlert, FormNotice } from "@/components/account/form-controls";
import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount, type CloudUser } from "@/lib/cloud";

type Phase = "loading" | "anonymous" | "signed" | "error";

/**
 * 账号页:**只知道云端身份**。
 *
 * 它不请求本地后端、不显示工作区 / 素材 / 本地用户名 —— 那属于本机 Mosael,这一页是 MosaelCloud 的。
 *
 * **设备的那两块(已绑定 / 确认这台设备)已经搬到「我的」控制台**
 * (`components/account/dashboard-devices.tsx`);这一页只剩身份、退出与删号,以及登录 /
 * 桌面绑定回跳(`ResumeLoginReturn`)。桌面绑定链接仍然是 `/account?user_code=…` —— 见
 * `app/[locale]/(auth)/account/page.tsx`,它把带确认码的访问转给控制台的设备分区。
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
  const [phase, setPhase] = useState<Phase>("loading");
  const [user, setUser] = useState<CloudUser | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    cloudAccount
      .me()
      .then((me) => {
        if (!alive) return;
        setUser(me.user);
        setPhase("signed");
      })
      .catch((failure: unknown) => {
        if (!alive) return;
        if (failure instanceof CloudApiError && failure.status === 401) {
          setPhase("anonymous");
          return;
        }
        setError(failure instanceof CloudApiError ? failure.text(locale) : copy.loadFailed);
        setPhase("error");
      });
    return () => {
      alive = false;
    };
  }, [locale, copy.loadFailed, reloadKey]);

  const signOut = async () => {
    setBusy("logout");
    try {
      await cloudAccount.logout();
    } catch {
      // 本地无状态可清:cookie 由服务端撤销;即使请求失败,离开这一页也不显示旧账号。
    }
    router.push(`/${locale}/login`);
  };

  const remove = async () => {
    setBusy("delete");
    setError("");
    try {
      await cloudAccount.deleteAccount();
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
        <p className="mt-3 text-sm leading-7 text-muted-foreground">{error || copy.loadFailed}</p>
        <Button
          variant="outline"
          className="mt-6 min-h-11 rounded-full px-5 text-sm font-semibold"
          onClick={() => {
            setError("");
            setPhase("loading");
            setReloadKey((key) => key + 1);
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
      {oauthOutcome && (
        <FormNotice id="oauth-result">
          {oauthOutcome === "created" ? copy.oauthCreated : copy.oauthExisting}
        </FormNotice>
      )}
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
