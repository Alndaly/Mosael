"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  AccountField,
  CodeField,
  FormAlert,
  FormNotice,
  PasswordField,
  SendCodeButton,
  SubmitButton,
} from "@/components/account/form-controls";
import { OAuthButtons } from "@/components/account/oauth-buttons";
import { useResendCountdown } from "@/components/account/use-email-code";
import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";
import { oauthErrorCopyKey } from "@/lib/oauth";

type Phase = "form" | "success";

/**
 * 注册:**邮箱 → 发送验证码 → 6 位码 → 密码**。
 *
 * 验证码是注册的一部分,不是可选项:后端不验码就会拒。发送按钮有 60 秒本地倒计时
 * (服务端同样有冷却),发送中 / 已发送 / 失败都在按钮和提示区里说清楚。
 * 成功后**留在这页**给出成功态 —— 静默跳转会让用户不确定账号到底建没建成。
 */
export function SignupForm({
  locale,
  copy,
  oauthError = "",
}: {
  locale: Locale;
  copy: Messages["account"];
  /** Cloud 回调失败时带回的稳定错误码(见 lib/oauth.ts)。 */
  oauthError?: string;
}) {
  const [phase, setPhase] = useState<Phase>("form");
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState("");
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState("");
  const [notice, setNotice] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState<"" | "password" | "confirm">("");
  const [busy, setBusy] = useState(false);
  const countdown = useResendCountdown();
  const oauthMessage = oauthError ? copy[oauthErrorCopyKey(oauthError)] : "";

  const sendCode = async () => {
    setError("");
    setNotice("");
    setCodeError("");
    setEmailError("");
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setEmailError(copy.emailRequired);
      return;
    }
    setSendingCode(true);
    try {
      await cloudAccount.sendSignupCode(email.trim());
      setNotice(copy.codeSent);
      countdown.start();
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setSendingCode(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setFieldError("");
    setCodeError("");
    if (!/^\d{6}$/.test(code.trim())) {
      setCodeError(copy.codeRequired);
      return;
    }
    if (password.length < 8) {
      setFieldError("password");
      return;
    }
    if (password !== confirm) {
      setFieldError("confirm");
      return;
    }
    setBusy(true);
    try {
      await cloudAccount.signup(email.trim(), code.trim(), password);
      setPhase("success");
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };

  if (phase === "success") {
    return (
      <div className="grid gap-5 motion-safe:animate-[auth-rise_450ms_ease-out_both]">
        <div
          aria-live="polite"
          aria-atomic="true"
          className="rounded-3xl border border-primary/20 bg-brand-soft p-6 text-accent sm:p-7"
        >
          <CheckCircle2 className="size-6" aria-hidden />
          <h2 className="mt-4 font-display text-2xl font-semibold tracking-[-0.035em]">
            {copy.signupSuccessTitle}
          </h2>
          <p className="mt-2 text-sm leading-7 text-foreground/75">{copy.signupSuccessBody}</p>
          <p className="mt-3 break-all text-sm font-medium text-foreground">{email}</p>
        </div>
        <Button
          asChild
          className="h-13 w-full rounded-full bg-primary px-6 text-[15px] font-semibold text-primary-foreground hover:bg-accent focus-visible:ring-4 focus-visible:ring-primary/25"
        >
          <Link href={`/${locale}/login?registered=1`}>{copy.signupSuccessCta}</Link>
        </Button>
        <p className="m-0 text-center text-sm leading-6 text-muted-foreground">
          {copy.haveAccount}{" "}
          <Link
            className="font-semibold text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            href={`/${locale}/login`}
          >
            {copy.signIn}
          </Link>
        </p>
      </div>
    );
  }

  // 发送结果 / 表单错误都通过 id 关联到验证码字段,读屏在聚焦时能听到"为什么"。
  const codeDescription =
    [notice ? "signup-code-status" : "", error ? "signup-error" : ""].filter(Boolean).join(" ") || undefined;

  return (
    <div className="grid gap-5">
      <form className="grid gap-5" onSubmit={submit} noValidate>
        {oauthMessage && (
          <FormAlert id="oauth-error" title={copy.formErrorTitle}>
            {oauthMessage}
          </FormAlert>
        )}
        {error && (
          <FormAlert id="signup-error" title={copy.formErrorTitle}>
            {error}
          </FormAlert>
        )}
        {notice && <FormNotice id="signup-code-status">{notice}</FormNotice>}
        <AccountField
          id="signup-email"
          label={copy.email}
          type="email"
          inputMode="email"
          autoComplete="email"
          required
          value={email}
          error={emailError}
          describedBy={error ? "signup-error" : undefined}
          onChange={(event) => setEmail(event.target.value)}
        />
        <CodeField
          id="signup-code"
          label={copy.codeLabel}
          hint={copy.codeHint}
          value={code}
          error={codeError}
          describedBy={codeDescription}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
          trailing={
            <SendCodeButton
              label={copy.sendCode}
              sendingLabel={copy.sendingCode}
              resendLabel={copy.resendCode}
              sending={sendingCode}
              cooldown={countdown.remaining}
              disabled={busy}
              onClick={() => void sendCode()}
            />
          }
        />
        <PasswordField
          id="signup-password"
          label={copy.password}
          hint={copy.passwordHint}
          autoComplete="new-password"
          required
          minLength={8}
          value={password}
          error={fieldError === "password" ? copy.passwordTooShort : undefined}
          describedBy={error ? "signup-error" : undefined}
          showPassword={copy.showPassword}
          hidePassword={copy.hidePassword}
          onChange={(event) => setPassword(event.target.value)}
        />
        <PasswordField
          id="signup-confirm"
          label={copy.confirmPassword}
          autoComplete="new-password"
          required
          value={confirm}
          error={fieldError === "confirm" ? copy.passwordMismatch : undefined}
          describedBy={error ? "signup-error" : undefined}
          showPassword={copy.showPassword}
          hidePassword={copy.hidePassword}
          onChange={(event) => setConfirm(event.target.value)}
        />
        <div className="pt-1">
          <SubmitButton label={copy.signUp} busyLabel={copy.creating} busy={busy} />
        </div>
      </form>

      <OAuthButtons locale={locale} copy={copy} from="signup" />

      <p className="m-0 text-center text-sm leading-6 text-muted-foreground">
        {copy.haveAccount}{" "}
        <Link
          className="font-semibold text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          href={`/${locale}/login`}
        >
          {copy.signIn}
        </Link>
      </p>
    </div>
  );
}
