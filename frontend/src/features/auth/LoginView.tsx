import React from "react";
import { CircleAlert, Languages } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useQuery } from "@tanstack/react-query";

import { oauthPending, oauthProviders, oauthStart } from "@/api/client";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import { BrandMark } from "@/components/layout/BrandMark";
import loginHeroUrl from "@/assets/login-hero.jpg";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ServerPicker } from "@/components/layout/ServerPicker";
import { LegalDialog, type LegalDoc } from "@/features/auth/legal";
import type { MessageKey } from "@/app/messages";

type LoginValues = { username: string; displayName: string; password: string; confirm: string; inviteCode: string };

/** Map a raw API error body to a friendly, accurate message — instead of always
 * blaming the credentials (a server/network error is not a wrong password). */
function friendlyAuthError(raw: string, mode: "login" | "register", t: (key: MessageKey) => string): string {
  try {
    const detail = (JSON.parse(raw) as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.toLowerCase().includes("exists")) return t("usernameTaken");
  } catch {
    /* not JSON (e.g. network failure) → fall through */
  }
  if (!raw || raw.toLowerCase().includes("failed to fetch") || raw.toLowerCase().includes("networkerror")) {
    return t("loginNetworkError");
  }
  if (/^5\d\d\b/.test(raw)) return t("loginServerError");
  return mode === "login" ? t("loginFailed") : t("registerFailed");
}

export function LoginView() {
  const t = useI18n();
  const { locale, setLocale } = usePreferences();
  const { hasUsers, openRegistration, login, register } = useAuth();
  const [mode, setMode] = React.useState<"login" | "register">(hasUsers ? "login" : "register");
  const [legalDoc, setLegalDoc] = React.useState<LegalDoc | null>(null);

  const schema = React.useMemo(() => {
    const base = z.object({
      username: z.string().min(1, t("fieldRequired")),
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
      else await register(values.username, values.password, values.displayName, values.inviteCode);
    } catch (err) {
      form.setError("root", { message: friendlyAuthError((err as Error).message, mode, t) });
    }
  });

  return (
    <div className="relative grid min-h-screen bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      {/* 桌面端无边框窗:登录/注册页不挂 AppShell,若不自带拖拽条,整个窗口在登录前完全
          拖不动(只能靠系统快捷键移动)。这条透明带盖住顶栏高度,层级压在语言按钮之下,
          按钮自身标 no-drag 保证可点。 */}
      <div
        className="fixed inset-x-0 top-0 z-[5] hidden h-11 [.is-desktop_&]:block [-webkit-app-region:drag]"
        aria-hidden
      />
      <LoginHero />

      {/* 未登录也能换语言:与壳层同一偏好存储,登录后无缝延续。 */}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="absolute right-4 top-4 z-10 gap-1.5 text-muted-foreground [-webkit-app-region:no-drag]"
        onClick={() => setLocale(locale === "zh-CN" ? "en-US" : "zh-CN")}
        title={locale === "zh-CN" ? "Switch to English" : "切换到中文"}
        aria-label={locale === "zh-CN" ? "Switch to English" : "切换到中文"}
      >
        <Languages size={14} /> {locale === "zh-CN" ? "English" : "中文"}
      </Button>

      <main className="grid min-h-screen grid-rows-[minmax(0,1fr)_auto] justify-items-center overflow-y-auto px-6 py-8">
        <div className="grid w-[min(340px,100%)] content-center gap-6">
          <div className="grid gap-2.5 [&_h1]:m-0 [&_h1]:text-[22px] [&_h1]:font-[640] [&_h1]:leading-[1.15] [&_h1]:tracking-[-0.02em] [&_h1]:text-foreground [&_p]:m-0 [&_p]:text-ui-md [&_p]:leading-normal [&_p]:text-muted-foreground">
            <BrandMark size={48} className="mb-1.5 block" />
            {/* 空库 = 这个部署还没有管理员。直说他正在创建什么,而不是一句泛泛的"创建账户"。 */}
            <h1>{mode === "login" ? t("loginWelcomeBack") : hasUsers ? t("loginCreateTitle") : t("bootstrapTitle")}</h1>
            <p>
              {mode === "login" ? t("loginSubtitle") : hasUsers ? t("registerSubtitle") : t("bootstrapSubtitle")}
            </p>
          </div>

          <Form {...form}>
            {/* 组间 16px 明显大于组内标签的 8px,字段归属一眼可辨。 */}
            <form className="grid gap-4" onSubmit={onSubmit} noValidate>
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
              {mode === "register" && hasUsers && !openRegistration && (
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
              <Button type="submit" className="mt-1.5" disabled={form.formState.isSubmitting}>
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

          <button
            type="button"
            className="-mt-2 cursor-pointer justify-self-start border-0 bg-transparent p-0.5 text-ui-sm text-muted-foreground hover:text-accent-foreground hover:underline"
            onClick={switchMode}
          >
            {mode === "login" ? t("switchToRegister") : t("switchToLogin")}
          </button>

          <OAuthButtons />
        </div>
        <LegalDialog doc={legalDoc} onClose={() => setLegalDoc(null)} />

        {/* 服务器入口必须在登录前:选定本地/团队后端,再对它认证。 */}
        <div className="flex w-[min(340px,100%)] justify-center border-t border-border pt-4">
          <ServerPicker />
        </div>
      </main>
    </div>
  );
}

/** 第三方登录(Google / Apple):后端只报已配置的提供方,一个没配就整块不渲染。
 *  流程:start 拿授权 URL(系统浏览器打开)+ pending_id → 每 2s 轮询取票 →
 *  adoptAuth 落座。file://(Electron)与 5173 开发页都无需注册自己为回调目标。 */
function OAuthButtons() {
  const t = useI18n();
  const { adoptAuth } = useAuth();
  const [pendingId, setPendingId] = React.useState<string | null>(null);
  const [failure, setFailure] = React.useState<string | null>(null);
  const providers = useQuery({ queryKey: ["oauth-providers"], queryFn: oauthProviders, staleTime: 60_000 });

  React.useEffect(() => {
    if (!pendingId) return;
    const timer = window.setInterval(async () => {
      try {
        const state = await oauthPending(pendingId);
        if (state.status === "done" && state.token && state.user) {
          setPendingId(null);
          adoptAuth({ token: state.token, user: state.user });
        } else if (state.status === "error" || state.status === "expired") {
          setPendingId(null);
          setFailure(state.error || t("authOauthFailed"));
        }
      } catch {
        /* 后端瞬断:下一轮再试 */
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pendingId, adoptAuth, t]);

  const begin = async (provider: string) => {
    setFailure(null);
    try {
      const { pending_id, url } = await oauthStart(provider);
      window.open(url, "_blank", "noopener");
      setPendingId(pending_id);
    } catch (err) {
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
        <Button variant="outline" className="w-full" disabled={pendingId !== null} onClick={() => begin("google")}>
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden><path fill="currentColor" d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.4Z"/><path fill="currentColor" opacity=".7" d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22Z"/><path fill="currentColor" opacity=".5" d="M6.4 14a6 6 0 0 1 0-3.9V7.5H3.1a10 10 0 0 0 0 9.1L6.4 14Z"/><path fill="currentColor" opacity=".85" d="M12 6c1.5 0 2.8.5 3.8 1.5L18.7 4.7A10 10 0 0 0 3.1 7.5L6.4 10c.8-2.3 3-4 5.6-4Z"/></svg>
          {t("authContinueGoogle")}
        </Button>
      )}
      {list.includes("apple") && (
        <Button variant="outline" className="w-full" disabled={pendingId !== null} onClick={() => begin("apple")}>
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden><path fill="currentColor" d="M16.7 12.9c0-2.3 1.9-3.4 2-3.5-1.1-1.6-2.8-1.8-3.4-1.8-1.4-.1-2.8.8-3.5.8-.7 0-1.9-.8-3.1-.8-1.6 0-3 .9-3.9 2.4-1.6 2.9-.4 7.1 1.2 9.4.8 1.1 1.7 2.4 3 2.4 1.2 0 1.6-.8 3.1-.8s1.9.8 3.1.8c1.3 0 2.1-1.2 2.9-2.3.9-1.3 1.3-2.6 1.3-2.7 0 0-2.6-1-2.7-3.9ZM14.4 5.6c.6-.8 1.1-1.9 1-3-1 0-2.1.6-2.8 1.5-.6.7-1.2 1.9-1 3 1 .1 2.1-.6 2.8-1.5Z"/></svg>
          {t("authContinueApple")}
        </Button>
      )}
      {pendingId && (
        <p className="m-0 flex items-center justify-between gap-2 text-ui-xs leading-normal text-muted-foreground">
          {t("authOauthWaiting")}
          <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-[length:inherit] text-primary underline underline-offset-2" onClick={() => setPendingId(null)}>
            {t("authOauthCancel")}
          </button>
        </p>
      )}
      {failure && <p className="m-0 text-ui-xs text-destructive">{failure}</p>}
    </div>
  );
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
    <aside className="relative hidden overflow-hidden lg:block">
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
      <div className="absolute inset-x-0 bottom-0 grid gap-1.5 p-10 [&_p]:m-0 [&_p]:max-w-[42ch] [&_p]:text-ui-md [&_p]:leading-relaxed [&_p]:text-white/85 [&_strong]:text-[21px] [&_strong]:font-[640] [&_strong]:leading-tight [&_strong]:tracking-[-0.015em] [&_strong]:text-white">
        <strong>{t("loginHeroTitle")}</strong>
        <p>{t("loginHeroBody")}</p>
      </div>
    </aside>
  );
}
