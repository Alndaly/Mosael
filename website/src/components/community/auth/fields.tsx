"use client";

/**
 * 登录、注册、找回密码共用的几块:手机号 + 验证码(60 秒倒计时、可选腾讯云验证码)、
 * 协议勾选。
 */
import Link from "next/link";
import * as React from "react";

import { useSession } from "@/components/community/session-provider";
import { BUTTON, Field, INPUT, errorText } from "@/components/community/ui";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS, REQUESTED, browserUrl } from "@/lib/community/endpoints";
import { fill } from "@/lib/community/format";
import { toE164, validCode } from "@/lib/community/input";
import type { AuthConfig } from "@/lib/community/types";
import { cn } from "@/lib/utils";

/**
 * 协议的版本号:随注册 / 首次短信登录一起交给服务(`agree_terms_version`),服务只存版本号和同意时间。
 * 以服务的 `GET /auth/config` 为准(和它校验的是同一个值);取不到时用构建期的
 * `NEXT_PUBLIC_COMMUNITY_TERMS_VERSION`。
 */
const TERMS_VERSION = process.env.NEXT_PUBLIC_COMMUNITY_TERMS_VERSION?.trim() || "1";

/** 腾讯云验证码的 CaptchaAppId(公开值)。构建期配了用它,否则用服务 `/auth/config` 给的。 */
const CAPTCHA_APP_ID = process.env.NEXT_PUBLIC_TENCENT_CAPTCHA_APP_ID?.trim() || "";

let configRequest: Promise<AuthConfig | null> | null = null;

function loadAuthConfig(): Promise<AuthConfig | null> {
  if (!configRequest) {
    configRequest = fetch(browserUrl(REQUESTED.authConfig), { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? (response.json() as Promise<AuthConfig>) : null))
      .catch(() => null);
  }
  return configRequest;
}

/** 登录页要的公开配置,一页取一次。 */
export function useAuthConfig(): { termsVersion: string; captchaAppId: string } {
  const [config, setConfig] = React.useState<AuthConfig | null>(null);
  React.useEffect(() => {
    let cancelled = false;
    void loadAuthConfig().then((value) => {
      if (!cancelled) setConfig(value);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return {
    termsVersion: config?.terms_version || TERMS_VERSION,
    captchaAppId: CAPTCHA_APP_ID || config?.captcha?.app_id || "",
  };
}
const CAPTCHA_SCRIPT = "https://turing.captcha.qcloud.com/TJCaptcha.js";

type CaptchaResult = { ticket: string; randstr: string };
type TencentCaptchaInstance = { show(): void; destroy?(): void };
type TencentCaptchaConstructor = new (appId: string, callback: (result: { ret: number; ticket?: string; randstr?: string }) => void, options?: object) => TencentCaptchaInstance;

let captchaScript: Promise<TencentCaptchaConstructor> | null = null;

function loadCaptcha(): Promise<TencentCaptchaConstructor> {
  if (!captchaScript) {
    captchaScript = new Promise((resolve, reject) => {
      const existing = (window as unknown as { TencentCaptcha?: TencentCaptchaConstructor }).TencentCaptcha;
      if (existing) return resolve(existing);
      const script = document.createElement("script");
      script.src = CAPTCHA_SCRIPT;
      script.async = true;
      script.onload = () => {
        const loaded = (window as unknown as { TencentCaptcha?: TencentCaptchaConstructor }).TencentCaptcha;
        if (loaded) resolve(loaded);
        else reject(new Error("captcha unavailable"));
      };
      script.onerror = () => {
        captchaScript = null;
        reject(new Error("captcha unavailable"));
      };
      document.head.appendChild(script);
    });
  }
  return captchaScript;
}

/**
 * 发短信前的人机验证(腾讯云验证码 / 天御):配了 `NEXT_PUBLIC_TENCENT_CAPTCHA_APP_ID`,或社区服务开了
 * 验证码(`/auth/config` 给出 AppId)才启用。用户关掉验证窗口返回 null(不算错,只是不发)。
 */
async function runCaptcha(appId: string): Promise<CaptchaResult | null> {
  const Captcha = await loadCaptcha();
  return new Promise((resolve, reject) => {
    const captcha = new Captcha(appId, (result) => {
      if (result.ret === 0 && result.ticket && result.randstr) resolve({ ticket: result.ticket, randstr: result.randstr });
      else if (result.ret === 2) resolve(null);
      else reject(new Error("captcha failed"));
    });
    captcha.show();
  });
}

export const RESEND_SECONDS = 60;

/**
 * 手机号 + 验证码两栏。「获取验证码」按下去:格式对 → (配了的话)过人机验证 → 发短信 →
 * 60 秒倒计时。服务端的限速(60 秒一条、一天十条)会回 429,message 照原样显示。
 */
export function PhoneCodeFields({
  locale,
  purpose,
  phone,
  code,
  onPhone,
  onCode,
  onError,
}: {
  locale: Locale;
  purpose: "login" | "bind" | "reset";
  phone: string;
  code: string;
  onPhone: (value: string) => void;
  onCode: (value: string) => void;
  onError: (message: string | null) => void;
}) {
  const t = getMessages(locale);
  const { client } = useSession();
  const { captchaAppId } = useAuthConfig();
  const [left, setLeft] = React.useState(0);
  const [sending, setSending] = React.useState(false);
  const [sent, setSent] = React.useState(false);

  // 倒计时一秒走一格。差个几十毫秒无所谓 —— 真正的「60 秒内不重发」由服务端限速把关。
  React.useEffect(() => {
    if (left <= 0) return;
    const timer = window.setTimeout(() => setLeft((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [left]);

  const send = async () => {
    onError(null);
    const e164 = toE164(phone);
    if (!e164) {
      onError(t.auth.invalidPhone);
      return;
    }
    if (!client) return;
    setSending(true);
    try {
      let captcha: CaptchaResult | null = null;
      if (captchaAppId) {
        try {
          captcha = await runCaptcha(captchaAppId);
        } catch {
          onError(t.auth.captchaFailed);
          return;
        }
        if (!captcha) return;
      }
      await client.fetchJson(ENDPOINTS.auth.smsSend, { method: "POST", json: { phone: e164, purpose, ...(captcha ? { captcha } : {}) } });
      setLeft(RESEND_SECONDS);
      setSent(true);
    } catch (error) {
      onError(errorText(error, t.community.genericError, t.community.networkError));
    } finally {
      setSending(false);
    }
  };

  const codeInvalid = code.length > 0 && !validCode(code);
  return (
    <>
      <Field label={t.auth.phone} htmlFor={`${purpose}-phone`}>
        <input
          id={`${purpose}-phone`}
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          required
          value={phone}
          onChange={(event) => onPhone(event.target.value)}
          placeholder={t.auth.phonePlaceholder}
          className={INPUT}
        />
      </Field>
      <Field label={t.auth.code} htmlFor={`${purpose}-code`} error={codeInvalid ? t.auth.invalidCode : null} hint={sent ? t.auth.codeSent : undefined}>
        <div className="flex gap-2">
          <input
            id={`${purpose}-code`}
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            required
            value={code}
            onChange={(event) => onCode(event.target.value.replace(/\D/g, ""))}
            placeholder={t.auth.codePlaceholder}
            aria-invalid={codeInvalid || undefined}
            className={cn(INPUT, "font-mono tracking-[0.3em]")}
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={sending || left > 0 || !client}
            className={cn(BUTTON.secondary, "shrink-0 px-4 tabular-nums")}
          >
            {left > 0 ? fill(t.auth.resendIn, { s: left }) : t.auth.sendCode}
          </button>
        </div>
      </Field>
    </>
  );
}

/** 《用户协议》《隐私政策》勾选。链接开新页 —— 读完回来,填了一半的表单还在。 */
export function Consent({ locale, checked, onChange }: { locale: Locale; checked: boolean; onChange: (value: boolean) => void }) {
  const t = getMessages(locale).auth;
  const link = "font-medium text-primary hover:underline";
  return (
    <label className="flex items-start gap-2.5 text-sm leading-6 text-muted-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 size-4 shrink-0 accent-[var(--primary)]"
      />
      <span>
        {/* 词间空格写在文案里(英文要、中文不要),JSX 这里不另加。 */}
        {t.agreePrefix}
        <Link href={localePath(locale, "/terms")} target="_blank" className={link}>
          {t.terms}
        </Link>
        {t.and}
        <Link href={localePath(locale, "/privacy")} target="_blank" className={link}>
          {t.privacy}
        </Link>
      </span>
    </label>
  );
}

/** 登录、注册、找回三页的卡片外形。 */
export function AuthCard({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-5 rounded-2xl border border-border bg-card p-5 sm:p-7">{children}</div>;
}
