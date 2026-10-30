import React from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  describeCloudFailure,
  changeCloudPassword,
  loadCloudSession,
  loginWithPassword,
  loginWithPhonePassword,
  logoutCloud,
  requestCloudLoginCode,
  requestCloudLoginSmsCode,
  verifyCloudLoginCode,
  verifyCloudLoginSms,
  type CloudSession,
} from "@/api/domains/cloud";
import { cloudKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { FailureCard } from "@/components/failure/FailureCard";
import { Input } from "@/components/ui/input";
import { SettingsBlock, SettingsField, SettingsForm } from "@/components/settings/settings-layout";

/**
 * 设置 → 账户里的「MosaelCloud 账号」:桌面端**自己**登录云端。
 *
 * 维护者说得明白:「桌面端和网站端本来就都可以独立登录」「桌面端也要可以通过邮箱账号密码等
 * 信息登录」。所以这里不是浏览器授权、也不是设备码:两条路都直接打本机后端的
 * `/api/cloud/v1/login*`,由本机后端拿云端会话换一枚设备令牌存下来(加密列,ADR 0088),渲染层只拿得到邮箱。
 *
 * **三条路**:
 * - 邮箱 + 密码,或手机号 + 密码;
 * - 邮箱验证码:先发码,再填 6 位,再验证;
 * - 手机短信验证码:同一个手机号首次验证会自动建 Cloud 账号。
 *
 * 「这个部署接没接 MosaelCloud」在点之前就要知道:读 `/me` 的 503 `cloud_not_configured`
 * 就是这份部署事实。产品默认接官方 Cloud,只有部署管理员显式关掉才会走到这里(ADR 0088 §0):把按钮关掉,
 * 说清该找谁 —— 不给一颗点了只会错的按钮,也不教用户去设环境变量(那是管理员的事,写在 docs/CLOUD_ACCOUNTS.md)。
 */
export function CloudAccountSection() {
  const t = useI18n();
  const queryClient = useQueryClient();
  const [session, setSession] = React.useState<CloudSession | null>(null);
  const [loading, setLoading] = React.useState(true);
  //: 这个部署没接 Cloud。配置存的是环境变量,不重启不会变 —— 一旦知道就不再重置。
  const [notConfigured, setNotConfigured] = React.useState(false);
  const [failure, setFailure] = React.useState("");
  const [mode, setMode] = React.useState<"password" | "code" | "sms">("password");
  const [email, setEmail] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [codeSent, setCodeSent] = React.useState(false);
  const [cooldown, setCooldown] = React.useState(0);
  const [pending, setPending] = React.useState<"" | "login" | "code" | "verify" | "logout" | "password">("");
  const [currentPassword, setCurrentPassword] = React.useState("");
  const [newPassword, setNewPassword] = React.useState("");
  const [confirmPassword, setConfirmPassword] = React.useState("");
  const [passwordFailure, setPasswordFailure] = React.useState("");
  const [passwordSaved, setPasswordSaved] = React.useState(false);
  const hintId = React.useId();
  const howId = React.useId();

  React.useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  React.useEffect(() => {
    let alive = true;
    void loadCloudSession()
      .then((found) => {
        if (!alive) return;
        setSession(found);
        setFailure("");
      })
      .catch((error: unknown) => {
        if (!alive) return;
        const next = describeCloudFailure(error);
        if (next.notConfigured) setNotConfigured(true);
        else setFailure(next.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const noteFailure = (error: unknown) => {
    const next = describeCloudFailure(error);
    if (next.notConfigured) setNotConfigured(true);
    else setFailure(next.message);
  };

  const signIn = async () => {
    setFailure("");
    setPending(mode === "password" ? "login" : "verify");
    try {
      const found =
        mode === "password"
          ? email.includes("@")
            ? await loginWithPassword(email.trim(), password)
            : await loginWithPhonePassword(email.trim(), password)
          : mode === "code"
            ? await verifyCloudLoginCode(email.trim(), code.trim())
            : await verifyCloudLoginSms(phone.trim(), code.trim());
      setSession(found);
      //: 供应商列表顶上的「Mosael Cloud」那一行读的是同一份登录。
      void queryClient.invalidateQueries({ queryKey: cloudKeys.session() });
      setEmail("");
      setPhone("");
      setPassword("");
      setCode("");
      setCodeSent(false);
    } catch (error) {
      noteFailure(error);
    } finally {
      setPending("");
    }
  };

  const sendCode = async () => {
    setFailure("");
    setPending("code");
    try {
      if (mode === "sms") await requestCloudLoginSmsCode(phone.trim());
      else await requestCloudLoginCode(email.trim());
      setCodeSent(true);
      setCooldown(60);
    } catch (error) {
      noteFailure(error);
    } finally {
      setPending("");
    }
  };

  const savePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setPasswordFailure("");
    setPasswordSaved(false);
    if (newPassword.length < 8) {
      setPasswordFailure(t("passwordTooShort"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordFailure(t("passwordMismatch"));
      return;
    }
    setPending("password");
    try {
      const updated = await changeCloudPassword(session?.has_password ? currentPassword : "", newPassword);
      setSession(updated);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordSaved(true);
      void queryClient.invalidateQueries({ queryKey: cloudKeys.session() });
    } catch (error) {
      noteFailure(error);
      setPasswordFailure(describeCloudFailure(error).message);
    } finally {
      setPending("");
    }
  };

  const signOut = async () => {
    setFailure("");
    setPending("logout");
    try {
      await logoutCloud();
      setSession(null);
      void queryClient.invalidateQueries({ queryKey: cloudKeys.session() });
    } catch (error) {
      noteFailure(error);
    } finally {
      setPending("");
    }
  };

  const switchMode = (next: "password" | "code" | "sms") => {
    setMode(next);
    setFailure("");
    setCode("");
    setCodeSent(false);
  };

  const identifier = mode === "sms" ? phone.trim() : email.trim();
  const canSubmit =
    !pending &&
    identifier.length > 0 &&
    (mode === "password" ? password.length > 0 : codeSent && code.trim().length === 6);
  const canSend = !pending && identifier.length > 0 && cooldown === 0;

  return (
    <SettingsBlock>
      <div data-cloud-account="" className="grid gap-3">
        <div className="grid gap-1">
          <strong className="text-ui-lg font-semibold leading-snug">{t("settingsCloudAccount")}</strong>
          <small className="text-ui-sm leading-[1.5] text-muted-foreground">
            {t("settingsCloudAccountDesc")}
          </small>
        </div>

        {loading ? (
          <small className="text-ui-sm text-muted-foreground">{t("settingsCloudChecking")}</small>
        ) : notConfigured ? (
          <div className="grid gap-2">
            <small id={hintId} className="text-ui-sm leading-[1.5] text-muted-foreground">
              {t("settingsCloudNotConfigured")}
            </small>
            <small id={howId} className="text-ui-sm leading-[1.5] text-muted-foreground">
              {t("settingsCloudNotConfiguredHow")}
            </small>
            {/* 保留入口但关掉它:藏起来,用户就不知道这台部署有这项能力。禁用要有可读的原因。 */}
            <div className="flex justify-end">
              <Button disabled aria-describedby={`${hintId} ${howId}`}>
                {t("settingsCloudSignIn")}
              </Button>
            </div>
          </div>
        ) : session ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="grid gap-0.5">
                <strong className="text-sm font-[650]">{session.email}</strong>
                <small className="text-ui-sm text-muted-foreground">{t("settingsCloudSignedIn")}</small>
              </div>
              <Button variant="outline" onClick={() => void signOut()} loading={pending === "logout"} disabled={Boolean(pending)}>
                {t("settingsCloudSignOut")}
              </Button>
            </div>
            <div className="grid gap-3 border-t border-border pt-4">
                <div className="grid gap-1">
                  <strong className="text-ui-md font-semibold">
                    {session.has_password ? t("settingsCloudChangePassword") : t("settingsCloudSetPassword")}
                  </strong>
                  <small className="text-ui-sm leading-[1.5] text-muted-foreground">
                    {t("settingsCloudPasswordHint")}
                  </small>
                </div>
                <form onSubmit={(event) => void savePassword(event)}>
                  <SettingsForm>
                    {session.has_password && (
                      <SettingsField label={t("currentPassword")}>
                        <Input
                          type="password"
                          autoComplete="current-password"
                          value={currentPassword}
                          onChange={(event) => setCurrentPassword(event.target.value)}
                        />
                      </SettingsField>
                    )}
                    <SettingsField label={t("newPassword")}>
                      <Input
                        type="password"
                        autoComplete="new-password"
                        value={newPassword}
                        onChange={(event) => setNewPassword(event.target.value)}
                      />
                    </SettingsField>
                    <SettingsField label={t("confirmPassword")}>
                      <Input
                        type="password"
                        autoComplete="new-password"
                        value={confirmPassword}
                        onChange={(event) => setConfirmPassword(event.target.value)}
                      />
                    </SettingsField>
                    <div className="flex items-center justify-between gap-3">
                      <small role="alert" className="text-ui-sm leading-[1.5] text-destructive">
                        {passwordFailure}
                      </small>
                      <Button
                        type="submit"
                        loading={pending === "password"}
                        disabled={pending === "password" || !newPassword || !confirmPassword}
                      >
                        {t("updatePassword")}
                      </Button>
                    </div>
                    {passwordSaved && (
                      <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("settingsCloudPasswordUpdated")}</small>
                    )}
                  </SettingsForm>
                </form>
              </div>
          </>
        ) : (
          <form
            data-cloud-login-form=""
            onSubmit={(event) => {
              event.preventDefault();
              if (canSubmit) void signIn();
            }}
          >
            <SettingsForm>
              {mode === "sms" ? (
                <SettingsField label={t("settingsCloudPhone")}>
                  <Input
                    type="tel"
                    autoComplete="tel"
                    value={phone}
                    onChange={(event) => setPhone(event.target.value)}
                  />
                </SettingsField>
              ) : (
                <SettingsField label={mode === "password" ? t("settingsCloudIdentifier") : t("settingsCloudEmail")}>
                  <Input
                    type={mode === "password" ? "text" : "email"}
                    inputMode={mode === "password" ? "text" : "email"}
                    autoComplete={mode === "password" ? "username" : "email"}
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </SettingsField>
              )}
              {mode === "password" ? (
                <SettingsField label={t("settingsCloudPassword")}>
                  <Input
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </SettingsField>
              ) : codeSent ? (
                <SettingsField label={mode === "sms" ? t("settingsCloudSmsCode") : t("settingsCloudCode")}>
                  <Input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    value={code}
                    onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
                  />
                </SettingsField>
              ) : null}
              {/* 切换登录方式 = **和主动作并排的次要动作**,所以走 outline(和输入框同一种描边、同高)。
                  以前是 ghost:没有轮廓、只有悬停底色,左侧像一行浮着的字,和右边的实心按钮凑不成一对
                  (维护者:「现在怪怪的 好像多出间距一样」)。 */}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  {mode !== "password" && (
                    <Button variant="outline" onClick={() => switchMode("password")}>
                      {t("settingsCloudUsePassword")}
                    </Button>
                  )}
                  {mode !== "code" && (
                    <Button variant="outline" onClick={() => switchMode("code")}>
                      {t("settingsCloudUseCode")}
                    </Button>
                  )}
                  {mode !== "sms" && (
                    <Button variant="outline" onClick={() => switchMode("sms")}>
                      {t("settingsCloudUseSms")}
                    </Button>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {mode !== "password" && (
                    <Button
                      variant="outline"
                      onClick={() => void sendCode()}
                      loading={pending === "code"}
                      disabled={!canSend}
                    >
                      {cooldown > 0
                        ? t("settingsCloudResendIn").replace("{seconds}", String(cooldown))
                        : t("settingsCloudSendCode")}
                    </Button>
                  )}
                  {(mode === "password" || codeSent) && (
                    <Button
                      type="submit"
                      loading={pending === "login" || pending === "verify"}
                      disabled={!canSubmit}
                    >
                      {mode === "password" ? t("settingsCloudSignIn") : t("settingsCloudVerify")}
                    </Button>
                  )}
                </div>
              </div>
              {mode !== "password" && codeSent && (
                <small className="text-ui-sm leading-[1.5] text-muted-foreground">
                  {mode === "sms" ? t("settingsCloudSmsSent") : t("settingsCloudCodeSent")}
                </small>
              )}
            </SettingsForm>
          </form>
        )}

        {failure && (
          <FailureCard
            size="inline"
            status="failed"
            title={t("settingsCloudSignInFailed")}
            summary={failure}
            copyText={failure}
          />
        )}
      </div>
    </SettingsBlock>
  );
}
