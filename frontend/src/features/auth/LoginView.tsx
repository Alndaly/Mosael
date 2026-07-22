import React from "react";
import { CircleAlert, Film } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ServerPicker } from "@/components/layout/ServerPicker";
import { LegalDialog, type LegalDoc } from "@/features/auth/legal";
import type { MessageKey } from "@/app/messages";

type LoginValues = { username: string; displayName: string; password: string; confirm: string };

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
  const { hasUsers, login, register } = useAuth();
  const [mode, setMode] = React.useState<"login" | "register">(hasUsers ? "login" : "register");
  const [legalDoc, setLegalDoc] = React.useState<LegalDoc | null>(null);

  const schema = React.useMemo(() => {
    const base = z.object({
      username: z.string().min(1, t("fieldRequired")),
      displayName: z.string(),
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
    defaultValues: { username: "", displayName: "", password: "", confirm: "" },
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
      else await register(values.username, values.password, values.displayName);
    } catch (err) {
      form.setError("root", { message: friendlyAuthError((err as Error).message, mode, t) });
    }
  });

  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <LoginHero />

      <main className="grid min-h-screen grid-rows-[minmax(0,1fr)_auto] justify-items-center overflow-y-auto px-6 py-8">
        <div className="grid w-[min(340px,100%)] content-center gap-6">
          <div className="grid gap-2.5 [&_h1]:m-0 [&_h1]:text-[22px] [&_h1]:font-[640] [&_h1]:leading-[1.15] [&_h1]:tracking-[-0.02em] [&_h1]:text-foreground [&_p]:m-0 [&_p]:text-[13px] [&_p]:leading-normal [&_p]:text-muted-foreground">
            <div className="mb-1.5 grid h-11 w-11 place-items-center rounded-xl bg-primary text-primary-foreground">
              <Film size={21} />
            </div>
            <h1>{mode === "login" ? t("loginWelcomeBack") : t("loginCreateTitle")}</h1>
            <p>{mode === "login" ? t("loginSubtitle") : t("registerSubtitle")}</p>
          </div>

          <Form {...form}>
            <form className="grid gap-3" onSubmit={onSubmit} noValidate>
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
                <p className="m-0 text-[11.5px] leading-[1.6] text-muted-foreground [&_button]:cursor-pointer [&_button]:border-0 [&_button]:bg-transparent [&_button]:p-0 [&_button]:text-[length:inherit] [&_button]:text-foreground [&_button]:underline [&_button]:underline-offset-2 [&_button:hover]:text-primary">
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
            className="-mt-2 cursor-pointer justify-self-start border-0 bg-transparent p-0.5 text-[12.5px] text-muted-foreground hover:text-accent-foreground hover:underline"
            onClick={switchMode}
          >
            {mode === "login" ? t("switchToRegister") : t("switchToLogin")}
          </button>
        </div>
        <LegalDialog doc={legalDoc} onClose={() => setLegalDoc(null)} />

        {/* 服务器入口必须在登录前:选定本地/团队后端,再对它认证。 */}
        <div className="flex w-[min(340px,100%)] justify-start border-t border-border pt-4">
          <ServerPicker />
        </div>
      </main>
    </div>
  );
}

/** 左侧英雄面板:公共目录的 /login-hero.jpg 作满幅背景(加载失败时退回品牌渐变),
 * 底部叠加品牌语。窄屏(<lg)整块隐藏,退回单列表单。 */
function LoginHero() {
  const t = useI18n();
  const [imageOk, setImageOk] = React.useState(true);
  return (
    <aside className="relative hidden overflow-hidden lg:block">
      {/* 渐变兜底始终垫底;图片在其上,onError 即撤下。 */}
      <div className="absolute inset-0 bg-[linear-gradient(160deg,color-mix(in_srgb,var(--primary)_58%,var(--background))_0%,color-mix(in_srgb,var(--primary)_24%,var(--background))_46%,var(--background)_100%)]" />
      {imageOk && (
        <img
          src="/login-hero.jpg"
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => setImageOk(false)}
        />
      )}
      {/* 底部压暗渐变保证文字可读(图片场景);纯渐变兜底时同样成立。 */}
      <div className="absolute inset-x-0 bottom-0 h-[46%] bg-[linear-gradient(to_top,rgba(10,8,16,0.62)_0%,rgba(10,8,16,0.32)_55%,transparent_100%)]" />
      <div className="absolute inset-x-0 bottom-0 grid gap-1.5 p-10 [&_p]:m-0 [&_p]:max-w-[42ch] [&_p]:text-[13.5px] [&_p]:leading-relaxed [&_p]:text-white/85 [&_strong]:text-[21px] [&_strong]:font-[640] [&_strong]:leading-tight [&_strong]:tracking-[-0.015em] [&_strong]:text-white">
        <strong>{t("loginHeroTitle")}</strong>
        <p>{t("loginHeroBody")}</p>
      </div>
    </aside>
  );
}
