"use client";

/**
 * 设备授权(RFC 8628,ADR 0026 §3「桌面应用」):应用打开浏览器到 `/{locale}/device?code=XXXX-XXXX`,
 * 用户在这里登录、核对设备码、点「允许」,应用那边轮询拿到令牌。
 *
 * 没登录时先送去登录页,`next` 带着设备码回到这里。「不是我发起的」不发请求 —— ADR 没有拒绝接口,
 * 不批准的设备码到期自然作废。
 */
import { CheckCircle2, MonitorSmartphone, ShieldCheck, XCircle } from "lucide-react";
import * as React from "react";

import { Avatar } from "@/components/community/header-menus";
import { useRequireSession } from "@/components/community/session-provider";
import { BUTTON, Field, INPUT, Notice, Spinner, errorText } from "@/components/community/ui";
import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { normalizeUserCode } from "@/lib/community/input";
import { cn } from "@/lib/utils";

const CODE_PATTERN = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/;

export function DeviceApproval({ locale, initialCode }: { locale: Locale; initialCode: string }) {
  const t = getMessages(locale);
  const session = useRequireSession(locale);
  const [code, setCode] = React.useState(() => normalizeUserCode(initialCode));
  const [state, setState] = React.useState<"idle" | "pending" | "approved" | "denied">("idle");
  const [error, setError] = React.useState<string | null>(null);

  if (session.status !== "authenticated" || !session.user) {
    return (
      <p className="m-0 inline-flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        {session.status === "anonymous" ? t.device.loginFirst : t.auth.checking}
      </p>
    );
  }

  if (state === "approved" || state === "denied") {
    return (
      <div className="grid justify-items-center gap-4 rounded-2xl border border-border bg-card px-6 py-12 text-center">
        {state === "approved" ? <CheckCircle2 className="size-10 text-primary" aria-hidden /> : <XCircle className="size-10 text-muted-foreground" aria-hidden />}
        <p className="m-0 max-w-sm text-sm leading-6">{state === "approved" ? t.device.approved : t.device.denied}</p>
      </div>
    );
  }

  const valid = CODE_PATTERN.test(code);
  const approve = async () => {
    if (!valid) return setError(t.device.invalidCode);
    setError(null);
    setState("pending");
    try {
      await session.communityFetch(ENDPOINTS.auth.deviceApprove, { method: "POST", json: { user_code: code } });
      setState("approved");
    } catch (caught) {
      const status = (caught as { status?: number }).status;
      setError(status === 404 || status === 410 ? t.device.expired : errorText(caught, t.community.genericError, t.community.networkError));
      setState("idle");
    }
  };

  return (
    <div className="grid gap-5 rounded-2xl border border-border bg-card p-5 sm:p-7">
      <div className="flex items-center gap-3">
        <span className="grid size-11 place-items-center rounded-xl bg-brand-soft text-primary">
          <MonitorSmartphone className="size-5" aria-hidden />
        </span>
        <p className="m-0 text-base font-semibold">{t.device.lede}</p>
      </div>

      <Field label={t.device.codeLabel} htmlFor="device-code" hint={t.device.codeHint} error={code && !valid ? t.device.invalidCode : null}>
        <input
          id="device-code"
          value={code}
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setCode(normalizeUserCode(event.target.value))}
          className={cn(INPUT, "h-14 text-center font-mono text-2xl tracking-[0.3em]")}
        />
      </Field>

      <div className="grid gap-2">
        <span className="text-sm text-muted-foreground">{t.device.signedInAs}</span>
        <span className="flex items-center gap-2.5">
          <Avatar user={session.user} />
          <span className="grid">
            <span className="text-sm font-semibold">{session.user.display_name || session.user.handle}</span>
            <span className="font-mono text-xs text-muted-foreground">@{session.user.handle}</span>
          </span>
        </span>
      </div>

      <ul className="m-0 grid list-none gap-2 p-0 text-sm">
        {t.device.grants.map((grant) => (
          <li key={grant} className="flex items-start gap-2.5">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            {grant}
          </li>
        ))}
      </ul>

      {error && <Notice tone="error">{error}</Notice>}
      <div className="flex flex-wrap gap-2.5">
        <button type="button" onClick={() => void approve()} disabled={state === "pending" || !valid} className={BUTTON.primary}>
          {state === "pending" && <Spinner />}
          {state === "pending" ? t.device.approving : t.device.approve}
        </button>
        <button type="button" onClick={() => setState("denied")} disabled={state === "pending"} className={BUTTON.secondary}>
          {t.device.deny}
        </button>
      </div>
    </div>
  );
}
