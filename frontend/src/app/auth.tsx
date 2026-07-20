import React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, getAuthToken, setAuthToken, setUnauthorizedHandler, type AuthOut, type User } from "@/api/client";

type AuthState = {
  status: "loading" | "anonymous" | "authenticated";
  user: User | null;
  hasUsers: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = React.createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<AuthState["status"]>("loading");
  const [user, setUser] = React.useState<User | null>(null);
  const [hasUsers, setHasUsers] = React.useState(true);

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
      const bootstrap = await api<{ has_users: boolean }>("/api/auth/bootstrap");
      setHasUsers(bootstrap.has_users);
    } catch {
      setHasUsers(true);
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

  const value: AuthState = {
    status,
    user,
    hasUsers,
    login: async (username, password) => {
      applyAuth(await api<AuthOut>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }));
    },
    register: async (username, password) => {
      applyAuth(
        await api<AuthOut>("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
      );
    },
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
