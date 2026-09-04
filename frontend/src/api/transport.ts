import { humanError } from "@/api/errorMessage";

const SERVER_KEY = "mosael.server.url";
export const DEFAULT_API_BASE = "http://127.0.0.1:8800";
export const API_BASE = (
  typeof window === "undefined" ? DEFAULT_API_BASE : window.localStorage.getItem(SERVER_KEY) || DEFAULT_API_BASE
).replace(/\/+$/, "");

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
    "X-Mosael-Client": __APP_VERSION__,
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
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
