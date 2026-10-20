/**
 * MosaelCloud 的浏览器客户端。
 *
 * **只打同源的 `/api/cloud/v1/*`** —— 生产由 Caddy 把这个前缀转给 cloud 服务,本地开发由
 * `next.config.ts` 的 rewrite 转给 `CLOUD_API_URL`。同源有两个直接好处:会话 cookie 是第一方的,
 * 不需要 CORS + `SameSite=None`;云端那侧的 Origin 校验认的就是官网自己的地址。
 *
 * 会话 token 由服务端放在 HttpOnly cookie 里,**客户端拿不到、也不该拿**。所以这里没有
 * localStorage、没有 Authorization 头 —— 只有 `fetch` 默认带着的同源 cookie。
 */

export const CLOUD_API = "/api/cloud/v1";

export type CloudUser = {
  id: string;
  email: string;
  email_verified_at: string | null;
  created_at: string;
};

export type CloudDevice = { id: string; name: string; created_at: string };

export type CloudMessage = { en: string; zh: string };

const NETWORK_MESSAGE: CloudMessage = {
  en: "Can't reach MosaelCloud. Check your connection and try again.",
  zh: "连不上 MosaelCloud，请检查网络后重试。",
};

const FALLBACK_MESSAGE: CloudMessage = {
  en: "That didn't work. Try again.",
  zh: "操作没有完成，请重试。",
};

/** 云端的一次拒绝。`message` 是中英两份,页面按当前语言挑。 */
export class CloudApiError extends Error {
  constructor(
    readonly code: string,
    readonly messages: CloudMessage,
    readonly status: number,
  ) {
    super(messages.en);
    this.name = "CloudApiError";
  }

  text(locale: "en" | "zh"): string {
    return this.messages[locale] || this.messages.en;
  }
}

function messageOf(value: unknown): CloudMessage {
  if (value && typeof value === "object" && "en" in value && "zh" in value) {
    const found = value as { en?: unknown; zh?: unknown };
    if (typeof found.en === "string" && typeof found.zh === "string") {
      return { en: found.en, zh: found.zh };
    }
  }
  return FALLBACK_MESSAGE;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${CLOUD_API}${path}`, {
      ...init,
      // 同源请求本来就带 cookie;写出来是让"会话在 cookie 里"这件事在调用处可见。
      credentials: "same-origin",
      cache: "no-store",
      headers,
    });
  } catch {
    throw new CloudApiError("network_error", NETWORK_MESSAGE, 0);
  }

  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new CloudApiError(
      typeof body.error === "string" ? body.error : "request_failed",
      messageOf(body.message),
      response.status,
    );
  }
  return body as T;
}

export const cloudAccount = {
  sendSignupCode(email: string): Promise<{ sent: boolean }> {
    return request("/signup/code", { method: "POST", body: JSON.stringify({ email }) });
  },
  signup(email: string, code: string, password: string): Promise<{ user: CloudUser }> {
    return request("/signup", { method: "POST", body: JSON.stringify({ email, code, password }) });
  },
  login(email: string, password: string): Promise<{ user: CloudUser }> {
    return request("/login", { method: "POST", body: JSON.stringify({ email, password }) });
  },
  sendLoginCode(email: string): Promise<{ sent: boolean }> {
    return request("/login/code", { method: "POST", body: JSON.stringify({ email }) });
  },
  loginWithCode(email: string, code: string): Promise<{ user: CloudUser }> {
    return request("/login/code/verify", { method: "POST", body: JSON.stringify({ email, code }) });
  },
  logout(): Promise<void> {
    return request("/logout", { method: "POST" });
  },
  me(): Promise<{ user: CloudUser }> {
    return request("/me");
  },
  deleteAccount(): Promise<void> {
    return request("/me", { method: "DELETE" });
  },
  devices(): Promise<{ devices: CloudDevice[] }> {
    return request("/devices");
  },
  revokeDevice(deviceId: string): Promise<void> {
    return request(`/device/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
  },
  approveDevice(userCode: string): Promise<void> {
    return request("/device/approve", {
      method: "POST",
      body: JSON.stringify({ user_code: userCode }),
    });
  },
};
