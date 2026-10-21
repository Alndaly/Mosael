import React from "react";

import {
  describeCloudFailure,
  loadCloudSession,
  loginWithPassword,
  logoutCloud,
  requestCloudLoginCode,
  verifyCloudLoginCode,
  type CloudSession,
} from "@/api/domains/cloud";
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
 * `/api/cloud/v1/login*`,由本机后端把云端的会话 cookie 存下来(加密列),渲染层只拿得到邮箱。
 *
 * **两条路**:
 * - 邮箱 + 密码;
 * - 邮箱验证码:先发码,再填 6 位,再验证。
 *
 * 「这个部署接没接 MosaelCloud」在点之前就要知道:读 `/me` 的 503 `cloud_not_configured`
 * 就是这份部署事实。没接就把按钮关掉,并说清要设 `MOSAEL_CLOUD_URL` —— 不给一颗点了只会错的按钮。
 */
export function CloudAccountSection() {
  const t = useI18n();
  const [session, setSession] = React.useState<CloudSession | null>(null);
  const [loading, setLoading] = React.useState(true);
  //: 这个部署没接 Cloud。配置存的是环境变量,不重启不会变 —— 一旦知道就不再重置。
  const [notConfigured, setNotConfigured] = React.useState(false);
  const [failure, setFailure] = React.useState("");
  const [mode, setMode] = React.useState<"password" | "code">("password");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [codeSent, setCodeSent] = React.useState(false);
  const [pending, setPending] = React.useState<"" | "login" | "code" | "verify" | "logout">("");
  const hintId = React.useId();
  const howId = React.useId();

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
          ? await loginWithPassword(email.trim(), password)
          : await verifyCloudLoginCode(email.trim(), code.trim());
      setSession(found);
      setEmail("");
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
      await requestCloudLoginCode(email.trim());
      setCodeSent(true);
    } catch (error) {
      noteFailure(error);
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
    } catch (error) {
      noteFailure(error);
    } finally {
      setPending("");
    }
  };

  const useCode = () => {
    setMode((current) => (current === "password" ? "code" : "password"));
    setFailure("");
    setCode("");
    setCodeSent(false);
  };

  const canSubmit =
    !pending &&
    email.trim().length > 0 &&
    (mode === "password" ? password.length > 0 : codeSent && code.trim().length === 6);

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
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="grid gap-0.5">
              <strong className="text-sm font-[650]">{session.email}</strong>
              <small className="text-ui-sm text-muted-foreground">{t("settingsCloudSignedIn")}</small>
            </div>
            <Button variant="outline" onClick={() => void signOut()} loading={pending === "logout"} disabled={Boolean(pending)}>
              {t("settingsCloudSignOut")}
            </Button>
          </div>
        ) : (
          <form
            data-cloud-login-form=""
            onSubmit={(event) => {
              event.preventDefault();
              if (canSubmit) void signIn();
            }}
          >
            <SettingsForm>
              <SettingsField label={t("settingsCloudEmail")}>
                <Input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </SettingsField>
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
                <SettingsField label={t("settingsCloudCode")}>
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
                <Button variant="outline" onClick={useCode}>
                  {mode === "password" ? t("settingsCloudUseCode") : t("settingsCloudUsePassword")}
                </Button>
                <div className="flex items-center gap-2">
                  {mode === "code" && !codeSent && (
                    <Button
                      onClick={() => void sendCode()}
                      loading={pending === "code"}
                      disabled={!email.trim() || Boolean(pending)}
                    >
                      {t("settingsCloudSendCode")}
                    </Button>
                  )}
                  {(mode === "password" || codeSent) && (
                    <Button
                      type="submit"
                      loading={pending === "login" || pending === "verify"}
                      disabled={!canSubmit}
                    >
                      {mode === "code" ? t("settingsCloudVerify") : t("settingsCloudSignIn")}
                    </Button>
                  )}
                </div>
              </div>
              {mode === "code" && codeSent && (
                <small className="text-ui-sm leading-[1.5] text-muted-foreground">{t("settingsCloudCodeSent")}</small>
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
