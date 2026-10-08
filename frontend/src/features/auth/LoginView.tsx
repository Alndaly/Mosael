import React from "react";
import { CircleAlert, Languages } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useQuery } from "@tanstack/react-query";

import { ApiError, ApiOfflineError, oauthConfirm, oauthPending, oauthProviders, oauthStart, previewInviteLink } from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import loginHeroUrl from "@/assets/login-hero.jpg";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Hint } from "@/components/ui/tooltip";
import { ServerPicker } from "@/components/app/ServerPicker";
import { LegalDialog, type LegalDoc } from "@/features/auth/legal";
import type { MessageKey } from "@/app/messages";
import { docsUrl } from "@/lib/deepLink";
import { clearPendingInvite, codeFromInviteText, usePendingInvite } from "@/lib/inviteLinks";

type LoginValues = { username: string; displayName: string; password: string; confirm: string; inviteCode: string };

/** 把登录/注册的失败说准 —— 连不上、后端出错都不是「账号密码错」。
 *  按 transport 抛出的错误类型和状态码判断:到这里时 message 已经是翻好的人话,不再是响应体,
 *  从 message 里猜(此前的做法)一条分支都走不到。 */
function friendlyAuthError(err: unknown, mode: "login" | "register", t: (key: MessageKey) => string): string {
  if (err instanceof ApiOfflineError) return t("loginNetworkError");
  if (err instanceof ApiError) {
    if (err.status >= 500) return t("loginServerError");
    if (mode === "register" && err.status === 409) return t("usernameTaken");
    //: 注册已转邀请制、邀请码无效:后端给的就是按界面语言翻好的原因,照说。
    if (mode === "register" && err.status === 403) return err.message;
    if (err.status === 422) return t("authInvalidFields");
  }
  return mode === "login" ? t("loginFailed") : t("registerFailed");
}

export function LoginView() {
  const t = useI18n();
  const { locale, setLocale } = usePreferences();
  const { hasUsers, openRegistration, login, register } = useAuth();
  const [mode, setMode] = React.useState<"login" | "register">(hasUsers ? "login" : "register");
  const [legalDoc, setLegalDoc] = React.useState<LegalDoc | null>(null);
  const [forgotOpen, setForgotOpen] = React.useState(false);
  //: 打开的是一张邀请链接(ADR 0054):登录页说清是谁邀请进哪里,注册时带上它 —— 不用再手抄一个码。
  const invite = usePendingInvite();
  const preview = useQuery({
    queryKey: ["invite-link-preview", invite],
    queryFn: () => previewInviteLink(invite!),
    enabled: Boolean(invite),
    retry: false,
  });
  const inviteUsable = preview.data?.state === "open";

  const schema = React.useMemo(() => {
    const base = z.object({
      //: 和后端同一个下限(AuthCredentials.username ≥ 2):此前填 1 个字,后端 422,界面说「无法创建账户,请稍后重试」,
      //: 重试一百次也不行(体检 UM-27)。
      username: z.string().trim().min(1, t("fieldRequired")).min(2, t("teamUsernameShort")),
      displayName: z.string(),
      inviteCode: z.string(),
      password: z.string().min(4, t("passwordTooShort")),
      confirm: z.string(),
    });
    return mode === "register"
      ? base
          .refine((data) => data.displayName.trim().length > 0, { message: t("fieldRequired"), path: ["displayName"] })
          .refine((data) => data.password === data.confirm, { message: t("passwordMismatch"), path: ["confirm"] })
      : base;
  }, [mode, t]);

  const form = useForm<LoginValues>({
    resolver: zodResolver(schema),
    defaultValues: { username: "", displayName: "", password: "", confirm: "", inviteCode: "" },
    mode: "onSubmit",
  });

  React.useEffect(() => {
    setMode(hasUsers ? "login" : "register");
  }, [hasUsers]);

  const switchMode = () => {
    setMode((current) => (current === "login" ? "register" : "login"));
    form.reset();
  };

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      if (mode === "login") await login(values.username, values.password);
      else
        await register(
          values.username,
          values.password,
          values.displayName,
          //: 带着邀请链接来的就用它;手填的框认得出粘进来的整条链接(网页地址或深链)。
          inviteUsable && invite ? invite : codeFromInviteText(values.inviteCode),
        );
      //: 不带工作区的邀请只管进部署:注册完就用掉了,不留给登录之后那一步(它会说「这是注册用的」)。
      if (mode === "register" && inviteUsable && !preview.data?.workspace_name) clearPendingInvite();
    } catch (err) {
      form.setError("root", { message: friendlyAuthError(err, mode, t) });
    }
  });

  return (
    <div className="relative grid min-h-screen bg-background lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      {/* 桌面端无边框窗:登录/注册页不挂 AppShell,若不自带拖拽条,整个窗口在登录前完全
          拖不动(只能靠系统快捷键移动)。这条透明带盖住顶栏高度,层级压在语言按钮之下,
          按钮自身标 no-drag 保证可点。 */}
      <div
        className="fixed inset-x-0 top-0 z-[5] hidden h-11 [.is-desktop_&]:block [-webkit-app-region:drag]"
        aria-hidden
      />
      <LoginHero />

      {/* 未登录也能换语言:与壳层同一偏好存储,登录后无缝延续。 */}
      {/* 按钮上写的是要换成的语言名;悬停说清这一下是「切换到它」。 */}
      <Hint label={locale === "zh-CN" ? t("languageSwitchToEn") : t("languageSwitchToZh")} side="bottom">
        <Button
          variant="ghost"
          size="sm"
          className="absolute right-4 top-4 z-10 gap-1.5 text-muted-foreground [-webkit-app-region:no-drag]"
          onClick={() => setLocale(locale === "zh-CN" ? "en-US" : "zh-CN")}
          aria-label={locale === "zh-CN" ? t("languageSwitchToEn") : t("languageSwitchToZh")}
        >
          <Languages size={14} /> {locale === "zh-CN" ? t("languageEn") : t("languageZh")}
        </Button>
      </Hint>

      <main className="grid min-h-screen grid-rows-[minmax(0,1fr)_auto] justify-items-center overflow-y-auto px-6 py-8">
        <div className="grid w-[min(400px,100%)] content-center gap-8 py-12">
          <div className="grid gap-2.5 [&_h1]:m-0 [&_h1]:text-3xl [&_h1]:font-semibold [&_h1]:leading-[1.15] [&_h1]:tracking-[-0.02em] [&_h1]:text-foreground [&_p]:m-0 [&_p]:text-ui-md [&_p]:leading-normal [&_p]:text-muted-foreground">
            <span className="mb-8 text-3xl font-semibold tracking-tighter">Mosael</span>
            {/* 空库 = 这个部署还没有管理员。直说他正在创建什么,而不是一句泛泛的"创建账户"。 */}
            <h1>{mode === "login" ? t("loginWelcomeBack") : hasUsers ? t("loginCreateTitle") : t("bootstrapTitle")}</h1>
            <p>
              {mode === "login" ? t("loginSubtitle") : hasUsers ? t("registerSubtitle") : t("bootstrapSubtitle")}
            </p>
          </div>

          {invite && (preview.isSuccess || preview.isError) && (
            <InviteNotice
              preview={preview.data ?? null}
              openRegistration={openRegistration}
              onDismiss={clearPendingInvite}
            />
          )}

          <Form {...form}>
            {/* 组间 16px 明显大于组内标签的 8px,字段归属一眼可辨。 */}
            <form className="grid gap-5 [&_input]:h-12" onSubmit={onSubmit} noValidate>
              {form.formState.errors.root && (
                <Alert variant="destructive">
                  <CircleAlert size={14} />
                  <AlertDescription>{form.formState.errors.root.message}</AlertDescription>
                </Alert>
              )}
              <FormField
                control={form.control}
                name="username"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("username")}</FormLabel>
                    <FormControl>
                      <Input autoFocus autoComplete="username" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {mode === "register" && (
                <FormField
                  control={form.control}
                  name="displayName"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t("displayName")}</FormLabel>
                      <FormControl>
                        <Input autoComplete="name" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              {/* 邀请码只在**关掉了自助注册**的部署上出现。开放的部署摆一个永远不用填的框,
                  等于让每个新人先去问一句"这个要填吗";空库时更没有任何人可以给他发码。 */}
              {mode === "register" && hasUsers && !openRegistration && !inviteUsable && (
                <FormField
                  control={form.control}
                  name="inviteCode"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t("inviteCode")}</FormLabel>
                      <FormControl>
                        <Input autoComplete="off" placeholder={t("inviteCodePlaceholder")} {...field} />
                      </FormControl>
                      <FormDescription>{t("inviteCodeHint")}</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("password")}</FormLabel>
                    <FormControl>
                      <Input
                        type="password"
                        autoComplete={mode === "login" ? "current-password" : "new-password"}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {mode === "register" && (
                <FormField
                  control={form.control}
                  name="confirm"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t("confirmPassword")}</FormLabel>
                      <FormControl>
                        <Input type="password" autoComplete="new-password" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              <Button type="submit" className="mt-2 h-12" loading={form.formState.isSubmitting}>
                {mode === "login" ? t("signIn") : t("createAccount")}
              </Button>
              {mode === "register" && (
                <p className="m-0 text-ui-xs leading-[1.6] text-muted-foreground [&_button]:cursor-pointer [&_button]:border-0 [&_button]:bg-transparent [&_button]:p-0 [&_button]:text-[length:inherit] [&_button]:text-foreground [&_button]:underline [&_button]:underline-offset-2 [&_button:hover]:text-primary">
                  {t("authConsentPrefix")}
                  <button type="button" onClick={() => setLegalDoc("terms")}>{t("legalTerms")}</button>
                  {t("authConsentAnd")}
                  <button type="button" onClick={() => setLegalDoc("privacy")}>{t("legalPrivacy")}</button>
                  {t("authConsentSuffix")}
                </p>
              )}
            </form>
          </Form>

          <div className="-mt-2 flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              className="cursor-pointer border-0 bg-transparent p-0.5 text-ui-sm text-muted-foreground hover:text-accent-foreground hover:underline"
              onClick={switchMode}
            >
              {mode === "login" ? t("switchToRegister") : t("switchToLogin")}
            </button>
            {/* 忘了密码此前没有任何下一步(体检 UM-04):说清找谁重置,唯一的管理员自己用命令行。 */}
            {mode === "login" && hasUsers && (
              <button
                type="button"
                aria-expanded={forgotOpen}
                className="cursor-pointer border-0 bg-transparent p-0.5 text-ui-sm text-muted-foreground hover:text-accent-foreground hover:underline"
                onClick={() => setForgotOpen((open) => !open)}
              >
                {t("loginForgot")}
              </button>
            )}
          </div>
          {mode === "login" && forgotOpen && (
            <p data-login-forgot="" className="-mt-4 m-0 rounded-md bg-secondary px-3 py-2.5 text-ui-xs leading-[1.6] text-muted-foreground">
              {t("loginForgotBody")}{" "}
              <a className="text-primary underline underline-offset-2" href={docsUrl("guides/admin", locale)} target="_blank" rel="noreferrer noopener">
                {t("loginForgotDocs")}
              </a>
            </p>
          )}

          <OAuthButtons />
        </div>
        <LegalDialog doc={legalDoc} onClose={() => setLegalDoc(null)} />

        {/* 服务器入口必须在登录前:选定本地/团队后端,再对它认证。 */}
        <div className="flex w-[min(400px,100%)] justify-center border-t border-border pt-4">
          <ServerPicker />
        </div>
      </main>
    </div>
  );
}

/**
 * 带着一张邀请链接来的(ADR 0054):谁邀请你进哪个工作区、什么角色;还没账号能不能凭它注册。用不了的(用过、撤回、过期、
 * 找不到)说是哪件事,给一个「不用这张」把它放下 —— 登录照常。
 */
function InviteNotice({
  preview,
  openRegistration,
  onDismiss,
}: {
  preview: { workspace_name: string; inviter_name: string; role: string; state: string; allows_signup: boolean } | null;
  openRegistration: boolean;
  onDismiss: () => void;
}) {
  const t = useI18n();
  const usable = preview?.state === "open";
  const problems: Record<string, MessageKey> = {
    used: "loginInviteUsed",
    revoked: "loginInviteRevoked",
    expired: "loginInviteExpired",
  };
  const body = !preview
    ? t("loginInviteUnknown")
    : !usable
      ? t(problems[preview.state] ?? "loginInviteUnknown")
      : preview.workspace_name
        ? t("loginInviteTitle")
            .replace("{inviter}", preview.inviter_name)
            .replace("{workspace}", preview.workspace_name)
            .replace("{role}", t(`role_${preview.role}` as never))
        : t("loginInviteDeployment").replace("{inviter}", preview.inviter_name);
  const next = !usable
    ? null
    : preview?.allows_signup || openRegistration
      ? t("loginInviteSignupOk")
      : t("loginInviteMembersOnly");
  return (
    <div
      role="status"
      data-login-invite={usable ? "open" : "unusable"}
      className="-mt-2 grid gap-1.5 rounded-md border border-border bg-secondary px-3.5 py-3 text-ui-sm leading-[1.6]"
    >
      <span className="font-[550] text-foreground">{body}</span>
      {next && <span className="text-ui-xs text-muted-foreground">{next}</span>}
      {!usable && (
        <Button variant="inline" className="justify-self-start" onClick={onDismiss}>
          {t("loginInviteDismiss")}
        </Button>
      )}
    </div>
  );
}

/** 第三方登录(Google / Apple):后端只报已配置的提供方,一个没配就整块不渲染。
 *  流程:start 拿授权 URL(系统浏览器打开)+ pending_id → 每 2s 轮询 → 浏览器那边成了,轮询说「等确认」,
 *  这里换成一个确认码输入框 → 填回调页上显示的码 → 对上了拿到票,adoptAuth 落座。
 *  **令牌只交给填对码的这一边**:此前轮询直接交票,谁开的这次登录谁就能取走 —— 转一条授权链接给别人,
 *  对方登录完,会话落进发起人手里(SEC-11)。file://(Electron)与 5173 开发页都无需注册自己为回调目标。 */
function OAuthButtons() {
  const t = useI18n();
  const { adoptAuth } = useAuth();
  //: 点了哪一家:从去拿授权地址起,到这边取到票(或出错、取消)为止 —— 那一颗转圈,另一颗点不了
  const [pending, setPending] = React.useState<{ provider: string; id: string | null } | null>(null);
  const pendingId = pending?.id ?? null;
  const [failure, setFailure] = React.useState<string | null>(null);
  //: 浏览器那边登录成了,等人把回调页上的确认码填进来。
  const [confirming, setConfirming] = React.useState(false);
  const [code, setCode] = React.useState("");
  const [codeHint, setCodeHint] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const providers = useQuery({ queryKey: ["oauth-providers"], queryFn: oauthProviders, staleTime: 60_000 });

  const reset = () => {
    setPending(null);
    setConfirming(false);
    setCode("");
    setCodeHint(null);
  };

  React.useEffect(() => {
    if (!pendingId || confirming) return;
    const timer = window.setInterval(async () => {
      try {
        const state = await oauthPending(pendingId);
        if (state.status === "confirm") {
          setConfirming(true);
        } else if (state.status === "error" || state.status === "expired") {
          reset();
          setFailure(state.error || t("authOauthFailed"));
        }
      } catch {
        /* 后端瞬断:下一轮再试 */
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pendingId, confirming, t]);

  const submitCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!pendingId || !code.trim()) return;
    setSubmitting(true);
    try {
      const answer = await oauthConfirm(pendingId, code);
      if (answer.status === "done" && answer.token && answer.user) {
        reset();
        adoptAuth({ token: answer.token, user: answer.user });
      } else if (answer.status === "wrong_code") {
        setCodeHint(t("authOauthWrongCode").replace("{n}", String(answer.attempts_left ?? 0)));
      } else if (answer.status !== "waiting") {
        reset();
        setFailure(answer.error || t("authOauthFailed"));
      }
    } catch (err) {
      setCodeHint(String((err as Error).message));
    } finally {
      setSubmitting(false);
    }
  };

  const begin = async (provider: string) => {
    setFailure(null);
    setPending({ provider, id: null });
    try {
      const { pending_id, url } = await oauthStart(provider);
      window.open(url, "_blank", "noopener");
      setPending({ provider, id: pending_id });
    } catch (err) {
      setPending(null);
      setFailure(String((err as Error).message));
    }
  };

  const list = providers.data?.providers ?? [];
  if (list.length === 0) return null;

  return (
    <div className="grid gap-2.5">
      <div className="flex items-center gap-2.5 text-ui-xs text-muted-foreground before:h-px before:flex-1 before:bg-border before:content-[''] after:h-px after:flex-1 after:bg-border after:content-['']">
        {t("authOr")}
      </div>
      {list.includes("google") && (
        <Button variant="outline" className="w-full" disabled={pending !== null} loading={pending?.provider === "google"} onClick={() => begin("google")}>
          <GoogleMark />
          {t("authContinueGoogle")}
        </Button>
      )}
      {list.includes("apple") && (
        <Button variant="outline" className="w-full" disabled={pending !== null} loading={pending?.provider === "apple"} onClick={() => begin("apple")}>
          <AppleMark />
          {t("authContinueApple")}
        </Button>
      )}
      {pendingId && !confirming && (
        <p className="m-0 flex items-center justify-between gap-2 text-ui-xs leading-normal text-muted-foreground">
          {t("authOauthWaiting")}
          <Button variant="inline" onClick={reset}>
            {t("authOauthCancel")}
          </Button>
        </p>
      )}
      {pendingId && confirming && (
        <form className="grid gap-2" onSubmit={submitCode} data-oauth-confirm="">
          <label className="text-ui-xs leading-normal text-muted-foreground" htmlFor="oauth-confirm-code">
            {t("authOauthConfirmLead")}
          </label>
          <div className="flex gap-2">
            <Input
              id="oauth-confirm-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="ABC-DEF"
              autoComplete="one-time-code"
              autoFocus
              className="font-mono uppercase tracking-widest"
            />
            <Button type="submit" loading={submitting} disabled={!code.trim()}>
              {t("authOauthConfirmSubmit")}
            </Button>
          </div>
          {codeHint && <p className="m-0 text-ui-xs text-destructive">{codeHint}</p>}
          <p className="m-0 flex items-center justify-between gap-2 text-ui-xs leading-normal text-muted-foreground">
            {t("authOauthConfirmNote")}
            <Button variant="inline" onClick={reset}>
              {t("authOauthCancel")}
            </Button>
          </p>
        </form>
      )}
      {failure && <p className="m-0 text-ui-xs text-destructive">{failure}</p>}
    </div>
  );
}

//: 两家的标做成组件:按钮在跑时 Button 会把「第一个图标」换成转圈,认的是组件 —— 直接写的 <svg> 会被留着,转圈另加在前面。
function GoogleMark() {
  return <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden><path fill="currentColor" d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.4Z"/><path fill="currentColor" opacity=".7" d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22Z"/><path fill="currentColor" opacity=".5" d="M6.4 14a6 6 0 0 1 0-3.9V7.5H3.1a10 10 0 0 0 0 9.1L6.4 14Z"/><path fill="currentColor" opacity=".85" d="M12 6c1.5 0 2.8.5 3.8 1.5L18.7 4.7A10 10 0 0 0 3.1 7.5L6.4 10c.8-2.3 3-4 5.6-4Z"/></svg>;
}

function AppleMark() {
  return <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden><path fill="currentColor" d="M16.7 12.9c0-2.3 1.9-3.4 2-3.5-1.1-1.6-2.8-1.8-3.4-1.8-1.4-.1-2.8.8-3.5.8-.7 0-1.9-.8-3.1-.8-1.6 0-3 .9-3.9 2.4-1.6 2.9-.4 7.1 1.2 9.4.8 1.1 1.7 2.4 3 2.4 1.2 0 1.6-.8 3.1-.8s1.9.8 3.1.8c1.3 0 2.1-1.2 2.9-2.3.9-1.3 1.3-2.6 1.3-2.7 0 0-2.6-1-2.7-3.9ZM14.4 5.6c.6-.8 1.1-1.9 1-3-1 0-2.1.6-2.8 1.5-.6.7-1.2 1.9-1 3 1 .1 2.1-.6 2.8-1.5Z"/></svg>;
}

/** 左侧英雄面板:满幅背景图(加载失败时退回品牌渐变),底部叠加品牌语。
 * 窄屏(<lg)整块隐藏,退回单列表单。
 *
 * 图片走 import 而不是 public/ 的绝对路径:打包版用 file:// 加载 index.html,
 * 写死的 "/login-hero.jpg" 会解析到**文件系统根目录**而不是应用包内(dev 下 vite
 * 从根提供服务所以看不出来),封面图在打包后静默消失、只剩兜底渐变。import 让
 * vite 产出随 base 正确解析的相对 URL。 */
function LoginHero() {
  const t = useI18n();
  const [imageOk, setImageOk] = React.useState(true);
  return (
    <aside className="relative m-6 hidden overflow-hidden rounded-2xl lg:block">
      {/* 渐变兜底始终垫底;图片在其上,onError 即撤下。 */}
      <div className="absolute inset-0 bg-[linear-gradient(160deg,color-mix(in_srgb,var(--primary)_58%,var(--background))_0%,color-mix(in_srgb,var(--primary)_24%,var(--background))_46%,var(--background)_100%)]" />
      {imageOk && (
        <img
          src={loginHeroUrl}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => setImageOk(false)}
        />
      )}
      {/* 底部压暗渐变保证文字可读(图片场景);纯渐变兜底时同样成立。 */}
      <div className="absolute inset-x-0 bottom-0 h-[46%] bg-[linear-gradient(to_top,rgba(10,8,16,0.62)_0%,rgba(10,8,16,0.32)_55%,transparent_100%)]" />
      <div className="absolute inset-x-0 bottom-0 grid gap-4 p-12 [&_p]:m-0 [&_p]:max-w-[42ch] [&_p]:text-ui-md [&_p]:leading-relaxed [&_p]:text-white/85 [&_strong]:text-4xl [&_strong]:font-semibold [&_strong]:leading-tight [&_strong]:tracking-[-0.015em] [&_strong]:text-white">
        <strong>{t("loginHeroTitle")}</strong>
        <p>{t("loginHeroBody")}</p>
      </div>
    </aside>
  );
}
