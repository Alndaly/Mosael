import { humanError } from "@/api/errorMessage";

const SERVER_KEY = "mosael.server.url";
export const DEFAULT_API_BASE = "http://127.0.0.1:8800";
export const API_BASE = (
  typeof window === "undefined" ? DEFAULT_API_BASE : window.localStorage.getItem(SERVER_KEY) || DEFAULT_API_BASE
).replace(/\/+$/, "");

/** 后端在「这次请求建了任务」时带的响应头(见 backend 的 app/api/middleware.AnnounceNewJobs)。 */
export const NEW_JOBS_HEADER = "X-Mosael-New-Jobs";
/**
 * 看到那个头就广播这个事件,由 App 统一刷新所有任务列表。
 *
 * 不让各个「开始 xx」按钮自己去刷新:建任务的接口几十个,记得刷新的只有少数几处,其余的
 * 任务要等任务中心下一轮轮询(空闲时 8 秒)才出现。
 */
export const JOBS_CREATED_EVENT = "mosael:jobs-created";

export function setServerUrl(url: string | null): void {
  if (url && url.replace(/\/+$/, "") !== DEFAULT_API_BASE) {
    window.localStorage.setItem(SERVER_KEY, url.replace(/\/+$/, ""));
  } else {
    window.localStorage.removeItem(SERVER_KEY);
  }
}

export function isCustomServer(): boolean {
  return API_BASE !== DEFAULT_API_BASE;
}

const TOKEN_KEY = "mosael.auth.token";
let authToken: string | null = typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;
let apiLocale = "zh";

export function setApiLocale(locale: string): void {
  apiLocale = locale;
}

export class ApiOfflineError extends Error {
  readonly offline = true;
}

/** HTTP failure with machine-readable status/body for conflict-aware domain clients. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (typeof window !== "undefined") {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/** Unified HTTP seam for every domain client. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const auth: Record<string, string> = {
    // 语法是 `<界面>/<版本>`(见 backend/app/api/deps/auth.parse_client_header)。此前这里只发
    // 版本号,而浏览器扩展发的是字面量 `browser-extension` —— 同一栏两个意思,管理页于是
    // 把扩展那一行渲染成「vbrowser-extension」。
    "X-Mosael-Client": `app/${__APP_VERSION__}`,
    "Accept-Language": apiLocale,
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
  };
  const headers =
    init?.body instanceof FormData
      ? { ...auth, ...(init?.headers as Record<string, string> | undefined) }
      : { "Content-Type": "application/json", ...auth, ...(init?.headers as Record<string, string> | undefined) };
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (cause) {
    throw new ApiOfflineError(`${API_BASE} 连不上`, { cause });
  }
  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    onUnauthorized?.();
    throw new Error("Not authenticated");
  }
  if (!response.ok) {
    const body = await response.text();
    const method = (init?.method ?? "GET").toUpperCase();
    console.warn(
      `[api] ${method} ${path} → ${response.status} ${response.statusText}${body ? `: ${body}` : ""}`,
    );
    throw new ApiError(humanError(response.status, response.statusText, body), response.status, body);
  }
  if (response.headers.has(NEW_JOBS_HEADER) && typeof window !== "undefined") {
    window.dispatchEvent(new Event(JOBS_CREATED_EVENT));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
