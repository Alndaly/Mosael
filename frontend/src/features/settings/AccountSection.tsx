import React from "react";
import { Camera, Check, Loader2, LogOut } from "lucide-react";
import { toast } from "sonner";

import { userAvatarUrl } from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SettingsBlock, SettingsField, SettingsForm, SettingsGroup } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

export function AccountSection() {
  const t = useI18n();
  const { user, updateProfile, changePassword, updateAvatar, logout } = useAuth();
  const [profile, setProfile] = React.useState(() => profileFromUser(user));
  // idle:还没改过任何东西 —— 这时说「资料已保存」是把结果当状态,第一眼就是误导。
  const [saveState, setSaveState] = React.useState<"idle" | "saved" | "saving" | "error">("idle");
  const [passwords, setPasswords] = React.useState({ current: "", next: "", confirm: "" });
  const [passwordPending, setPasswordPending] = React.useState(false);
  const lastSavedRef = React.useRef(profileKey(profile));

  React.useEffect(() => {
    const next = profileFromUser(user);
    setProfile(next);
    lastSavedRef.current = profileKey(next);
    setSaveState("saved");
  }, [user?.id, user?.username, user?.display_name, user?.signature]);

  React.useEffect(() => {
    const next = normalizeProfile(profile);
    const nextKey = profileKey(next);
    if (next.username.length < 2 || next.display_name.length < 1) return;
    if (nextKey === lastSavedRef.current) {
      setSaveState("saved");
      return;
    }
    setSaveState("saving");
    const timer = window.setTimeout(async () => {
      try {
        const saved = await updateProfile(next);
        lastSavedRef.current = profileKey(profileFromUser(saved));
        setSaveState("saved");
      } catch (error) {
        setSaveState("error");
        toast.error((error as Error).message || t("profileSaveFailed"));
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [profile, t, updateProfile]);

  const canUpdatePassword =
    passwords.current.length >= 4 &&
    passwords.next.length >= 4 &&
    passwords.next === passwords.confirm &&
    !passwordPending;

  const submitPassword = async () => {
    if (passwords.next !== passwords.confirm) {
      toast.error(t("passwordMismatch"));
      return;
    }
    if (passwords.next.length < 4) {
      toast.error(t("passwordTooShort"));
      return;
    }
    setPasswordPending(true);
    try {
      await changePassword(passwords.current, passwords.next);
      setPasswords({ current: "", next: "", confirm: "" });
      toast.success(t("passwordUpdated"));
    } catch (error) {
      toast.error((error as Error).message || t("passwordUpdateFailed"));
    } finally {
      setPasswordPending(false);
    }
  };

  const displayName = profile.display_name || profile.username || "M";
  const initial = displayName.slice(0, 1).toUpperCase();
  const avatarSrc = user?.avatar_key && user.id ? userAvatarUrl(user.id, user.avatar_key) : "";
  const avatarInputRef = React.useRef<HTMLInputElement | null>(null);
  const [avatarPending, setAvatarPending] = React.useState(false);
  const pickAvatar = async (file: File) => {
    setAvatarPending(true);
    try {
      await updateAvatar(file);
      toast.success(t("avatarUpdated"));
    } catch (error) {
      toast.error(t("avatarUpdateFailed"), { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setAvatarPending(false);
    }
  };

  return (
    <SettingsGroup
      title={t("settingsAccount")}
      description={t("settingsAccountDesc")}
      actions={
        <Button variant="outline" size="sm" onClick={() => void logout()}>
          <LogOut size={13} /> {t("signOut")}
        </Button>
      }
    >
      <SettingsBlock>
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3">
          <button
            type="button"
            className="group/avatar relative inline-flex h-[38px] w-[38px] cursor-pointer items-center justify-center overflow-hidden rounded-xl border-0 bg-accent p-0 font-bold text-accent-foreground shadow-[var(--shadow-panel)]"
            title={t("avatarChange")}
            aria-label={t("avatarChange")}
            disabled={avatarPending}
            onClick={() => avatarInputRef.current?.click()}
          >
            {avatarSrc ? <img src={avatarSrc} className="h-full w-full object-cover" alt="" /> : initial}
            <span className="absolute inset-0 grid place-items-center bg-[rgb(0_0_0/0.45)] text-white opacity-0 transition-opacity duration-100 group-hover/avatar:opacity-100">
              {avatarPending ? <Loader2 size={13} className="animate-mosael-spin" /> : <Camera size={13} />}
            </span>
          </button>
          <input
            ref={avatarInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void pickAvatar(file);
            }}
          />
          <div className="[&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:text-sm [&_strong]:font-[650]">
            <strong>{displayName}</strong>
            <small>@{profile.username || "account"}</small>
          </div>
          <span
            className={cn(
              "inline-flex items-center gap-[5px] whitespace-nowrap text-xs text-muted-foreground",
              saveState === "saved" && "text-success",
              saveState === "error" && "text-destructive",
            )}
            aria-live="polite"
          >
            {saveState === "idle" ? null : saveState === "saving" ? (
              <>
                <Loader2 size={12} className="animate-mosael-spin" /> {t("profileSaving")}
              </>
            ) : saveState === "error" ? (
              t("profileSaveFailed")
            ) : (
              <>
                <Check size={12} /> {t("profileSaved")}
              </>
            )}
          </span>
        </div>
      </SettingsBlock>
      <SettingsBlock>
        <SettingsForm>
          <SettingsField label={t("settingsUsername")} description={t("settingsUsernameDesc")}>
            <Input
              value={profile.username}
              autoComplete="username"
              onChange={(event) => setProfile((current) => ({ ...current, username: event.target.value }))}
            />
          </SettingsField>
          <SettingsField label={t("displayName")} description={t("displayNameDesc")}>
            <Input
              value={profile.display_name}
              autoComplete="name"
              onChange={(event) => setProfile((current) => ({ ...current, display_name: event.target.value }))}
            />
          </SettingsField>
          <SettingsField label={t("signature")} description={t("signatureDesc")}>
            <Textarea
              className="resize-y"
              rows={3}
              maxLength={500}
              value={profile.signature}
              placeholder={t("signaturePlaceholder")}
              onChange={(event) => setProfile((current) => ({ ...current, signature: event.target.value }))}
            />
          </SettingsField>
        </SettingsForm>
      </SettingsBlock>
      <SettingsBlock>
        <div className="grid gap-3">
          <div className="[&_small]:text-xs [&_small]:leading-[1.45] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:text-sm [&_strong]:font-[650]">
            <strong>{t("settingsPassword")}</strong>
            <small>{t("settingsPasswordDesc")}</small>
          </div>
          <SettingsForm>
            {/* 当前密码是这次变更的前提，不是两个新值中的一个；单独成行后，阅读顺序与验证逻辑一致。 */}
            <SettingsField label={t("currentPassword")}>
              <Input
                type="password"
                value={passwords.current}
                autoComplete="current-password"
                onChange={(event) => setPasswords((current) => ({ ...current, current: event.target.value }))}
              />
            </SettingsField>
            <div data-slot="password-pair" className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1">
              <SettingsField label={t("newPassword")}>
                <Input
                  type="password"
                  value={passwords.next}
                  autoComplete="new-password"
                  onChange={(event) => setPasswords((current) => ({ ...current, next: event.target.value }))}
                />
              </SettingsField>
              <SettingsField label={t("confirmPassword")}>
                <Input
                  type="password"
                  value={passwords.confirm}
                  autoComplete="new-password"
                  onChange={(event) => setPasswords((current) => ({ ...current, confirm: event.target.value }))}
                />
              </SettingsField>
            </div>
            <div className="flex items-end justify-end">
              <Button size="sm" disabled={!canUpdatePassword} onClick={() => void submitPassword()}>
                {passwordPending ? <Loader2 size={13} className="animate-mosael-spin" /> : null} {t("updatePassword")}
              </Button>
            </div>
          </SettingsForm>
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}

function profileFromUser(user: ReturnType<typeof useAuth>["user"]) {
  return {
    username: user?.username ?? "",
    display_name: user?.display_name || user?.username || "",
    signature: user?.signature ?? "",
  };
}

function normalizeProfile(profile: { username: string; display_name: string; signature: string }) {
  const username = profile.username.trim().toLowerCase();
  return {
    username,
    display_name: profile.display_name.trim() || username,
    signature: profile.signature.trim(),
  };
}

function profileKey(profile: { username: string; display_name: string; signature: string }) {
  return `${profile.username}\n${profile.display_name}\n${profile.signature}`;
}

/** 开机自启(仅桌面端渲染,且开发模式下主进程不暴露——那时 execPath 是裸 Electron)。
 *  和「关窗收进托盘」是一对:后者让应用关窗后还活着,前者让它开机就活着。定时任务依赖
 *  后端进程存活(后端是主进程 spawn 的子进程),两者缺一,到点就不会触发。 */
