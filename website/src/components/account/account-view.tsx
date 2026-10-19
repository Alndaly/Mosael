"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount, type CloudDevice, type CloudUser } from "@/lib/cloud";

type Phase = "loading" | "anonymous" | "signed" | "error";

const FIELD =
  "h-10 w-full rounded-lg border border-border bg-background px-3 font-mono text-sm uppercase tracking-[0.12em] outline-none transition-[border-color,box-shadow] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * 账号页:**只知道云端身份**。
 *
 * 它不请求本地后端、不显示工作区 / 素材 / 本地用户名 —— 那属于本机 Mosael,这一页是 MosaelCloud 的。
 * 设备确认也在这里:桌面端显示 `user_code`,用户在这个已登录的页面点一下确认。
 */
export function AccountView({ locale, copy, initialCode = "" }: { locale: Locale; copy: Messages["account"]; initialCode?: string }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("loading");
  const [user, setUser] = useState<CloudUser | null>(null);
  const [devices, setDevices] = useState<CloudDevice[]>([]);
  const [code, setCode] = useState(initialCode.toUpperCase());
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    cloudAccount
      .me()
      .then(async (me) => {
        const list = await cloudAccount.devices();
        if (!alive) return;
        setUser(me.user);
        setDevices(list.devices);
        setPhase("signed");
      })
      .catch((failure: unknown) => {
        if (!alive) return;
        if (failure instanceof CloudApiError && failure.status === 401) {
          setPhase("anonymous");
          return;
        }
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
    if (!code.trim()) {
      setError(copy.deviceCodeRequired);
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

  const signOut = async () => {
    setBusy("logout");
    try {
      await cloudAccount.logout();
    } catch {
      // 本地无状态可清:cookie 由服务端撤销;即使请求失败,离开这一页也不显示旧账号。
    }
    router.push(`/${locale}/login`);
  };

  const remove = async () => {
    setBusy("delete");
    setError("");
    try {
      await cloudAccount.deleteAccount();
      router.push(`/${locale}`);
    } catch (failure) {
      setError(failure instanceof CloudApiError ? failure.text(locale) : copy.actionFailed);
      setBusy("");
    }
  };

  if (phase === "loading") {
    return <p className="text-sm text-muted-foreground">{copy.loading}</p>;
  }

  if (phase === "anonymous") {
    return (
      <div className="grid gap-4">
        <p className="text-sm leading-7 text-muted-foreground">{copy.loginRequired}</p>
        <div className="flex flex-wrap gap-3">
          <Button asChild>
            <Link href={`/${locale}/login`}>{copy.signIn}</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href={`/${locale}/signup`}>{copy.signup}</Link>
          </Button>
        </div>
      </div>
    );
  }

  if (phase === "error" || !user) {
    return (
      <div className="grid gap-4">
        <p className="text-sm text-destructive" role="alert">
          {error || copy.loadFailed}
        </p>
        <Button
          variant="outline"
          onClick={() => {
            setPhase("loading");
            setReloadKey((key) => key + 1);
          }}
        >
          {copy.signIn}
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-8">
      <div className="grid gap-2">
        <span className="text-xs font-semibold tracking-[0.12em] text-muted-foreground uppercase">{copy.account}</span>
        <strong className="break-all text-lg">{user.email}</strong>
        <div className="flex flex-wrap gap-3 pt-1">
          <Button variant="outline" size="sm" disabled={busy === "logout"} onClick={() => void signOut()}>
            {copy.signOut}
          </Button>
          {confirmingDelete ? (
            <>
              <Button variant="destructive" size="sm" disabled={busy === "delete"} onClick={() => void remove()}>
                {busy === "delete" ? copy.deleting : copy.deleteYes}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmingDelete(false)}>
                {copy.cancel}
              </Button>
            </>
          ) : (
            <Button variant="destructive" size="sm" onClick={() => setConfirmingDelete(true)}>
              {copy.deleteAccount}
            </Button>
          )}
        </div>
        {confirmingDelete && <p className="text-sm text-muted-foreground">{copy.deleteConfirm}</p>}
      </div>

      <div className="grid gap-3 border-t border-border pt-6">
        <h2 className="m-0 text-base font-semibold">{copy.devices}</h2>
        {devices.length === 0 ? (
          <p className="text-sm text-muted-foreground">{copy.noDevices}</p>
        ) : (
          <ul className="m-0 grid list-none gap-2 p-0">
            {devices.map((device) => (
              <li key={device.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border px-3 py-2">
                <span className="min-w-0 break-all text-sm">{device.name || device.id}</span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy === device.id}
                  onClick={() => void revoke(device.id)}
                >
                  {busy === device.id ? copy.revoking : copy.revoke}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form className="grid gap-3 border-t border-border pt-6" onSubmit={approve} noValidate>
        <h2 className="m-0 text-base font-semibold">{copy.approve}</h2>
        <label className="grid gap-1.5 text-sm">
          {copy.deviceCode}
          <input
            className={FIELD}
            value={code}
            placeholder="ABCD-EFGH"
            autoComplete="one-time-code"
            onChange={(event) => setCode(event.target.value)}
          />
        </label>
        <p className="m-0 text-sm leading-6 text-muted-foreground">{copy.deviceCodeHint}</p>
        <div>
          <Button type="submit" disabled={busy === "approve"}>
            {busy === "approve" ? copy.approving : copy.approve}
          </Button>
        </div>
      </form>

      {notice && (
        <output className="m-0 text-sm text-primary">
          {notice}
        </output>
      )}
      {error && (
        <p className="m-0 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
