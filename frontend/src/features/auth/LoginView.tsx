import React from "react";
import { CircleAlert, Film } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Form, FormControl, FormField, FormItem, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ServerPicker } from "@/components/layout/ServerPicker";
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
    <div className="grid min-h-screen place-items-center text-muted-foreground">
      <Card className="w-[min(384px,calc(100vw-32px))] [[data-appearance=glass]_&]:[-webkit-backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)] [[data-appearance=glass]_&]:[backdrop-filter:blur(var(--app-blur,16px))_saturate(1.35)]">
        <CardContent className="grid justify-items-center gap-4 px-7 pb-[22px] pt-[30px] text-center">
          <div className="grid justify-items-center gap-2 [&_h1]:m-0 [&_h1]:text-[19px] [&_h1]:font-[640] [&_h1]:leading-[1.1] [&_h1]:tracking-[-0.02em] [&_h1]:text-foreground [&_p]:m-0 [&_p]:max-w-[30ch] [&_p]:text-[13px] [&_p]:leading-normal [&_p]:text-muted-foreground">
            <div className="mb-0.5 grid h-[46px] w-[46px] place-items-center rounded-[13px] bg-primary text-primary-foreground">
              <Film size={22} />
            </div>
            <h1>Mibu</h1>
            <p>{mode === "login" ? t("loginSubtitle") : t("registerSubtitle")}</p>
          </div>
          <Form {...form}>
            <form className="grid w-full gap-2" onSubmit={onSubmit} noValidate>
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
                    <FormControl>
                      <Input autoFocus placeholder={t("username")} autoComplete="username" {...field} />
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
                      <FormControl>
                        <Input placeholder={t("displayName")} autoComplete="name" {...field} />
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
                    <FormControl>
                      <Input
                        type="password"
                        placeholder={t("password")}
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
                      <FormControl>
                        <Input
                          type="password"
                          placeholder={t("confirmPassword")}
                          autoComplete="new-password"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
              <Button type="submit" disabled={form.formState.isSubmitting}>
                {mode === "login" ? t("signIn") : t("createAccount")}
              </Button>
            </form>
          </Form>
          <button type="button" className="-mt-1.5 cursor-pointer border-0 bg-transparent p-0.5 text-[12.5px] text-muted-foreground hover:text-accent-foreground hover:underline" onClick={switchMode}>
            {mode === "login" ? t("switchToRegister") : t("switchToLogin")}
          </button>
          {/* 服务器入口必须在登录前:选定本地/团队后端,再对它认证。 */}
          <div className="mt-0.5 flex w-full justify-center border-t border-border pt-4">
            <ServerPicker />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
