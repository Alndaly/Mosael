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

/** 注册。成功后去登录页 —— 注册本身不建立会话(云端 signup 不自动登录)。 */
export function SignupForm({ locale, copy }: { locale: Locale; copy: Messages["account"] }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (password.length < 8) {
      setError(copy.passwordTooShort);
      return;
    }
    if (password !== confirm) {
      setError(copy.passwordMismatch);
      return;
    }
    setBusy(true);
    try {
      await cloudAccount.signup(email, password);
      router.push(`/${locale}/login?registered=1`);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="grid gap-4" onSubmit={submit} noValidate>
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
          autoComplete="new-password"
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      <label className="grid gap-1.5 text-sm">
        {copy.confirmPassword}
        <input
          className={FIELD}
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
      </label>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <Button type="submit" className="w-full" disabled={busy}>
        {busy ? copy.creating : copy.signUp}
      </Button>
      <p className="text-sm text-muted-foreground">
        {copy.haveAccount}{" "}
        <Link className="font-semibold text-primary underline-offset-4 hover:underline" href={`/${locale}/login`}>
          {copy.signIn}
        </Link>
      </p>
    </form>
  );
}
