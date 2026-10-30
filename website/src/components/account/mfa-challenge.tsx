"use client";

import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { AccountField, FormAlert, SubmitButton } from "@/components/account/form-controls";
import { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";
import { invalidateAfterAuth } from "@/lib/query-invalidation";

/** 登录第二步:主认证通过后，用 TOTP / 恢复码换会话。 */
export function MfaChallenge({
  locale,
  copy,
  ticket,
  onCancel,
}: {
  locale: Locale;
  copy: Messages["account"];
  ticket: string;
  onCancel?: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError("");
    if (!code.trim()) {
      setError(copy.mfaCodeRequired);
      return;
    }
    setBusy(true);
    try {
      await cloudAccount.verifyMfa(ticket, code.trim());
      await invalidateAfterAuth(queryClient);
      router.push(`/${locale}/account`);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="grid gap-5" onSubmit={submit} noValidate>
      <div className="grid gap-1">
        <h2 className="m-0 font-display text-xl font-semibold tracking-[-0.03em]">{copy.mfaTitle}</h2>
        <p className="m-0 text-[13px] leading-6 text-muted-foreground">{copy.mfaLede}</p>
      </div>
      {error && (
        <FormAlert id="mfa-error" title={copy.formErrorTitle}>
          {error}
        </FormAlert>
      )}
      <AccountField
        id="mfa-code"
        label={copy.mfaCode}
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        value={code}
        onChange={(event) => setCode(event.target.value)}
        describedBy={error ? "mfa-error" : undefined}
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        {onCancel ? (
          <button
            type="button"
            className="text-[13px] text-muted-foreground underline-offset-4 hover:underline"
            onClick={onCancel}
          >
            {copy.mfaBack}
          </button>
        ) : (
          <span />
        )}
        <SubmitButton label={copy.mfaVerify} busyLabel={copy.verifying} busy={busy} />
      </div>
    </form>
  );
}
