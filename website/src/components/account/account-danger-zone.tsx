"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ShieldAlert, Trash2 } from "lucide-react";
import { useState } from "react";

import { FormAlert } from "@/components/account/form-controls";
import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import { getMessages, type Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";
import { invalidateAfterSignOut } from "@/lib/query-invalidation";

/**
 * 危险区:删除 MosaelCloud 账号。
 *
 * **从 `(auth)/account` 那一块原样搬来的**(维护者:「为何系统账号只有这么一个页面 应该和普通
 * 账号一样支持所有操作」):同样的警告配色(`border-destructive/25` + `bg-destructive/[0.04]`)、
 * 同一个 `ShieldAlert`、同一句「删除后不能恢复」、同样两次点击才真的删。账号页收成跳转之后,
 * 这块不再有自己的页面,而是落在控制台「个人信息」的最底下。
 *
 * 删号之后**不只是离开这一页**:viewer(站头会立刻变成「登录」)、未读角标、通知、我的分享
 * 都还是刚删掉那个账号的,所以复用 `invalidateAfterSignOut` 那一组失效,再回首页。
 *
 * 账号类型不参与判断:官方号也是它自己的账号,没有「官方不能删」的闸。
 */
export function AccountDangerZone({ locale, copy }: { locale: Locale; copy: Messages["dashboard"] }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);

  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await cloudAccount.deleteAccount();
      // 缓存清单见 `lib/query-invalidation.ts`:viewer / unread / notifications / sharesByMe。
      await invalidateAfterSignOut(queryClient);
      router.push(`/${locale}`);
    } catch (failure) {
      setError(
        failure instanceof CloudApiError ? failure.text(locale) : getMessages(locale).account.actionFailed,
      );
      setBusy(false);
    }
  };

  return (
    <>
      {error && (
        <FormAlert id="dashboard-delete-error" title={copy.tabProfile}>
          {error}
        </FormAlert>
      )}

      <section
        aria-labelledby="dashboard-danger"
        className="rounded-3xl border border-destructive/25 bg-destructive/[0.04] p-6 sm:p-7"
      >
        <div className="flex items-start gap-3">
          <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
            <ShieldAlert className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2
              id="dashboard-danger"
              className="font-display text-xl font-semibold tracking-[-0.03em] text-destructive"
            >
              {copy.dangerZone}
            </h2>
            <p className="mt-1 mb-0 text-sm leading-7 text-muted-foreground">{copy.deleteConfirm}</p>
          </div>
        </div>
        {confirming ? (
          <div className="mt-5 flex flex-col gap-2 sm:flex-row">
            <Button
              variant="destructive"
              disabled={busy}
              aria-busy={busy}
              onClick={() => void remove()}
              className="min-h-11 rounded-full px-5 text-sm font-semibold"
            >
              <Trash2 className="size-4" aria-hidden />
              {busy ? copy.deleting : copy.confirmDelete}
            </Button>
            <Button
              variant="ghost"
              onClick={() => setConfirming(false)}
              className="min-h-11 rounded-full px-5 text-sm font-semibold"
            >
              {copy.cancel}
            </Button>
          </div>
        ) : (
          <Button
            variant="destructive"
            onClick={() => setConfirming(true)}
            className="mt-5 min-h-11 rounded-full px-5 text-sm font-semibold"
          >
            <Trash2 className="size-4" aria-hidden />
            {copy.deleteAccount}
          </Button>
        )}
      </section>
    </>
  );
}
