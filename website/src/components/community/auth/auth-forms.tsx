"use client";

/**
 * 登录(手机验证码 / 账号密码两个标签)、注册、找回密码。
 *
 * 路径与请求体逐条照 ADR 0026「认证」:短信登录与注册带 `agree_terms_version`;密码登录、
 * 找回密码的请求体里 ADR 没有这一项,就不发 —— 勾选框照样要勾(ADR:三个页上都有勾选)。
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { AuthCard, Consent, PhoneCodeFields, useAuthConfig } from "@/components/community/auth/fields";
import { useSession } from "@/components/community/session-provider";
import { BUTTON, Field, INPUT, Notice, Segmented, Spinner, SubmitButton, errorText } from "@/components/community/ui";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { safeNext, toE164, validCode, validHandle, validPassword } from "@/lib/community/input";

/** 已经登录着就不再给表单:说一句是谁,给个「继续」。 */
function AlreadySignedIn({ locale, next }: { locale: Locale; next: string }) {
  const t = getMessages(locale).auth;
  const { user } = useSession();
  return (
    <AuthCard>
      <p className="m-0 flex flex-wrap gap-x-1.5 text-sm text-muted-foreground">
        {t.signedInAs}
        <strong className="text-foreground">@{user?.handle}</strong>
      </p>
      <Link href={next} className={BUTTON.primary}>
        {t.goAccount}
      </Link>
    </AuthCard>
  );
}

function Checking({ locale }: { locale: Locale }) {
  return (
    <AuthCard>
      <p className="m-0 inline-flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        {getMessages(locale).auth.checking}
      </p>
    </AuthCard>
  );
}

export function LoginForm({ locale, next: rawNext }: { locale: Locale; next: string | null }) {
  const t = getMessages(locale);
  const router = useRouter();
  const { client, status } = useSession();
  const { termsVersion } = useAuthConfig();
  const next = safeNext(rawNext, locale);
  const [mode, setMode] = React.useState<"sms" | "password">("sms");
  const [phone, setPhone] = React.useState("");
  const [code, setCode] = React.useState("");
  const [login, setLogin] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [agreed, setAgreed] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  React.useEffect(() => {
    void client?.bootstrap({ force: true });
  }, [client]);

  if (status === "authenticated" && !pending) return <AlreadySignedIn locale={locale} next={next} />;
  if (status === "unknown" || status === "loading") return <Checking locale={locale} />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!agreed) return setError(t.auth.mustAgree);
    if (!client) return;
    let path: string;
    let body: Record<string, string>;
    if (mode === "sms") {
      const e164 = toE164(phone);
      if (!e164) return setError(t.auth.invalidPhone);
      if (!validCode(code)) return setError(t.auth.invalidCode);
      path = ENDPOINTS.auth.smsLogin;
      body = { phone: e164, code: code.trim(), agree_terms_version: termsVersion };
    } else {
      path = ENDPOINTS.auth.passwordLogin;
      body = { login: toE164(login) ?? login.trim(), password };
    }
    setPending(true);
    try {
      await client.login(path, body);
      router.replace(next);
    } catch (caught) {
      setError(errorText(caught, t.community.genericError, t.community.networkError));
      setPending(false);
    }
  };

  return (
    <AuthCard>
      <Segmented
        label={t.auth.loginTitle}
        value={mode}
        onChange={(value) => {
          setMode(value);
          setError(null);
        }}
        options={[
          { id: "sms", label: t.auth.tabSms },
          { id: "password", label: t.auth.tabPassword },
        ]}
      />
      <form className="grid gap-4" onSubmit={(event) => void submit(event)} noValidate>
        {mode === "sms" ? (
          <>
            <PhoneCodeFields locale={locale} purpose="login" phone={phone} code={code} onPhone={setPhone} onCode={setCode} onError={setError} />
            <p className="m-0 text-xs text-muted-foreground">{t.auth.smsHint}</p>
          </>
        ) : (
          <>
            <Field label={t.auth.account} htmlFor="login-account">
              <input id="login-account" autoComplete="username" required value={login} onChange={(event) => setLogin(event.target.value)} className={INPUT} />
            </Field>
            <Field
              label={t.auth.password}
              htmlFor="login-password"
              aside={
                <Link href={localePath(locale, "/reset-password")} className="text-xs font-medium text-primary hover:underline">
                  {t.auth.forgot}
                </Link>
              }
            >
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className={INPUT}
              />
            </Field>
          </>
        )}
        <Consent locale={locale} checked={agreed} onChange={setAgreed} />
        {error && <Notice tone="error">{error}</Notice>}
        <SubmitButton pending={pending}>{mode === "sms" ? t.auth.loginOrRegister : t.auth.login}</SubmitButton>
      </form>
      {/* 两段之间用 gap 隔开,不在 JSX 里写空格:中文里那会是一个多余的空格。 */}
      <p className="m-0 flex flex-wrap justify-center gap-x-1.5 text-sm text-muted-foreground">
        {t.auth.noAccount}
        <Link href={`${localePath(locale, "/register")}${rawNext ? `?next=${encodeURIComponent(rawNext)}` : ""}`} className="font-semibold text-primary hover:underline">
          {t.auth.register}
        </Link>
      </p>
    </AuthCard>
  );
}

export function RegisterForm({ locale, next: rawNext }: { locale: Locale; next: string | null }) {
  const t = getMessages(locale);
  const router = useRouter();
  const { client, status } = useSession();
  const { termsVersion } = useAuthConfig();
  const next = safeNext(rawNext, locale);
  const [handle, setHandle] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [code, setCode] = React.useState("");
  const [agreed, setAgreed] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  React.useEffect(() => {
    void client?.bootstrap({ force: true });
  }, [client]);

  if (status === "authenticated" && !pending) return <AlreadySignedIn locale={locale} next={next} />;
  if (status === "unknown" || status === "loading") return <Checking locale={locale} />;

  const handleInvalid = handle.length > 0 && !validHandle(handle);
  const passwordInvalid = password.length > 0 && !validPassword(password);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!agreed) return setError(t.auth.mustAgree);
    if (!validHandle(handle)) return setError(t.auth.invalidHandle);
    if (!validPassword(password)) return setError(t.auth.invalidPassword);
    const e164 = toE164(phone);
    if (!e164) return setError(t.auth.invalidPhone);
    if (!validCode(code)) return setError(t.auth.invalidCode);
    if (!client) return;
    setPending(true);
    try {
      await client.login(ENDPOINTS.auth.register, { handle, password, phone: e164, code: code.trim(), agree_terms_version: termsVersion });
      router.replace(next);
    } catch (caught) {
      setError(errorText(caught, t.community.genericError, t.community.networkError));
      setPending(false);
    }
  };

  return (
    <AuthCard>
      <form className="grid gap-4" onSubmit={(event) => void submit(event)} noValidate>
        <Field label={t.auth.handle} htmlFor="register-handle" hint={t.auth.handleHint} error={handleInvalid ? t.auth.invalidHandle : null}>
          <input
            id="register-handle"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={handle}
            onChange={(event) => setHandle(event.target.value.toLowerCase())}
            aria-invalid={handleInvalid || undefined}
            className={INPUT}
          />
        </Field>
        <Field label={t.auth.password} htmlFor="register-password" hint={t.auth.passwordHint} error={passwordInvalid ? t.auth.invalidPassword : null}>
          <input
            id="register-password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={passwordInvalid || undefined}
            className={INPUT}
          />
        </Field>
        <PhoneCodeFields locale={locale} purpose="bind" phone={phone} code={code} onPhone={setPhone} onCode={setCode} onError={setError} />
        <Consent locale={locale} checked={agreed} onChange={setAgreed} />
        {error && <Notice tone="error">{error}</Notice>}
        <SubmitButton pending={pending}>{t.auth.createAccount}</SubmitButton>
      </form>
      <p className="m-0 flex flex-wrap justify-center gap-x-1.5 text-sm text-muted-foreground">
        {t.auth.haveAccount}
        <Link href={`${localePath(locale, "/login")}${rawNext ? `?next=${encodeURIComponent(rawNext)}` : ""}`} className="font-semibold text-primary hover:underline">
          {t.auth.login}
        </Link>
      </p>
    </AuthCard>
  );
}

export function ResetPasswordForm({ locale }: { locale: Locale }) {
  const t = getMessages(locale);
  const { client } = useSession();
  const [phone, setPhone] = React.useState("");
  const [code, setCode] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [agreed, setAgreed] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);
  const [done, setDone] = React.useState(false);

  if (done) {
    return (
      <AuthCard>
        <Notice tone="success">{t.auth.resetDone}</Notice>
        <Link href={localePath(locale, "/login")} className={BUTTON.primary}>
          {t.auth.backToLogin}
        </Link>
      </AuthCard>
    );
  }

  const passwordInvalid = password.length > 0 && !validPassword(password);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!agreed) return setError(t.auth.mustAgree);
    const e164 = toE164(phone);
    if (!e164) return setError(t.auth.invalidPhone);
    if (!validCode(code)) return setError(t.auth.invalidCode);
    if (!validPassword(password)) return setError(t.auth.invalidPassword);
    if (!client) return;
    setPending(true);
    try {
      await client.fetchJson(ENDPOINTS.auth.passwordReset, { method: "POST", json: { phone: e164, code: code.trim(), new_password: password } });
      // 服务吊销了这个人的全部会话:本页若还登录着,也跟着退出。
      client.forget();
      setDone(true);
    } catch (caught) {
      setError(errorText(caught, t.community.genericError, t.community.networkError));
    } finally {
      setPending(false);
    }
  };

  return (
    <AuthCard>
      <form className="grid gap-4" onSubmit={(event) => void submit(event)} noValidate>
        <PhoneCodeFields locale={locale} purpose="reset" phone={phone} code={code} onPhone={setPhone} onCode={setCode} onError={setError} />
        <Field label={t.auth.newPassword} htmlFor="reset-password" hint={t.auth.passwordHint} error={passwordInvalid ? t.auth.invalidPassword : null}>
          <input
            id="reset-password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={passwordInvalid || undefined}
            className={INPUT}
          />
        </Field>
        <Consent locale={locale} checked={agreed} onChange={setAgreed} />
        {error && <Notice tone="error">{error}</Notice>}
        <SubmitButton pending={pending}>{t.auth.resetSubmit}</SubmitButton>
      </form>
      <p className="m-0 text-center text-sm">
        <Link href={localePath(locale, "/login")} className="font-semibold text-primary hover:underline">
          {t.auth.backToLogin}
        </Link>
      </p>
    </AuthCard>
  );
}
