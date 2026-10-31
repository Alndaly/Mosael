"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { AccountField, FormAlert, PasswordField } from "@/components/account/form-controls";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";
import { invalidateAfterPasswordChange } from "@/lib/query-invalidation";

/**
 * 官网控制台的登录密码块。
 *
 * 验证码登录新建的账号没有密码(`has_password === false`):这时只显示新密码两栏。
 * 已有密码时必须先验当前密码 —— 这是云端的约束,前端不另造一套。
 */
export function DashboardPassword({
  locale,
  copy,
  hasPassword,
}: {
  locale: Locale;
  copy: Messages["dashboard"];
  hasPassword: boolean;
}) {
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError("");
    setSaved(false);
    if (next.length < 8) {
      setError(copy.passwordTooShort);
      return;
    }
    if (next !== confirm) {
      setError(copy.passwordMismatch);
      return;
    }
    setBusy(true);
    try {
      await cloudAccount.changePassword(hasPassword ? current : "", next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setSaved(true);
      await invalidateAfterPasswordChange(queryClient);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.passwordFailed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="bg-card/60 ring-border">
      <CardHeader>
        <CardTitle id="dashboard-password">{copy.passwordTitle}</CardTitle>
        <CardDescription>{copy.passwordLede}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {error && (
          <FormAlert id="dashboard-password-error" title={copy.passwordTitle}>
            {error}
          </FormAlert>
        )}

        <form className="grid gap-4" onSubmit={save} noValidate>
          {hasPassword && (
            <AccountField
              id="dashboard-current-password"
              label={copy.passwordCurrent}
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              className="h-9 rounded-md text-sm"
            />
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <PasswordField
              id="dashboard-new-password"
              label={copy.passwordNew}
              autoComplete="new-password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
              showPassword={copy.passwordShow}
              hidePassword={copy.passwordHide}
              className="h-9 rounded-md text-sm"
            />
            <PasswordField
              id="dashboard-confirm-password"
              label={copy.passwordConfirm}
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              showPassword={copy.passwordShow}
              hidePassword={copy.passwordHide}
              className="h-9 rounded-md text-sm"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" size="sm" disabled={busy} aria-busy={busy}>
              {busy ? copy.saving : hasPassword ? copy.passwordChange : copy.passwordSet}
            </Button>
            {saved && <p className="m-0 text-[13px] leading-5 text-muted-foreground">{copy.passwordSaved}</p>}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
