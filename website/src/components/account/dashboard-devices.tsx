"use client";

import { AlertTriangle, KeyRound, Laptop } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { AccountField, FormAlert, FormNotice, SubmitButton } from "@/components/account/form-controls";
import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount, type CloudDevice } from "@/lib/cloud";

/**
 * 设备:已绑定的设备 + 确认这台设备。
 *
 * 这两块**原样搬自** `/account`(见 `src/app/[locale]/(auth)/account/page.tsx` 的历史):
 * 桌面端显示 `user_code`,用户在这个已登录的页面点一下确认。处理方式一字未改 —— 同样的
 * `cloudAccount.devices / revokeDevice / approveDevice`,同样的「撤销后需重新确认」提示,
 * 同样的后端错误文案。只是位置从账号页挪到了控制台的「设备」分区,并带上桌面绑定链接里的
 * `?user_code=`(由 `/account` 转过来)。
 */
export function DashboardDevices({
  locale,
  copy,
  initialCode = "",
}: {
  locale: Locale;
  copy: Messages["account"];
  initialCode?: string;
}) {
  const [devices, setDevices] = useState<CloudDevice[]>([]);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [code, setCode] = useState(initialCode.toUpperCase());
  const [codeError, setCodeError] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    cloudAccount
      .devices()
      .then((list) => {
        if (!alive) return;
        setDevices(list.devices);
        setPhase("ready");
      })
      .catch((failure: unknown) => {
        if (!alive) return;
        setError(failure instanceof CloudApiError ? failure.text(locale) : copy.loadFailed);
        setPhase("error");
      });
    return () => {
      alive = false;
    };
  }, [locale, copy.loadFailed, reloadKey]);

  const approve = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    setCodeError("");
    if (!code.trim()) {
      setCodeError(copy.deviceCodeRequired);
      return;
    }
    setBusy("approve");
    try {
      await cloudAccount.approveDevice(code.trim());
      setNotice(copy.approved);
      setCode("");
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy("");
    }
  };

  const revoke = async (deviceId: string) => {
    setError("");
    setNotice("");
    setBusy(deviceId);
    try {
      await cloudAccount.revokeDevice(deviceId);
      setDevices((current) => current.filter((device) => device.id !== deviceId));
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
    } finally {
      setBusy("");
    }
  };

  if (phase === "loading") {
    return (
      <div aria-busy="true" aria-live="polite" className="grid gap-4">
        <span className="sr-only">{copy.loading}</span>
        <div className="rounded-3xl border border-border bg-card p-6">
          <div className="h-3 w-20 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
          <div className="mt-5 h-14 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" />
          <div className="mt-2.5 h-14 animate-pulse rounded-2xl bg-muted motion-reduce:animate-none" />
        </div>
        <div className="rounded-3xl border border-border bg-card p-6">
          <div className="h-3 w-24 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
          <div className="mt-5 h-7 w-3/5 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
          <div className="mt-3 h-3 w-2/5 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
        </div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div role="alert" className="rounded-3xl border border-destructive/25 bg-card p-6 sm:p-8">
        <span className="inline-flex size-11 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
          <AlertTriangle className="size-5" aria-hidden />
        </span>
        <h2 className="mt-5 font-display text-2xl font-semibold tracking-[-0.035em]">{copy.formErrorTitle}</h2>
        <p className="mt-3 text-sm leading-7 text-muted-foreground">{error || copy.loadFailed}</p>
        <Button
          variant="outline"
          className="mt-6 min-h-11 rounded-full px-5 text-sm font-semibold"
          onClick={() => {
            setError("");
            setPhase("loading");
            setReloadKey((key) => key + 1);
          }}
        >
          {copy.retry}
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {error && (
        <FormAlert id="dashboard-devices-error" title={copy.formErrorTitle}>
          {error}
        </FormAlert>
      )}
      {notice && <FormNotice>{notice}</FormNotice>}

      <section aria-labelledby="dashboard-devices" className="rounded-3xl border border-border bg-card p-6 sm:p-7">
        <div className="flex items-start gap-3">
          <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-2xl bg-secondary text-foreground">
            <Laptop className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 id="dashboard-devices" className="font-display text-xl font-semibold tracking-[-0.03em]">
              {copy.devices}
            </h2>
            <p className="mt-1 text-[13px] leading-6 text-muted-foreground">{copy.devicesHint}</p>
          </div>
        </div>

        {devices.length === 0 ? (
          <div className="mt-5 rounded-2xl border border-dashed border-border bg-paper/60 px-5 py-7 text-center">
            <Laptop className="mx-auto size-5 text-muted-foreground" aria-hidden />
            <p className="mt-3 text-sm text-muted-foreground">{copy.noDevices}</p>
          </div>
        ) : (
          <ul className="m-0 mt-5 grid list-none gap-2.5 p-0">
            {devices.map((device) => (
              <li
                key={device.id}
                className="flex min-w-0 flex-wrap items-center gap-3 rounded-2xl border border-border bg-paper/50 p-3.5 sm:flex-nowrap"
              >
                <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground">
                  <Laptop className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1 text-sm font-medium [overflow-wrap:anywhere]">{device.name || device.id}</span>
                <Button
                  variant="outline"
                  disabled={busy === device.id}
                  aria-busy={busy === device.id}
                  onClick={() => void revoke(device.id)}
                  className="min-h-9 rounded-full px-3.5 text-[13px]"
                >
                  {busy === device.id ? copy.revoking : copy.revoke}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="dashboard-approve" className="rounded-3xl border border-border bg-card p-6 sm:p-7">
        <div className="flex items-start gap-3">
          <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-accent">
            <KeyRound className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 id="dashboard-approve" className="font-display text-xl font-semibold tracking-[-0.03em]">
              {copy.approve}
            </h2>
            <p id="device-code-hint" className="mt-1 text-sm leading-7 text-muted-foreground">
              {copy.deviceCodeHint}
            </p>
          </div>
        </div>
        <form className="mt-5 grid gap-5" onSubmit={approve} noValidate>
          <AccountField
            id="device-code"
            label={copy.deviceCode}
            placeholder="ABCD-EFGH"
            autoComplete="one-time-code"
            autoCapitalize="characters"
            spellCheck={false}
            value={code}
            error={codeError}
            describedBy="device-code-hint"
            className="font-mono tracking-[0.14em] uppercase"
            onChange={(event) => setCode(event.target.value.toUpperCase())}
          />
          <SubmitButton label={copy.approve} busyLabel={copy.approving} busy={busy === "approve"} />
        </form>
      </section>
    </div>
  );
}
