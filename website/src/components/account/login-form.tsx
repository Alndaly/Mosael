"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";

const FIELD =
  "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none transition-[border-color,box-shadow] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/** 登录。成功后会拿到云端的 HttpOnly 会话 cookie,随后去账号页。 */
export function LoginForm({ locale, copy, registered = false }: { locale: Locale; copy: Messages["account"]; registered?: boolean }) {
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
    <form className="grid gap-4" onSubmit={submit} noValidate>
      {registered && (
        <output className="rounded-lg border border-border bg-secondary px-3 py-2 text-sm text-muted-foreground">
          {copy.registered}
        </output>
      )}
      <label className="grid gap-1.5 text-sm">
        {copy.email}
        <input
          className={FIELD}
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>
      <label className="grid gap-1.5 text-sm">
        {copy.password}
        <input
          className={FIELD}
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" className="w-full" disabled={busy}>
        {busy ? copy.signingIn : copy.signIn}
      </Button>
      <p className="text-sm text-muted-foreground">
        {copy.noAccount}{" "}
        <Link className="font-semibold text-primary underline-offset-4 hover:underline" href={`/${locale}/signup`}>
          {copy.signup}
        </Link>
      </p>
    </form>
  );
}
