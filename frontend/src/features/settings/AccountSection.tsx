import React from "react";
import { Camera, Check, Loader2, LogOut } from "lucide-react";
import { toast } from "sonner";

import { customServerHost, userAvatarUrl } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { accountOrigin } from "@/components/layout/accountOrigin";
import { ConfirmDialog } from "@/components/app/modals";
import { SettingsBlock, SettingsField, SettingsForm, SettingsGroup } from "@/components/settings/settings-layout";
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
  //: 用户名(登录名)**不跟着自动保存**:此前三项一起 650ms 防抖,停顿一下就把登录名改成了半截,下次登录用不上
  //: (体检 UM-19)。昵称、签名照旧边打边存;登录名改成显式的「修改登录名」+ 确认。
  const [usernameDraft, setUsernameDraft] = React.useState(user?.username ?? "");
  const [confirmingUsername, setConfirmingUsername] = React.useState(false);
  const [usernamePending, setUsernamePending] = React.useState(false);

  React.useEffect(() => {
    const next = profileFromUser(user);
    setProfile(next);
    lastSavedRef.current = profileKey(next);
    //: 刚打开页面时什么都没改,不说「资料已保存」(体检 UM-27:一进来右上角就是「✓ 资料已保存」);存过一次之后照旧说。
    setSaveState((current) => (current === "idle" ? "idle" : "saved"));
  }, [user?.id, user?.username, user?.display_name, user?.signature]);
  //: 只在登录名真的变了(改成功、或换了账号)时把输入框对回去 —— 昵称自动保存回来时不动正在改的登录名。
  React.useEffect(() => setUsernameDraft(user?.username ?? ""), [user?.username]);

  React.useEffect(() => {
    const next = normalizeProfile(profile);
    const nextKey = profileKey(next);
    if (next.username.length < 2 || next.display_name.length < 1) return;
    if (nextKey === lastSavedRef.current) {
      setSaveState((current) => (current === "saving" ? "saved" : current));
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

  const usernameNext = usernameDraft.trim().toLowerCase();
  const usernameChanged = usernameNext !== (user?.username ?? "");
  const usernameTooShort = usernameChanged && usernameNext.length < 2;
  const changeUsername = async () => {
    setUsernamePending(true);
    try {
      const saved = await updateProfile({ ...normalizeProfile(profile), username: usernameNext });
      toast.success(t("usernameChanged").replace("{name}", saved.username));
    } catch (error) {
      toast.error(errorText(error) || t("profileSaveFailed"));
    } finally {
      setUsernamePending(false);
      setConfirmingUsername(false);
    }
  };

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
      toast.error(t("avatarUpdateFailed"), { description: errorText(error) });
    } finally {
      setAvatarPending(false);
    }
  };

  return (
    <SettingsGroup
      title={t("settingsAccount")}
      // 和账号菜单同一行:这是哪台服务器上的账号、怎么登进来的。此前写死「本地账号,数据都在这台设备上」,
      // 连着团队服务器的人从菜单点「账号设置」进来,看到的是和菜单相反的说法。
      description={accountOrigin(t, customServerHost(), user?.oauth_providers ?? [])}
      actions={
        <Button variant="outline" size="sm" onClick={() => void logout()}>
          <LogOut size={13} /> {t("signOut")}
        </Button>
      }
    >
      <SettingsBlock>
        <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3">
          <IconButton
            unstyled
            type="button"
            className="group/avatar relative inline-flex h-[38px] w-[38px] cursor-pointer items-center justify-center overflow-hidden rounded-xl border-0 bg-accent p-0 font-bold text-accent-foreground shadow-[var(--shadow-panel)]"
            label={t("avatarChange")}
            loading={avatarPending}
            onClick={() => avatarInputRef.current?.click()}
          >
            {avatarSrc ? <img src={avatarSrc} className="h-full w-full object-cover" alt="" /> : initial}
            <span className="absolute inset-0 grid place-items-center bg-[rgb(0_0_0/0.45)] text-white opacity-0 transition-opacity duration-100 group-hover/avatar:opacity-100">
              {avatarPending ? <Loader2 size={13} className="animate-mosael-spin" /> : <Camera size={13} />}
            </span>
          </IconButton>
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
            <div className="flex min-w-0 items-center gap-2">
              <Input
                value={usernameDraft}
                autoComplete="username"
                aria-invalid={usernameTooShort || undefined}
                onChange={(event) => setUsernameDraft(event.target.value)}
              />
              {usernameChanged && (
                <Button
                  type="button"
                  variant="outline"
                  className="shrink-0"
                  data-username-change=""
                  disabled={usernameTooShort}
                  onClick={() => setConfirmingUsername(true)}
                >
                  {t("usernameChange")}
                </Button>
              )}
            </div>
            {usernameTooShort && <small className="text-ui-sm text-destructive">{t("teamUsernameShort")}</small>}
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
          {/* 一小节的标题比下面那几格的名字(16px)重一档,说明和字段说明同一档(14px)—— 此前是 14px 标题配 12px 说明,
              比下面「当前密码」「新密码」还小,读起来层级倒过来了。 */}
          <div className="grid gap-1">
            <strong className="text-ui-lg font-semibold leading-snug">{t("settingsPassword")}</strong>
            <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("settingsPasswordDesc")}</small>
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
              {/* 和上面的密码框同一档(md):设置页填值那一行的字段和按钮同高。 */}
              <Button disabled={!canUpdatePassword} loading={passwordPending} onClick={() => void submitPassword()}>
                {t("updatePassword")}
              </Button>
            </div>
          </SettingsForm>
        </div>
      </SettingsBlock>
      <ConfirmDialog
        open={confirmingUsername}
        title={t("usernameChange")}
        body={t("usernameChangeConfirm").replace("{name}", usernameNext)}
        confirmLabel={t("usernameChange")}
        onCancel={() => setConfirmingUsername(false)}
        pending={usernamePending}
        onConfirm={() => void changeUsername()}
      />
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
