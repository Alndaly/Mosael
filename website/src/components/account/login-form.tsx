"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  AccountField,
  CodeField,
  FormAlert,
  PasswordField,
  SegmentedControl,
  SendCodeButton,
  SubmitButton,
} from "@/components/account/form-controls";
import { MfaChallenge } from "@/components/account/mfa-challenge";
import { OAuthButtons } from "@/components/account/oauth-buttons";
import { useResendCountdown } from "@/components/account/use-email-code";
import { toast } from "@/components/ui/use-toast";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount, isMfaChallenge } from "@/lib/cloud";
import { oauthErrorCopyKey } from "@/lib/oauth";
import { invalidateAfterAuth } from "@/lib/query-invalidation";

type Mode = "password" | "code" | "sms";

/**
 * 登录:**同一个页面里两个入口** —— 密码 / 验证码。
 *
 * 分段控件切换的是"怎么证明这个账号是你的",不是另一条鉴权路径:三种方式成功后都拿同一枚
 * HttpOnly 会话 cookie、都去账号页。密码登录的标识可以是邮箱或手机号;切到验证码时输入留着,
 * 不用重填。
 */
export function LoginForm({
  locale,
  copy,
  registered = false,
  oauthError = "",
}: {
  locale: Locale;
  copy: Messages["account"];
  registered?: boolean;
  /** Cloud 回调失败时带回的稳定错误码(见 lib/oauth.ts);空 = 不是第三方登录回来的。 */
  oauthError?: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState("");
  const [phone, setPhone] = useState("");
  const [phoneError, setPhoneError] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState("");
  const [error, setError] = useState("");
  const [mfaTicket, setMfaTicket] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const emailCountdown = useResendCountdown();
  const smsCountdown = useResendCountdown();
  const oauthMessage = oauthError ? copy[oauthErrorCopyKey(oauthError)] : "";

  const switchMode = (next: Mode) => {
    setMode(next);
    setError("");
    setCodeError("");
    setEmailError("");
    setPhoneError("");
  };

  // 刚注册完带着 `?registered=1` 回来时,「账号已创建」同样是一过性通知 —— 弹一次 toast,
  // 不占表单版面。ref 挡住 StrictMode 的重放,免得同一句话弹两遍。
  const registeredToasted = useRef(false);
  useEffect(() => {
    if (!registered || registeredToasted.current) return;
    registeredToasted.current = true;
    toast({ title: copy.registered });
  }, [registered, copy.registered]);

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
      await cloudAccount.sendLoginCode(email.trim());
      // 后端对"注册过 / 没注册"回同一句,界面也只说这一句。
      toast({ title: copy.loginCodeSent });
      emailCountdown.start();
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setSendingCode(false);
    }
  };

  const sendSmsCode = async () => {
    setError("");
    setCodeError("");
    setPhoneError("");
    if (!/^\+?[0-9][\d\s\-()]{5,}$/.test(phone.trim())) {
      setPhoneError(copy.phoneRequired);
      return;
    }
    setSendingCode(true);
    try {
      await cloudAccount.sendLoginSmsCode(phone.trim());
      toast({ title: copy.smsCodeSent });
      smsCountdown.start();
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setSendingCode(false);
    }
  };

  const finishLogin = async (result: Awaited<ReturnType<typeof cloudAccount.login>>) => {
    if (isMfaChallenge(result)) {
      setMfaTicket(result.ticket);
      return;
    }
    // 登录态变了:站头那份 viewer 缓存必须失效,否则回到站内还显示「登录」。
    await invalidateAfterAuth(queryClient);
    router.push(`/${locale}/account`);
  };

  const submitPassword = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const identifier = email.trim();
      const result = identifier.includes("@")
        ? await cloudAccount.login(identifier, password)
        : await cloudAccount.loginWithPhone(identifier, password);
      await finishLogin(result);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setCodeError("");
    if (!/^\d{6}$/.test(code.trim())) {
      setCodeError(copy.codeRequired);
      return;
    }
    setBusy(true);
    try {
      const result = await cloudAccount.loginWithCode(email.trim(), code.trim());
      await finishLogin(result);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };

  const submitSms = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setCodeError("");
    if (!/^\d{6}$/.test(code.trim())) {
      setCodeError(copy.codeRequired);
      return;
    }
    setBusy(true);
    try {
      const result = await cloudAccount.loginWithSms(phone.trim(), code.trim());
      await finishLogin(result);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy(false);
    }
  };

  // 表单错误通过 id 关联到验证码字段。
  const codeDescription = error ? "login-error" : undefined;

  return (
    <div className="grid gap-5">
      {oauthMessage && (
        <FormAlert id="oauth-error" title={copy.formErrorTitle}>
          {oauthMessage}
        </FormAlert>
      )}
      <SegmentedControl
        id="login-mode"
        label={copy.loginModeLabel}
        value={mode}
        options={[
          { value: "password", label: copy.loginModePassword },
          { value: "code", label: copy.loginModeCode },
          { value: "sms", label: copy.loginModeSms },
        ]}
        onChange={switchMode}
        disabled={busy}
      />

      {mfaTicket ? (
        <MfaChallenge
          locale={locale}
          copy={copy}
          ticket={mfaTicket}
          onCancel={() => {
            setMfaTicket("");
            setCode("");
            setPassword("");
            setError("");
          }}
        />
      ) : mode === "password" ? (
        <form className="grid gap-5" onSubmit={submitPassword} noValidate>
          {error && (
            <FormAlert id="login-error" title={copy.formErrorTitle}>
              {error}
            </FormAlert>
          )}
          <AccountField
            id="login-email"
            label={copy.identifier}
            type="text"
            inputMode="text"
            autoComplete="username"
            required
            value={email}
            error={emailError}
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
        </form>
      ) : mode === "code" ? (
        <form className="grid gap-5" onSubmit={submitCode} noValidate>
          {error && (
            <FormAlert id="login-error" title={copy.formErrorTitle}>
              {error}
            </FormAlert>
          )}
          <AccountField
            id="login-code-email"
            label={copy.email}
            type="email"
            inputMode="email"
            autoComplete="email"
            required
            value={email}
            error={emailError}
            describedBy={error ? "login-error" : undefined}
            onChange={(event) => setEmail(event.target.value)}
          />
          <CodeField
            id="login-code"
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
                cooldown={emailCountdown.remaining}
                disabled={busy}
                onClick={() => void sendCode()}
              />
            }
          />
          <div className="pt-1">
            <SubmitButton label={copy.loginWithCode} busyLabel={copy.verifying} busy={busy} />
          </div>
        </form>
      ) : (
        <form className="grid gap-5" onSubmit={submitSms} noValidate>
          {error && (
            <FormAlert id="login-error" title={copy.formErrorTitle}>
              {error}
            </FormAlert>
          )}
          <AccountField
            id="login-phone"
            label={copy.phone}
            hint={copy.phoneHint}
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            required
            value={phone}
            error={phoneError}
            describedBy={error ? "login-error" : undefined}
            onChange={(event) => setPhone(event.target.value)}
          />
          <CodeField
            id="login-sms-code"
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
                cooldown={smsCountdown.remaining}
                disabled={busy}
                onClick={() => void sendSmsCode()}
              />
            }
          />
          <div className="pt-1">
            <SubmitButton label={copy.loginWithSms} busyLabel={copy.verifying} busy={busy} />
          </div>
        </form>
      )}

      <OAuthButtons locale={locale} copy={copy} from="login" />

      <p className="m-0 text-center text-sm leading-6 text-muted-foreground">
        {copy.noAccount}{" "}
        <Link
          className="font-semibold text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          href={`/${locale}/signup`}
        >
          {copy.signup}
        </Link>
      </p>
    </div>
  );
}
