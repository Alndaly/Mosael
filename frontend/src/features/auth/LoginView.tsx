import React from "react";
import { Film } from "lucide-react";

import { useAuth } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ServerPicker } from "@/components/layout/ServerPicker";

export function LoginView() {
  const t = useI18n();
  const { hasUsers, login, register } = useAuth();
  const [mode, setMode] = React.useState<"login" | "register">(hasUsers ? "login" : "register");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    setMode(hasUsers ? "login" : "register");
  }, [hasUsers]);

  const mismatch = mode === "register" && confirm.length > 0 && confirm !== password;
  const canSubmit = Boolean(username && password && (mode === "login" || confirm === password));

  const switchMode = () => {
    setMode(mode === "login" ? "register" : "login");
    setConfirm("");
    setError(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(username, password);
      else await register(username, password);
    } catch (err) {
      setError(mode === "login" ? t("loginFailed") : t("registerFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center">
      <Card className="welcome">
        <CardContent className="welcome-content">
          <div className="login-head">
            <div className="login-brand">
              <Film size={22} />
            </div>
            <h1>Mibu</h1>
            <p>{mode === "login" ? t("loginSubtitle") : t("registerSubtitle")}</p>
          </div>
          <form className="login-form" onSubmit={submit}>
            <Input
              autoFocus
              placeholder={t("username")}
              value={username}
              autoComplete="username"
              onChange={(event) => setUsername(event.target.value)}
            />
            <Input
              type="password"
              placeholder={t("password")}
              value={password}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              onChange={(event) => setPassword(event.target.value)}
            />
            {mode === "register" && (
              <Input
                type="password"
                placeholder={t("confirmPassword")}
                value={confirm}
                autoComplete="new-password"
                aria-invalid={mismatch}
                onChange={(event) => setConfirm(event.target.value)}
              />
            )}
            {mismatch && <p className="login-error">{t("passwordMismatch")}</p>}
            {error && <p className="login-error">{error}</p>}
            <Button type="submit" disabled={busy || !canSubmit}>
              {mode === "login" ? t("signIn") : t("createAccount")}
            </Button>
          </form>
          <button type="button" className="login-switch" onClick={switchMode}>
            {mode === "login" ? t("switchToRegister") : t("switchToLogin")}
          </button>
          {/* 服务器入口必须在登录前:选定本地/团队后端,再对它认证。 */}
          <div className="login-server">
            <ServerPicker />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
