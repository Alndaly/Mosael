"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import QRCode from "qrcode";

import { AccountField, FormAlert } from "@/components/account/form-controls";
import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount, type CloudMfaStatus } from "@/lib/cloud";

/** 控制台的「安全」分区：TOTP 自选开启、恢复码、关闭。 */
export function DashboardSecurity({
  locale,
  copy,
}: {
  locale: Locale;
  copy: Messages["dashboard"];
}) {
  const [status, setStatus] = useState<CloudMfaStatus | null>(null);
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);

  const fail = (failure: unknown) =>
    setError(failure instanceof CloudApiError ? failure.text(locale) : copy.mfaFailed);

  const refresh = async () => {
    try {
      setStatus(await cloudAccount.mfaStatus());
      setError("");
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.mfaLoadFailed);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // refresh 只依赖稳定的 client 与 locale 文案；首屏读取一次即可。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startSetup = async () => {
    setBusy("setup");
    setError("");
    try {
      const started = await cloudAccount.setupMfa();
      setSetup(started);
      setQr(await QRCode.toDataURL(started.otpauth_uri, { width: 190, margin: 1 }));
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy("");
    }
  };

  const enable = async () => {
    if (!code.trim()) {
      setError(copy.mfaCodeRequired);
      return;
    }
    setBusy("enable");
    setError("");
    try {
      const result = await cloudAccount.enableMfa(code.trim());
      setCodes(result.recovery_codes);
      setStatus({ enabled: true, recovery_codes_remaining: result.recovery_codes.length });
      setSetup(null);
      setQr("");
      setCode("");
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy("");
    }
  };

  const disable = async () => {
    if (!code.trim()) {
      setError(copy.mfaCodeRequired);
      return;
    }
    setBusy("disable");
    setError("");
    try {
      await cloudAccount.disableMfa(code.trim());
      setStatus({ enabled: false, recovery_codes_remaining: 0 });
      setCodes([]);
      setCode("");
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy("");
    }
  };

  const regenerate = async () => {
    if (!code.trim()) {
      setError(copy.mfaCodeRequired);
      return;
    }
    setBusy("recovery");
    setError("");
    try {
      const result = await cloudAccount.regenerateMfaRecoveryCodes(code.trim());
      setCodes(result.recovery_codes);
      setStatus((current) =>
        current ? { ...current, recovery_codes_remaining: result.recovery_codes.length } : current,
      );
      setCode("");
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy("");
    }
  };

  return (
    <section aria-labelledby="dashboard-security" className="rounded-3xl border border-border bg-card p-6 sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="dashboard-security" className="m-0 font-display text-xl font-semibold tracking-[-0.03em]">
            {copy.mfaTitle}
          </h2>
          <p className="mt-1 mb-0 max-w-2xl text-[13px] leading-6 text-muted-foreground">{copy.mfaLede}</p>
        </div>
        {!loading && status && (
          <span className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground">
            {status.enabled ? copy.mfaOn : copy.mfaOff}
          </span>
        )}
      </div>

      {loading ? (
        <p className="mt-5 text-[13px] text-muted-foreground">{copy.mfaLoading}</p>
      ) : (
        <div className="mt-5 grid gap-5">
          {error && (
            <FormAlert id="dashboard-mfa-error" title={copy.mfaTitle}>
              {error}
            </FormAlert>
          )}

          {codes.length > 0 && (
            <div className="grid gap-3 rounded-2xl border border-primary/30 bg-brand-soft px-4 py-4">
              <strong className="text-sm font-semibold">{copy.mfaRecoveryTitle}</strong>
              <p className="m-0 text-[13px] leading-6 text-muted-foreground">{copy.mfaRecoveryOnce}</p>
              <pre className="m-0 overflow-x-auto rounded-xl bg-card px-4 py-3 font-mono text-[13px] leading-6">
                {codes.join("\n")}
              </pre>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  type="button"
                  onClick={() => void navigator.clipboard.writeText(codes.join("\n")).catch(() => undefined)}
                >
                  {copy.mfaCopy}
                </Button>
                <Button variant="ghost" type="button" onClick={() => setCodes([])}>
                  {copy.mfaSaved}
                </Button>
              </div>
            </div>
          )}

          {!status?.enabled && !setup && (
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={() => void startSetup()} disabled={Boolean(busy)}>
                {busy === "setup" ? copy.mfaStarting : copy.mfaEnable}
              </Button>
            </div>
          )}

          {setup && (
            <div className="grid gap-4 rounded-2xl border border-border px-4 py-4">
              <p className="m-0 text-[13px] leading-6 text-muted-foreground">{copy.mfaScan}</p>
              {qr && (
                <Image src={qr} alt={copy.mfaQrAlt} width={190} height={190} unoptimized className="rounded-xl" />
              )}
              <div className="min-w-0">
                <p className="m-0 text-xs font-medium text-muted-foreground">{copy.mfaSecret}</p>
                <code className="mt-1 block font-mono text-[13px] [overflow-wrap:anywhere]">{setup.secret}</code>
              </div>
              <AccountField
                id="dashboard-mfa-setup-code"
                label={copy.mfaCode}
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => void enable()} disabled={busy === "enable"}>
                  {busy === "enable" ? copy.mfaStarting : copy.mfaConfirm}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setSetup(null);
                    setQr("");
                    setCode("");
                    setError("");
                  }}
                >
                  {copy.mfaCancel}
                </Button>
              </div>
            </div>
          )}

          {status?.enabled && (
            <div className="grid gap-4 border-t border-border pt-4">
              <p className="m-0 text-[13px] leading-6 text-muted-foreground">
                {copy.mfaRecoveryRemaining.replace("{count}", String(status.recovery_codes_remaining))}
              </p>
              <AccountField
                id="dashboard-mfa-code"
                label={copy.mfaCode}
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void regenerate()}
                  disabled={Boolean(busy)}
                >
                  {busy === "recovery" ? copy.mfaRegenerating : copy.mfaRegenerate}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void disable()}
                  disabled={Boolean(busy)}
                >
                  {busy === "disable" ? copy.mfaDisabling : copy.mfaDisable}
                </Button>
              </div>
              <p className="m-0 text-xs leading-5 text-muted-foreground">{copy.mfaDisableHint}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
