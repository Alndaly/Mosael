"use client";

import { AlertCircle, LoaderCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { CloudApiError, cloudProfile, type CloudIdentity } from "@/lib/cloud";
import { invalidateAfterProfileSave } from "@/lib/query-invalidation";
import { cn } from "@/lib/utils";

import { publicIdentity } from "./share-utils";

/**
 * 第一次发布 / 评论前的「起个名字」。
 *
 * 后端把「没有昵称」定成 409 `identity_required`(不是 401、也不是 422),意思很明确:
 * 账号已经有,只差一个别人看得见的名字。所以这里不要跳转、不要重新登录 —— 就在原地补上,
 * 补完继续刚才那件事(见 `share-detail.tsx` 的评论重试)。
 */
export function IdentityForm({
  locale,
  initialDisplayName = "",
  onDone,
  className,
}: {
  locale: Locale;
  initialDisplayName?: string;
  onDone: (identity: CloudIdentity) => void;
  className?: string;
}) {
  const t = getMessages(locale).community;
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = React.useState(initialDisplayName);
  const [handle, setHandle] = React.useState("");
  const [displayError, setDisplayError] = React.useState("");
  const [handleError, setHandleError] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setDisplayError("");
    setHandleError("");
    try {
      const patch: { display_name: string; handle?: string } = { display_name: displayName.trim() };
      // 空 handle = 不要短名,交给服务端自动生成;发一个空串过去会被 422 判成非法。
      if (handle.trim()) patch.handle = handle.trim();
      const { user } = await cloudProfile.update(patch);
      // 第一次起名字也是改资料:站头 / 我的分享 / 公开列表的作者名一起换新。
      await invalidateAfterProfileSave(queryClient);
      onDone(publicIdentity(user));
    } catch (failure) {
      if (failure instanceof CloudApiError) {
        if (failure.code.startsWith("display_name")) setDisplayError(failure.text(locale));
        else if (failure.code.startsWith("handle")) setHandleError(failure.text(locale));
        else setError(failure.text(locale));
      } else {
        setError(t.identityFailed);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className={cn("grid min-w-0 gap-4", className)}>
      <div className="grid gap-1">
        <h2 className="m-0 text-base font-semibold">{t.identityTitle}</h2>
        <p className="m-0 text-sm leading-6 text-muted-foreground">{t.identityLede}</p>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="community-display-name">{t.displayName}</Label>
        <Input
          id="community-display-name"
          name="display_name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder={t.displayNamePlaceholder}
          autoComplete="name"
          maxLength={40}
          required
          aria-invalid={Boolean(displayError)}
          aria-describedby={displayError ? "community-display-name-error" : undefined}
        />
        {displayError && (
          <p id="community-display-name-error" role="alert" className="m-0 flex items-start gap-1.5 text-[13px] text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {displayError}
          </p>
        )}
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="community-handle">{t.handle}</Label>
        <Input
          id="community-handle"
          name="handle"
          value={handle}
          onChange={(event) => setHandle(event.target.value)}
          placeholder={t.handlePlaceholder}
          autoComplete="off"
          spellCheck={false}
          maxLength={24}
          aria-invalid={Boolean(handleError)}
          aria-describedby={handleError ? "community-handle-error" : "community-handle-hint"}
          className="font-mono"
        />
        {handleError ? (
          <p id="community-handle-error" role="alert" className="m-0 flex items-start gap-1.5 text-[13px] text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {handleError}
          </p>
        ) : (
          <p id="community-handle-hint" className="m-0 text-xs leading-5 text-muted-foreground">
            {t.handleHint}
          </p>
        )}
      </div>

      {error && (
        <p role="alert" className="m-0 flex items-start gap-1.5 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] leading-5 text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}

      <div>
        <Button type="submit" disabled={busy} className="min-h-10 rounded-full px-5">
          {busy ? <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
          {busy ? t.savingIdentity : t.saveIdentity}
        </Button>
      </div>
    </form>
  );
}
