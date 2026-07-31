/**
 * pi 的 CredentialStore,实现在 Open Studio 后端之上。
 *
 * sidecar 是**每轮对话新起的短命进程**,而 OAuth 凭据会过期、刷新时还会轮换 —— 存在进程里
 * 等于每轮都要重新登录。所以存储归后端(库里的 provider_profiles.oauth_credential),这里只是
 * 一层代理。
 *
 * `read` 不走网络:凭据和 base_url / api_key 一样随回合帧发下来,读的就是那一份。
 *
 * `modify` 走网络,而且是 acquire → 改 → commit 三步,不是「GET 再 PUT」。原因是订阅制的
 * refresh token 多为一次性:换出新 access token 的同时旧 refresh 立刻作废。多个会话(对话页 /
 * 工作流 / 飞书)可以同时开工,各自一个 sidecar;两个同时刷新时,后手那次会让先手刚存好的凭据
 * 当场失效 —— 用户看到「刚登录就被登出」,偶发且难复现。租约把这段变成临界区,正好对上 pi 对
 * `modify` 的要求:「跨进程互斥」。
 */
import type { Credential, CredentialInfo, CredentialStore } from "@earendil-works/pi-ai";

import { log } from "./protocol.js";

/** acquire 撞上别人持锁时的重试。刷新本身是一次 HTTP,等待通常在一秒内结束。 */
const ACQUIRE_RETRIES = 3;
const ACQUIRE_RETRY_MS = 400;

interface LeaseResponse {
  lease: string;
  credential: Credential | null;
  version: number;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export class BackendCredentialStore implements CredentialStore {
  constructor(
    private readonly apiBase: string,
    private readonly token: string,
    private readonly profileId: string,
    /** 回合帧里带下来的当前凭据 —— read() 的来源,免去一次网络往返。 */
    private seeded: Credential | undefined,
  ) {}

  private async post(path: string, body: unknown): Promise<Response> {
    return fetch(`${this.apiBase}/api/agent/provider-credentials/${this.profileId}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async read(): Promise<Credential | undefined> {
    return this.seeded;
  }

  async list(): Promise<readonly CredentialInfo[]> {
    return this.seeded ? [{ providerId: this.profileId, type: this.seeded.type }] : [];
  }

  async modify(
    _providerId: string,
    fn: (current: Credential | undefined) => Promise<Credential | undefined>,
  ): Promise<Credential | undefined> {
    let lease: LeaseResponse | undefined;
    for (let attempt = 0; attempt <= ACQUIRE_RETRIES; attempt += 1) {
      const res = await this.post("/acquire", {});
      if (res.ok) {
        lease = (await res.json()) as LeaseResponse;
        break;
      }
      // 409 = 另一次刷新正在进行。它几秒内会结束,而且结束后库里就是新凭据,重试即可。
      if (res.status !== 409 || attempt === ACQUIRE_RETRIES) {
        throw new Error(`凭据加锁失败(${res.status}):${(await res.text()).slice(0, 200)}`);
      }
      await sleep(ACQUIRE_RETRY_MS * (attempt + 1));
    }
    if (!lease) throw new Error("凭据加锁失败:重试耗尽");

    let next: Credential | undefined;
    try {
      // 传库里的值而不是 seeded:别人刚刷新过的话,这里读到的才是有效的那份,
      // 用旧的去换只会拿到 invalid_grant。
      next = await fn(lease.credential ?? undefined);
    } catch (error) {
      // 刷新失败就立刻放手,不然下一轮对话要白等一个 TTL。
      await this.post("/release", { lease: lease.lease }).catch(() => undefined);
      throw error;
    }

    // pi 的契约:fn 返回 undefined 表示不改动。
    if (next === undefined) {
      await this.post("/release", { lease: lease.lease }).catch(() => undefined);
      return lease.credential ?? undefined;
    }

    const res = await this.post("/commit", { lease: lease.lease, credential: next });
    if (!res.ok) {
      // 409 = 租约超时被顶替,库里已是别人刷出来的新凭据。本轮内存里这份仍然可用,
      // 所以只记一笔往下走,而不是让整轮对话失败。
      log(`credential commit rejected (${res.status}); 本轮继续使用内存中的凭据`);
    }
    this.seeded = next;
    return next;
  }

  async delete(): Promise<void> {
    // 登出是应用侧的动作(设置页),不该由跑对话的 sidecar 发起 —— 一次刷新失败就把用户
    // 的订阅登录清掉,代价远大于收益。
    throw new Error("sidecar 不负责登出;请在设置里解除该供应商的登录");
  }
}
