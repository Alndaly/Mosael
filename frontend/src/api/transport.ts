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

/** 连的是别处的服务器时,它给人看的那一截(主机名加端口);连本机时是 null。 */
export function customServerHost(): string | null {
  if (!isCustomServer()) return null;
  try {
    return new URL(API_BASE).host;
  } catch {
    return API_BASE;
  }
}

const TOKEN_KEY = "mosael.auth.token";
let authToken: string | null = typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
let onUnauthorized: (() => void) | null = null;
/**
 * 语言相关的两样东西由界面层配置进来(见 app/preferences):请求带的 Accept-Language(后端据此选它
 * 那部分文案的语言),以及连不上时那句话怎么说。api 层不认识界面的文案表 —— 那是上一层的东西;
 * 此前这里为了一句离线提示 import 了整张中英文案表。
 */
export type ApiLocale = { locale: string; unreachable: (url: string) => string };
let apiLocale: ApiLocale = { locale: "zh-CN", unreachable: (url) => `Can't reach ${url}` };

export function configureApiLocale(next: ApiLocale): void {
  apiLocale = next;
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

/**
 * 服务端明确回了 404:那样东西**不在了**。断网(ApiOfflineError)、5xx、超时都不算 —— 把一次偶发的失败
 * 说成「已删除」,用户会顺手把引用它的那一格也删掉。
 */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
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

/** 每个请求都带的那几个头:客户端、语言、登录凭据。 */
function baseHeaders(): Record<string, string> {
  return {
    // 语法是 `<界面>/<版本>`(见 backend/app/api/deps/auth.parse_client_header)。此前这里只发
    // 版本号,而浏览器扩展发的是字面量 `browser-extension` —— 同一栏两个意思,管理页于是
    // 把扩展那一行渲染成「vbrowser-extension」。
    "X-Mosael-Client": `app/${__APP_VERSION__}`,
    "Accept-Language": apiLocale.locale,
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
  };
}

/** 一个没成的响应 → 抛什么:401 交给登录处理,别的带着状态码和原文。`api` 和 `apiUpload` 同一套。 */
function failure(path: string, method: string, status: number, statusText: string, body: string): Error {
  if (status === 401 && !path.startsWith("/api/auth/")) {
    onUnauthorized?.();
    return new Error("Not authenticated");
  }
  console.warn(`[api] ${method.toUpperCase()} ${path} → ${status} ${statusText}${body ? `: ${body}` : ""}`);
  return new ApiError(humanError(status, statusText, body), status, body);
}

/** Unified HTTP seam for every domain client: headers, offline, 401 and error bodies are handled once. */
async function request(path: string, init?: RequestInit): Promise<Response> {
  const auth = baseHeaders();
  const headers =
    init?.body instanceof FormData
      ? { ...auth, ...(init?.headers as Record<string, string> | undefined) }
      : { "Content-Type": "application/json", ...auth, ...(init?.headers as Record<string, string> | undefined) };
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (cause) {
    // 调用方自己掐断的请求(切会话、卸载、React Query 取消)不是「连不上」。
    if (init?.signal?.aborted) throw cause;
    throw new ApiOfflineError(apiLocale.unreachable(API_BASE), { cause });
  }
  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    throw failure(path, init?.method ?? "GET", response.status, response.statusText, "");
  }
  if (!response.ok) {
    throw failure(path, init?.method ?? "GET", response.status, response.statusText, await response.text());
  }
  if (response.headers.has(NEW_JOBS_HEADER) && typeof window !== "undefined") {
    window.dispatchEvent(new Event(JOBS_CREATED_EVENT));
  }
  return response;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** 回的是一段二进制(试听的音频)而不是 JSON 的接口。报错、掉线、401 和 `api` 同一套处理。 */
export async function apiBlob(path: string, init?: RequestInit): Promise<Blob> {
  return (await request(path, init)).blob();
}

/** 回的是一条持续推送的流(SSE)而不是一次性的响应体。报错、掉线、401 和 `api` 同一套处理。 */
export async function apiStream(path: string, init?: RequestInit): Promise<ReadableStream<Uint8Array>> {
  const response = await request(path, init);
  if (!response.body) throw new ApiError("Empty stream", response.status, "");
  return response.body;
}

/**
 * 传一个文件(表单),**说得出传了多少、停得下来**:`onProgress` 收 0..1(上传那一段的进度;服务端收完到回包之间
 * 停在 1),`signal` 一掐就停,抛 `AbortError`。fetch 给不出上传进度,所以这一个走 XMLHttpRequest;请求头、
 * 掉线、401、报错原文和 `api` 同一套。
 */
export function apiUpload<T>(
  path: string,
  form: FormData,
  { signal, onProgress }: { signal?: AbortSignal; onProgress?: (fraction: number) => void } = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const aborted = () => new DOMException("The upload was cancelled.", "AbortError");
    if (signal?.aborted) {
      reject(aborted());
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    for (const [name, value] of Object.entries(baseHeaders())) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(Math.min(1, event.loaded / event.total));
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(failure(path, "POST", xhr.status, xhr.statusText, xhr.responseText ?? ""));
        return;
      }
      if (xhr.getResponseHeader(NEW_JOBS_HEADER) !== null && typeof window !== "undefined") {
        window.dispatchEvent(new Event(JOBS_CREATED_EVENT));
      }
      try {
        resolve((xhr.status === 204 || !xhr.responseText ? undefined : JSON.parse(xhr.responseText)) as T);
      } catch (cause) {
        reject(cause);
      }
    };
    xhr.onerror = () => reject(new ApiOfflineError(apiLocale.unreachable(API_BASE)));
    xhr.onabort = () => reject(aborted());
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}
