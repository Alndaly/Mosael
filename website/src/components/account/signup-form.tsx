"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import {
  AccountField,
  CodeField,
  FormAlert,
  PasswordField,
  SendCodeButton,
  SubmitButton,
} from "@/components/account/form-controls";
import { OAuthButtons } from "@/components/account/oauth-buttons";
import { useResendCountdown } from "@/components/account/use-email-code";
import { toast } from "@/components/ui/use-toast";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount } from "@/lib/cloud";
import { oauthErrorCopyKey } from "@/lib/oauth";

/**
 * 注册:**邮箱 → 发送验证码 → 6 位码 → 密码**。
 *
 * 验证码是注册的一部分,不是可选项:后端不验码就会拒。发送按钮有 60 秒本地倒计时
 * (服务端同样有冷却),发送中 / 失败在按钮和提示区里说清楚;**「验证码已发送」是成功通知,
 * 走 toast 弹一下就走**,不占表单版面(错误仍内联,见 `FormAlert`)。
 *
 * 注册成功云端直接建会话,所以这里直接 `router.replace` 进控制台(不留注册页在历史里)。
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
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState("");
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState<"" | "password" | "confirm">("");
  const [busy, setBusy] = useState(false);
  const countdown = useResendCountdown();
  const oauthMessage = oauthError ? copy[oauthErrorCopyKey(oauthError)] : "";
  const router = useRouter();

  const sendCode = async () => {
    setError("");
    setCodeError("");
    setEmailError("");
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setEmailError(copy.emailRequired);
      return;
    }
    setSendingCode(true);
    try {
      await cloudAccount.sendSignupCode(email.trim());
      // 「发送成功」是一过性通知:弹一条 toast,表单里不留下占位的一条提示。
      toast({ title: copy.codeSent });
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
      // 云端注册**直接建会话**(注册即登录,见 cloud/api/auth.py 的 signup),所以这里不需要
      // 「再登录一次」那一步 —— 直接进自己的控制台。replace 不留注册页在历史里:后退回到一个
      // 已经完成的表单只会让人误点第二次。
      router.replace(`/${locale}/dashboard`);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };


  // 表单错误通过 id 关联到验证码字段,读屏在聚焦时能听到"为什么"。
  const codeDescription = error ? "signup-error" : undefined;

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
