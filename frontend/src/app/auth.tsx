import React from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  ApiOfflineError,
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
  //: offline = **令牌还在,只是这会儿够不着后端**。它和 anonymous 必须分开:摆一屏登录页
  //: 等于告诉用户「你的会话结束了」,而其实没有 —— 后端起来之后重试一下就回去了。
  status: "loading" | "anonymous" | "authenticated" | "offline";
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
  /** 连不上之后再试一次(重跑启动那条路,不另写一份)。 */
  retry: () => void;
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

  //: 重试用的:改一下它,下面那个 effect 就再跑一遍 boot。**不是复制一份 boot 的逻辑** ——
  //: 复制出来的那份迟早和真正的启动路径分岔。
  const [attempt, setAttempt] = React.useState(0);
  const retry = React.useCallback(() => {
    setStatus("loading");
    setAttempt((n) => n + 1);
  }, []);

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
      } catch (error) {
        //: **连不上不等于登出。** 这个 catch 以前是光秃秃的:后端一时没起来(本机进程,重启、
        //: 休眠唤醒、启动时抢跑都是常态),它就把令牌删了 —— 而令牌完全有效,删掉之后后端
        //: 回来也救不回,用户只能手动重新登录。
        if (error instanceof ApiOfflineError) {
          setStatus("offline");
          return;
        }
        await becomeAnonymous();
      }
    };
    void boot();
  }, [becomeAnonymous, attempt]);

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
    retry,
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
