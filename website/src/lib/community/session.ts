/**
 * 网页的社区会话(ADR 0026 §3「Token」)。
 *
 * - **访问令牌只在内存里**(这个对象的一个字段),不进 localStorage、不进 cookie;刷新令牌是
 *   服务设的 `HttpOnly` cookie(`Path=…/auth`),脚本碰不到,这里也从不读它 —— 只是在调
 *   `/auth/refresh` 时让浏览器带上。
 * - **到期前 60 秒主动刷新**(每页再随机提前 0–15 秒,见 REFRESH_JITTER_MS);请求发出前发现快到期了
 *   也先刷(标签页睡过一觉,定时器会迟到)。
 * - **收到 401 只刷新一次**:同一时刻只有一个刷新在飞,其余请求等它;成功后原请求重放一次,
 *   再 401 就把那个 401 交出去,不循环;刷新失败回到「未登录」。
 * - **多个标签页之间用 BroadcastChannel** 通告「拿到新令牌了 / 退出了」:别的页直接用这份新令牌、
 *   重排自己的定时器,不各刷各的。
 * - 刷新请求带 `X-Requested-With`,配合 SameSite 防 CSRF。
 * - 页面加载时经 `/auth/refresh` 恢复会话。只在「这个浏览器登录过」时才自动做:文档页的匿名
 *   访客不必每开一页就打一次社区服务。那个标记是 localStorage 里的一个布尔,不是令牌;标记丢了
 *   也不要紧,需要登录的页面会强制试一次(`bootstrap({ force: true })`)。
 *
 * 这个文件不依赖 React,也不直接碰 `window`:时钟、定时器、fetch、广播通道、标记都能注入,
 * 刷新逻辑用 node 的测试跑器就能测(test/session.test.mjs)。React 那一层在
 * components/community/session-provider.tsx。
 */
import { localizeTree } from "@/lib/community/localize";
import { CommunityError, errorFromResponse, networkError } from "@/lib/community/errors";
import type { LoginResponse, User } from "@/lib/community/types";

/** 到期前至少多久主动刷新。 */
export const REFRESH_LEEWAY_MS = 60_000;
/**
 * 每个标签页在 leeway 之上再随机提前至多这么久。几个标签页同时登录时定时器会落在同一刻 ——
 * 错开之后,最先醒的那一页刷新、广播,其余的收到新令牌就重排,不再各刷各的。
 */
export const REFRESH_JITTER_MS = 15_000;
/** 主动刷新遇到网络错误、令牌还没过期时,隔多久再试。 */
export const RETRY_DELAY_MS = 15_000;
export const CHANNEL_NAME = "mosael-community-session";
export const HINT_KEY = "mosael.community.signed-in";
/** 刷新接口要求的头(ADR:配合 SameSite 防 CSRF)。 */
export const REQUESTED_WITH = { "X-Requested-With": "XMLHttpRequest" } as const;

export type SessionStatus = "unknown" | "loading" | "authenticated" | "anonymous";
export type SessionSnapshot = { readonly status: SessionStatus; readonly user: User | null };

export type SessionMessage =
  | { type: "session"; accessToken: string; expiresAt: number; user: User }
  | { type: "logged-out" };

export type ChannelLike = {
  postMessage(message: SessionMessage): void;
  addEventListener(type: "message", listener: (event: { data: unknown }) => void): void;
  close?(): void;
};

export type HintStore = { get(): boolean; set(on: boolean): void };

export type SessionEnv = {
  fetch: (input: string, init?: RequestInit) => Promise<Response>;
  now: () => number;
  setTimer: (callback: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  channel: ChannelLike | null;
  hint: HintStore | null;
  /** [0, 1) 的随机数,决定这一页的提前量。 */
  random: () => number;
};

type RefreshReason = "bootstrap" | "proactive" | "expiring" | "unauthorized";

export type RequestOptions = Omit<RequestInit, "body"> & {
  /** 给了就按 JSON 发,自动加 Content-Type。 */
  json?: unknown;
  body?: BodyInit | null;
};

function isSessionMessage(value: unknown): value is SessionMessage {
  if (!value || typeof value !== "object") return false;
  const type = (value as { type?: unknown }).type;
  if (type === "logged-out") return true;
  if (type !== "session") return false;
  const message = value as { accessToken?: unknown; expiresAt?: unknown; user?: unknown };
  return typeof message.accessToken === "string" && typeof message.expiresAt === "number" && Boolean(message.user);
}

export class SessionClient {
  private readonly base: string;
  private language: string;
  private readonly env: SessionEnv;
  private readonly jitter: number;

  private token: string | null = null;
  private expiresAt = 0;
  private snapshot: SessionSnapshot = { status: "unknown", user: null };
  private inflight: Promise<boolean> | null = null;
  private booting: Promise<void> | null = null;
  private forcedOnce = false;
  private timer: unknown = null;
  private readonly listeners = new Set<() => void>();

  constructor(options: { baseUrl: string; language?: string; env: SessionEnv }) {
    this.base = options.baseUrl.replace(/\/+$/, "");
    this.language = options.language ?? "";
    this.env = options.env;
    this.jitter = Math.floor(this.env.random() * REFRESH_JITTER_MS);
    this.env.channel?.addEventListener("message", (event) => {
      if (isSessionMessage(event.data)) this.receive(event.data);
    });
  }

  // ── 状态 ──────────────────────────────────────────────────────────────

  /** 给 useSyncExternalStore:状态不变时返回同一个对象。 */
  getSnapshot = (): SessionSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** 换了页面语言:之后的请求按新语言要错误信息。 */
  setLanguage(language: string) {
    this.language = language;
  }

  /** 当前的访问令牌。只给测试和调试看;页面发请求一律走 request / fetchJson。 */
  get accessToken(): string | null {
    return this.token;
  }

  private publish(status: SessionStatus, user: User | null) {
    if (this.snapshot.status === status && this.snapshot.user === user) return;
    this.snapshot = { status, user };
    for (const listener of this.listeners) listener();
  }

  private schedule(delay: number) {
    if (this.timer !== null) this.env.clearTimer(this.timer);
    this.timer = this.env.setTimer(() => {
      this.timer = null;
      void this.refresh("proactive");
    }, Math.max(0, delay));
  }

  private adopt(accessToken: string, expiresAt: number, user: User) {
    this.token = accessToken;
    this.expiresAt = expiresAt;
    this.env.hint?.set(true);
    this.schedule(expiresAt - REFRESH_LEEWAY_MS - this.jitter - this.env.now());
    this.publish("authenticated", user);
  }

  private apply(body: LoginResponse, broadcast: boolean) {
    const expiresAt = this.env.now() + body.expires_in * 1000;
    this.adopt(body.access_token, expiresAt, body.user);
    if (broadcast) this.env.channel?.postMessage({ type: "session", accessToken: body.access_token, expiresAt, user: body.user });
  }

  private clear(broadcast: boolean) {
    this.token = null;
    this.expiresAt = 0;
    if (this.timer !== null) this.env.clearTimer(this.timer);
    this.timer = null;
    this.env.hint?.set(false);
    this.publish("anonymous", null);
    if (broadcast) this.env.channel?.postMessage({ type: "logged-out" });
  }

  /** 别的标签页发来的:拿到新令牌就直接用(只收更新的那份),退出了就跟着退。 */
  private receive(message: SessionMessage) {
    if (message.type === "logged-out") {
      this.clear(false);
      return;
    }
    if (message.expiresAt < this.expiresAt) return;
    this.adopt(message.accessToken, message.expiresAt, message.user);
  }

  // ── 刷新 ──────────────────────────────────────────────────────────────

  /**
   * 换一对新令牌。**单飞**:已经有一个在飞,就等那一个 —— 并发的几个 401 只会换来一次刷新,
   * 也就不会把一个刚轮换掉的刷新令牌再交一次(ADR 里那算被盗,整个会话吊销)。
   */
  refresh(reason: RefreshReason = "unauthorized"): Promise<boolean> {
    if (!this.inflight) {
      this.inflight = this.runRefresh(reason).finally(() => {
        this.inflight = null;
      });
    }
    return this.inflight;
  }

  private async runRefresh(reason: RefreshReason): Promise<boolean> {
    let response: Response;
    try {
      response = await this.env.fetch(`${this.base}/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
        headers: { ...REQUESTED_WITH, Accept: "application/json", ...this.languageHeader() },
      });
    } catch {
      return this.refreshFailed(reason, false);
    }
    if (!response.ok) return this.refreshFailed(reason, response.status < 500);
    let body: LoginResponse;
    try {
      body = (await response.json()) as LoginResponse;
    } catch {
      return this.refreshFailed(reason, false);
    }
    this.apply(body, true);
    return true;
  }

  /**
   * `definitive`:服务明确说不行(4xx —— 刷新令牌过期、被吊销、被判重放)。这时整个会话都死了,
   * 通知别的标签页一起退出。网络错误、5xx 不算:主动刷新时令牌还没过期,过一会儿再试;其余情形
   * 本页回到未登录,但不替别的页做决定。
   *
   * 启动时的失败**永远不广播**:那只说明这一页没有会话,别的页可能好好地登录着。
   */
  private refreshFailed(reason: RefreshReason, definitive: boolean): false {
    if (reason === "proactive" && !definitive && this.token && this.env.now() < this.expiresAt) {
      this.schedule(Math.min(RETRY_DELAY_MS, this.expiresAt - this.env.now()));
      return false;
    }
    this.clear(definitive && reason !== "bootstrap");
    return false;
  }

  /**
   * 页面加载时恢复会话。没有「登录过」的标记时不发请求,直接算未登录 —— 除非 `force`
   * (需要登录的页面:标记可能被清过,而 cookie 还在)。已登录、正在恢复时都不重复做。
   */
  bootstrap(options: { force?: boolean } = {}): Promise<void> {
    const force = Boolean(options.force);
    if (this.snapshot.status === "authenticated") return Promise.resolve();
    if (this.booting) return this.booting;
    if (this.snapshot.status === "anonymous" && (!force || this.forcedOnce)) return Promise.resolve();
    if (!force && !this.env.hint?.get()) {
      this.publish("anonymous", null);
      return Promise.resolve();
    }
    if (force) this.forcedOnce = true;
    this.publish("loading", this.snapshot.user);
    this.booting = this.refresh("bootstrap")
      .then(() => undefined)
      .finally(() => {
        this.booting = null;
      });
    return this.booting;
  }

  // ── 请求 ──────────────────────────────────────────────────────────────

  private languageHeader(): Record<string, string> {
    return this.language ? { "Accept-Language": this.language } : {};
  }

  private send(path: string, options: RequestOptions, token: string | null): Promise<Response> {
    const { json, headers, body, ...rest } = options;
    const merged = new Headers(headers);
    if (!merged.has("Accept")) merged.set("Accept", "application/json");
    for (const [key, value] of Object.entries(this.languageHeader())) if (!merged.has(key)) merged.set(key, value);
    if (token) merged.set("Authorization", `Bearer ${token}`);
    let payload = body ?? null;
    if (json !== undefined) {
      merged.set("Content-Type", "application/json");
      payload = JSON.stringify(json);
    }
    return this.env.fetch(`${this.base}${path}`, { ...rest, headers: merged, body: payload, credentials: "same-origin" });
  }

  /**
   * 带上访问令牌发一个请求,返回原始 Response。
   *
   * 401 且这次确实带了令牌 → 刷新(单飞)→ 用新令牌重放**一次**。等刷新的这段时间里别的请求
   * 已经换好了令牌,就不再刷,直接重放。body 是字符串 / FormData / Blob,能发第二遍;
   * 流式 body 不在这里用。
   */
  async request(path: string, options: RequestOptions = {}): Promise<Response> {
    if (this.booting) await this.booting;
    if (this.token && this.env.now() >= this.expiresAt - REFRESH_LEEWAY_MS) await this.refresh("expiring");
    const used = this.token;
    const response = await this.send(path, options, used);
    if (response.status !== 401 || !used) return response;
    const renewed = this.token !== used && this.token !== null ? true : await this.refresh("unauthorized");
    if (!renewed || !this.token) return response;
    return this.send(path, options, this.token);
  }

  /** 带类型的请求:2xx 解析 JSON(204 给 undefined),否则抛 CommunityError。 */
  async fetchJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
    let response: Response;
    try {
      response = await this.request(path, options);
    } catch (error) {
      if (error instanceof CommunityError) throw error;
      throw networkError();
    }
    if (!response.ok) throw await errorFromResponse(response);
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    return (text ? localizeTree(JSON.parse(text), this.language) : undefined) as T;
  }

  // ── 登录与退出 ────────────────────────────────────────────────────────

  /** 发一个「登录」类请求(短信登录、注册、密码登录),成功就进入已登录并通告别的页。 */
  async login(path: string, payload: unknown): Promise<User> {
    let response: Response;
    try {
      response = await this.send(path, { method: "POST", json: payload }, null);
    } catch {
      throw networkError();
    }
    if (!response.ok) throw await errorFromResponse(response);
    const body = (await response.json()) as LoginResponse;
    this.apply(body, true);
    return body.user;
  }

  /** 资料改过之后换掉内存里的 user,别的页也跟着换。令牌不变。 */
  updateUser(user: User) {
    if (!this.token) return;
    this.publish("authenticated", user);
    this.env.channel?.postMessage({ type: "session", accessToken: this.token, expiresAt: this.expiresAt, user });
  }

  /**
   * 退出:吊销服务端的会话(清掉 cookie),本页清空,通告别的页。服务端那一步失败也照样在本地退出 ——
   * 用户点了「退出」,屏幕上就不该还是登录着的样子。
   */
  async logout(): Promise<void> {
    const token = this.token;
    try {
      await this.env.fetch(`${this.base}/auth/logout`, {
        method: "POST",
        credentials: "same-origin",
        headers: { ...REQUESTED_WITH, ...(token ? { Authorization: `Bearer ${token}` } : {}), ...this.languageHeader() },
      });
    } catch {
      // 断网时也在本地退出,见上。
    }
    this.clear(true);
  }

  /** 服务端吊销了当前会话(「设备与会话」里撤销了自己):本地跟着退出。 */
  forget() {
    this.clear(true);
  }

  dispose() {
    if (this.timer !== null) this.env.clearTimer(this.timer);
    this.timer = null;
    this.env.channel?.close?.();
  }
}

/** 浏览器里的默认环境。localStorage / BroadcastChannel 不可用(隐私模式、老浏览器)时各自降级为 null。 */
export function browserEnv(): SessionEnv {
  let channel: ChannelLike | null = null;
  try {
    channel = typeof BroadcastChannel === "function" ? (new BroadcastChannel(CHANNEL_NAME) as unknown as ChannelLike) : null;
  } catch {
    channel = null;
  }
  const hint: HintStore = {
    get() {
      try {
        return window.localStorage.getItem(HINT_KEY) === "1";
      } catch {
        return false;
      }
    },
    set(on) {
      try {
        if (on) window.localStorage.setItem(HINT_KEY, "1");
        else window.localStorage.removeItem(HINT_KEY);
      } catch {
        // 存不了就每次按未登录起步,需要登录的页面会强制试一次。
      }
    },
  };
  return {
    fetch: (input, init) => window.fetch(input, init),
    now: () => Date.now(),
    setTimer: (callback, ms) => window.setTimeout(callback, ms),
    clearTimer: (handle) => window.clearTimeout(handle as number),
    channel,
    hint,
    random: Math.random,
  };
}
