"use client";

import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut, PenLine } from "lucide-react";
import { useState, type FormEvent } from "react";

import { AccountDangerZone } from "@/components/account/account-danger-zone";
import { DashboardPassword } from "@/components/account/dashboard-password";
import { AccountField, FormAlert } from "@/components/account/form-controls";

import { InitialTile } from "@/components/community/tile";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { toast } from "sonner";
import type { Locale } from "@/i18n/config";
import type { Messages } from "@/i18n/messages";
import { CloudApiError, cloudAccount, cloudProfile } from "@/lib/cloud";
import { invalidateAfterProfileSave, invalidateAfterSignOut } from "@/lib/query-invalidation";
import { useViewer } from "@/lib/queries";

import type { DashboardTab } from "./dashboard-utils";

/** 个人信息只读这两列;服务端给的公开身份与 `/me` 的完整用户都满足这个形状。 */
type ProfileViewer = { display_name?: string | null; handle?: string | null; has_password?: boolean };

/**
 * 个人信息:公开身份的两列 + 头像预览 + 保存 / 退出 + 最底下的危险区。
 *
 * **账号页收进控制台之后,这一块就是原来 `(auth)/account` 的全部内容**:身份(邮箱)、
 * 退出、删号都在这里。删号是最后一块(`AccountDangerZone`),形态与账号页那块一致:
 * 警告配色、说清不可恢复、两次点击。
 *
 * **邮箱只在这里出现,而且只有本人看得到** —— 它来自 `useViewer()` 那一份 `/me`
 * (站头也读同一份,只是站头只取公开三列),概览和分享列表都拿不到它。
 *
 * 头像预览和顶栏、社区卡片共用同一套 `--tile-*` 色相(见 `components/community/tile.tsx`):
 * 同一个名字在顶栏和这里永远同一块颜色。
 *
 * **保存成功要刷新的缓存**见 `lib/query-invalidation.ts` 的清单:viewer(站头首字母 /
 * 色块 / aria-label)+ 我的分享里的作者名 + 概览 + 个人页。只 `router.refresh()` 的话,
 * 站头那份客户端缓存不会变,所以才有了「改了昵称站头不刷新」。
 *
 * `handle_taken` / `handle_reserved` 是 409,但含义完全不同(被别人占了 / 是保留字)。
 * 前端不替后端改写成自己的句子 —— 后端给的那句就是用户该看到的那句。
 */
export function DashboardProfile({
  locale,
  copy,
  viewer,
  onSelect,
}: {
  locale: Locale;
  copy: Messages["dashboard"];
  viewer: ProfileViewer;
  onSelect: (tab: DashboardTab) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [displayName, setDisplayName] = useState(viewer.display_name ?? "");
  const [handle, setHandle] = useState(viewer.handle ?? "");
  const [displayError, setDisplayError] = useState("");
  const [handleError, setHandleError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  // 邮箱与「有没有 handle」都读同一份 viewer 缓存:保存之后 invalidate 会把它换新,
  // 不用再挂一个 useEffect 单独问一次 /me。
  const viewerQuery = useViewer();
  const currentViewer = viewerQuery.data ?? viewer;
  const email = viewerQuery.data?.email ?? null;
  const emailFailed = viewerQuery.isError || viewerQuery.data === null;
  const emailUnbound = viewerQuery.isSuccess && !email;

  const hasHandle = Boolean(currentViewer.handle?.trim());

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setDisplayError("");
    setHandleError("");
    setError("");
    const name = displayName.trim();
    if (!name) {
      setDisplayError(copy.displayNameRequired);
      return;
    }
    setBusy("save");
    try {
      const patch: { display_name: string; handle?: string } = { display_name: name };
      // 空 handle = 不改短名;发一个空串过去会被云端判成非法。
      if (handle.trim()) patch.handle = handle.trim();
      const { user } = await cloudProfile.update(patch);
      setDisplayName(user.display_name ?? name);
      setHandle(user.handle ?? handle.trim());
      // 缓存清单(见 lib/query-invalidation.ts):viewer 让站头换成新首字母 / 色块 /
      // aria-label,sharesByMe 让「我的分享」和概览换成新作者名,shareList 让公开列表的
      // 作者名一起变;个人页与 viewer 共用同一份缓存,一并刷新。
      await invalidateAfterProfileSave(queryClient);
      // 保存成功是一过性通知:弹一下就走,不在表单上方留一条常驻提示。
      toast.success(copy.saved);
    } catch (failure) {
      if (failure instanceof CloudApiError) {
        if (failure.code === "handle_taken" || failure.code === "handle_reserved") {
          setHandleError(failure.text(locale));
        } else if (failure.code.startsWith("display_name")) {
          setDisplayError(failure.text(locale));
        } else if (failure.code.startsWith("handle")) {
          setHandleError(failure.text(locale));
        } else {
          setError(failure.text(locale));
        }
      } else {
        setError(copy.saveFailed);
      }
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
    // 退出最不能省的就是这一条:不刷 viewer,站头还挂着上一个账号的头像与未读数。
    await invalidateAfterSignOut(queryClient);
    router.push(`/${locale}/login`);
  };

  const previewSeed = displayName.trim() || handle.trim() || currentViewer.handle?.trim() || "mosael";
  const previewName = displayName.trim() || handle.trim() || "?";
  const previewHandle = handle.trim() || currentViewer.handle?.trim() || "";

  return (
    <div className="grid gap-4">
      {!hasHandle && (
        <output className="flex flex-wrap items-start gap-3 rounded-xl border border-primary/30 bg-brand-soft px-4 py-3.5">
          <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-card text-accent">
            <PenLine className="size-4" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="m-0 text-sm font-semibold">{copy.noHandleTitle}</p>
            <p className="mt-1 mb-0 text-[13px] leading-6 text-muted-foreground">{copy.noHandleBody}</p>
          </div>
        </output>
      )}

      {error && (
        <FormAlert id="dashboard-profile-error" title={copy.tabProfile}>
          {error}
        </FormAlert>
      )}

      <Card className="bg-card/60 ring-border">
        <CardContent className="grid gap-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <InitialTile seed={previewSeed} name={previewName} size="lg" />
              <div className="grid min-w-0 gap-0.5">
                <strong className="truncate text-sm font-semibold">{previewName}</strong>
                <span className="truncate font-mono text-xs text-muted-foreground">
                  {previewHandle ? `@${previewHandle}` : copy.noHandleTitle}
                </span>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={busy === "logout"}
              aria-busy={busy === "logout"}
              onClick={() => void signOut()}
            >
              <LogOut className="size-3.5" aria-hidden />
              {busy === "logout" ? copy.signingOut : copy.signOut}
            </Button>
          </div>

          <form className="grid gap-4" onSubmit={save} noValidate>
            <AccountField
              id="dashboard-display-name"
              label={copy.displayName}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              autoComplete="nickname"
              maxLength={40}
              error={displayError}
              className="h-9 rounded-md text-sm"
            />
            <AccountField
              id="dashboard-handle"
              label={copy.handle}
              value={handle}
              onChange={(event) => setHandle(event.target.value)}
              hint={copy.handleHint}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={24}
              error={handleError}
              className="h-9 rounded-md font-mono text-sm"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" size="sm" disabled={busy === "save"} aria-busy={busy === "save"}>
                {busy === "save" ? copy.saving : copy.save}
              </Button>
            </div>
          </form>

          <div className="grid gap-1 border-t border-border pt-4">
            <dl className="m-0 flex min-w-0 flex-wrap items-baseline gap-x-3 text-[13px]">
              <dt className="m-0 font-medium text-muted-foreground">{copy.email}</dt>
              <dd className="m-0 min-w-0 font-mono [overflow-wrap:anywhere]">
                {email ?? (emailFailed ? copy.emailUnavailable : emailUnbound ? copy.emailUnbound : "…")}
              </dd>
            </dl>
            <p className="m-0 text-xs leading-5 text-muted-foreground">{copy.emailHint}</p>
          </div>
        </CardContent>
      </Card>

      <DashboardPassword locale={locale} copy={copy} hasPassword={Boolean(currentViewer.has_password)} />

      {!hasHandle && (
        <div>
          <Button variant="ghost" size="sm" onClick={() => onSelect("overview")}>
            {copy.tabOverview}
          </Button>
        </div>
      )}

      {/* 危险区放在这一块的**最底下**:删号不是日常动作,它属于「个人信息」的最后一步。 */}
      <AccountDangerZone locale={locale} copy={copy} />
    </div>
  );
}
