"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AccountField, FormAlert, FormNotice, PasswordField, SubmitButton } from "@/components/account/form-controls";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";

/** 登录。成功后会拿到云端的 HttpOnly 会话 cookie,随后去账号页。 */
export function LoginForm({
  locale,
  copy,
  registered = false,
}: {
  locale: Locale;
  copy: Messages["account"];
  registered?: boolean;
}) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await cloudAccount.login(email, password);
      router.push(`/${locale}/account`);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="grid gap-5" onSubmit={submit} noValidate>
      {registered && <FormNotice>{copy.registered}</FormNotice>}
      {error && (
        <FormAlert id="login-error" title={copy.formErrorTitle}>
          {error}
        </FormAlert>
      )}
      <AccountField
        id="login-email"
        label={copy.email}
        type="email"
        inputMode="email"
        autoComplete="email"
        required
        value={email}
        describedBy={error ? "login-error" : undefined}
        onChange={(event) => setEmail(event.target.value)}
      />
      <PasswordField
        id="login-password"
        label={copy.password}
        autoComplete="current-password"
        required
        value={password}
        describedBy={error ? "login-error" : undefined}
        showPassword={copy.showPassword}
        hidePassword={copy.hidePassword}
        onChange={(event) => setPassword(event.target.value)}
      />
      <div className="pt-1">
        <SubmitButton label={copy.signIn} busyLabel={copy.signingIn} busy={busy} />
      </div>
      <p className="m-0 text-center text-sm leading-6 text-muted-foreground">
        {copy.noAccount}{" "}
        <Link
          className="font-semibold text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          href={`/${locale}/signup`}
        >
          {copy.signup}
        </Link>
      </p>
    </form>
  );
}
