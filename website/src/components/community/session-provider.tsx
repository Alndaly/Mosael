"use client";

/**
 * 社区会话的 React 那一层:一页一个 SessionClient(lib/community/session.ts),经 context 交给
 * 站头的账号菜单、登录页、「我的账号」等组件。
 *
 * 挂在根布局里 —— 这不会让静态页变成动态页:它是个客户端组件,服务端只渲染出「状态未知」,
 * 真正的恢复会话在浏览器里做。文档页上它什么也不打(见 SessionClient.bootstrap 的标记)。
 */
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { HTML_LANG, type Locale } from "@/i18n/config";
import { API_PREFIX } from "@/lib/community/endpoints";
import { browserEnv, SessionClient, type RequestOptions, type SessionSnapshot } from "@/lib/community/session";
import type { User } from "@/lib/community/types";

const SERVER_SNAPSHOT: SessionSnapshot = { status: "unknown", user: null };

type SessionContextValue = { client: SessionClient | null };

const SessionContext = React.createContext<SessionContextValue>({ client: null });

/** 一个浏览器标签页只有一个会话客户端 —— 换页、换语言都沿用它,不重新刷新。 */
let shared: SessionClient | null = null;

function sharedClient(locale: Locale): SessionClient {
  if (!shared) shared = new SessionClient({ baseUrl: API_PREFIX, language: HTML_LANG[locale], env: browserEnv() });
  return shared;
}

const noopSubscribe = () => () => {};

export function SessionProvider({ locale, children }: { locale: Locale; children: React.ReactNode }) {
  const [client] = React.useState<SessionClient | null>(() => (typeof window === "undefined" ? null : sharedClient(locale)));

  React.useEffect(() => {
    void client?.bootstrap();
  }, [client]);

  React.useEffect(() => {
    client?.setLanguage(HTML_LANG[locale]);
  }, [client, locale]);

  const value = React.useMemo(() => ({ client }), [client]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export type Session = SessionSnapshot & {
  client: SessionClient | null;
  /** 带令牌、401 自动刷新重放一次的类型化请求(见 SessionClient.fetchJson)。 */
  communityFetch: <T>(path: string, options?: RequestOptions) => Promise<T>;
  logout: () => Promise<void>;
};

export function useSession(): Session {
  const { client } = React.useContext(SessionContext);
  const snapshot = React.useSyncExternalStore(
    client?.subscribe ?? noopSubscribe,
    client?.getSnapshot ?? (() => SERVER_SNAPSHOT),
    () => SERVER_SNAPSHOT,
  );
  const communityFetch = React.useCallback(
    <T,>(path: string, options?: RequestOptions): Promise<T> => {
      if (!client) return Promise.reject(new Error("session client is not ready"));
      return client.fetchJson<T>(path, options);
    },
    [client],
  );
  const logout = React.useCallback(async () => {
    await client?.logout();
  }, [client]);
  return { ...snapshot, client, communityFetch, logout };
}

/**
 * 需要登录的页面用它:先强制试一次恢复会话(标记可能被清过而 cookie 还在),确定没登录就带着
 * `?next=` 送去登录页,登录完回到这里。
 */
export function useRequireSession(locale: Locale): Session {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const { client, status } = session;

  React.useEffect(() => {
    void client?.bootstrap({ force: true });
  }, [client]);

  React.useEffect(() => {
    if (status !== "anonymous") return;
    const next = `${pathname}${window.location.search}`;
    router.replace(`/${locale}/login?next=${encodeURIComponent(next)}`);
  }, [status, pathname, router, locale]);

  return session;
}

export function isModerator(user: User | null): boolean {
  return user?.role === "moderator" || user?.role === "admin";
}
