import React from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  api,
  getAuthToken,
  setAuthToken,
  setUnauthorizedHandler,
  updateMe,
  updatePassword,
  uploadAvatar,
  type AuthOut,
  type User,
} from "@/api/client";

type AuthState = {
  status: "loading" | "anonymous" | "authenticated";
  user: User | null;
  hasUsers: boolean;
  /** 这个部署收不收自助注册。不收时注册要邀请码,登录页才摆那个框。 */
  openRegistration: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, displayName?: string, inviteCode?: string) => Promise<void>;
  /** 第三方登录轮询取到票后直接落座(token+user 已由后端铸好)。 */
  adoptAuth: (auth: { token: string; user: User }) => void;
  updateProfile: (profile: { username: string; display_name: string; signature: string }) => Promise<User>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  updateAvatar: (file: File) => Promise<User>;
  logout: () => Promise<void>;
};

const AuthContext = React.createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<AuthState["status"]>("loading");
  const [user, setUser] = React.useState<User | null>(null);
  const [hasUsers, setHasUsers] = React.useState(true);
  const [openRegistration, setOpenRegistration] = React.useState(true);

  const qc = useQueryClient();

  const becomeAnonymous = React.useCallback(async () => {
    setAuthToken(null);
    setUser(null);
    // Drop every cached response with the identity that fetched it. Nothing used to clear the
    // cache on logout or on a 401, and the global staleTime is 60s, so a query remounting with
    // cached data does not refetch: log out, log in as someone else on the same machine, and
    // the new session renders the previous user's workspaces, projects, assets and jobs until
    // those entries go stale.
    qc.clear();
    try {
      const bootstrap = await api<{ has_users: boolean; open_registration: boolean }>("/api/auth/bootstrap");
      setHasUsers(bootstrap.has_users);
      setOpenRegistration(bootstrap.open_registration);
    } catch {
      // 探不到就按"有人且不开放"渲染:那是更保守的一屏(要求登录、要邀请码),
      // 而不是对着一个连不上的后端摆出「创建管理员账户」。
      setHasUsers(true);
      setOpenRegistration(false);
    }
    setStatus("anonymous");
  }, [qc]);

  React.useEffect(() => {
    setUnauthorizedHandler(() => void becomeAnonymous());
    return () => setUnauthorizedHandler(null);
  }, [becomeAnonymous]);

  React.useEffect(() => {
    const boot = async () => {
      if (!getAuthToken()) {
        await becomeAnonymous();
        return;
      }
      try {
        const me = await api<User>("/api/auth/me");
        setUser(me);
        setStatus("authenticated");
      } catch {
        await becomeAnonymous();
      }
    };
    void boot();
  }, [becomeAnonymous]);

  const applyAuth = (auth: AuthOut) => {
    setAuthToken(auth.token);
    setUser(auth.user);
    setStatus("authenticated");
  };

  const updateProfile = React.useCallback(async (profile: { username: string; display_name: string; signature: string }) => {
    const next = await updateMe(profile);
    setUser(next);
    return next;
  }, []);

  const changePassword = React.useCallback(async (currentPassword: string, newPassword: string) => {
    await updatePassword({ current_password: currentPassword, new_password: newPassword });
  }, []);

  const updateAvatar = React.useCallback(async (file: File) => {
    const next = await uploadAvatar(file);
    setUser(next);
    return next;
  }, []);

  const value: AuthState = {
    status,
    user,
    hasUsers,
    openRegistration,
    login: async (username, password) => {
      applyAuth(await api<AuthOut>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }));
    },
    register: async (username, password, displayName, inviteCode) => {
      applyAuth(
        await api<AuthOut>("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({
            username,
            password,
            display_name: displayName || username,
            // 空库的第一个账号不需要码;之后这个部署要么开放注册,要么得有人给他一个。
            invite_code: inviteCode ?? "",
          }),
        }),
      );
    },
    adoptAuth: (auth) => applyAuth(auth as AuthOut),
    updateProfile,
    changePassword,
    updateAvatar,
    logout: async () => {
      try {
        await api("/api/auth/logout", { method: "POST" });
      } catch {
        // Local session cleanup happens regardless.
      }
      await becomeAnonymous();
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = React.useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
