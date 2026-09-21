/**
 * pi 的 CredentialStore,实现在 Mosael 后端之上。
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

/**
 * acquire 撞上别人持锁时的重试。
 *
 * **注意这里的等待远不止这几个 ms**:后端的 `acquire_lease` 自己就先阻塞了
 * `ACQUIRE_TIMEOUT_SECONDS`(见下方常量)才返回 409。所以收到一个 409 意味着**已经等过 20 秒**,
 * 重试 3 次 = 这一轮对话在凭据上最多站住约 80 秒。早先这里的注释写的是「它几秒内会结束」,
 * 两侧对同一段等待的理解差了三十倍。两个预算见 contracts/shared-constants.json。
 */
const ACQUIRE_RETRIES = 3;
const ACQUIRE_RETRY_MS = 400;

/**
 * 后端租约的 TTL 和 acquire 等待上限。**两侧都要认,而谁也不拥有** ——
 * 见 contracts/shared-constants.json,那里写了各自猜错会发生什么。
 */
export const CREDENTIAL_LEASE_TTL_SECONDS = 30;
export const CREDENTIAL_ACQUIRE_TIMEOUT_SECONDS = 20;

/** 续租间隔:TTL 的三分之一 —— 丢一两次续租也还在期限内。从 TTL 推出来,不另写一个数。 */
const RENEW_EVERY_MS = (CREDENTIAL_LEASE_TTL_SECONDS / 3) * 1000;

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
    // 刷新期间一直续租 —— TTL 用来发现死掉的持有者,不该用来罚慢的那个。
    const renewing = setInterval(() => {
      void this.post("/renew", { lease: lease.lease }).catch(() => undefined);
    }, RENEW_EVERY_MS);
    // 这个进程的存活不该被一个定时器吊着(sidecar 是回合级进程,收尾时要能退干净)。
    renewing.unref?.();
    try {
      // 传库里的值而不是 seeded:别人刚刷新过的话,这里读到的才是有效的那份,
      // 用旧的去换只会拿到 invalid_grant。
      next = await fn(lease.credential ?? undefined);
    } catch (error) {
      // 刷新失败就立刻放手,不然下一轮对话要白等一个 TTL。
      clearInterval(renewing);
      await this.post("/release", { lease: lease.lease }).catch(() => undefined);
      throw error;
    }
    clearInterval(renewing);

    // pi 的契约:fn 返回 undefined 表示不改动。
    if (next === undefined) {
      await this.post("/release", { lease: lease.lease }).catch(() => undefined);
      return lease.credential ?? undefined;
    }

    // `base_version` 带回去:后端据此判断「我拿到租约之后有没有别人写过」。没人写过时它会
    // **照写**,因为手上这份是刚换出来的唯一有效凭据 —— 丢掉它下一轮就是 invalid_grant。
    const res = await this.post("/commit", {
      lease: lease.lease,
      credential: next,
      base_version: lease.version,
    });
    if (!res.ok) {
      // 409 有**两种**原因,而它们要的处置正好相反 —— 早先这里把两种合并成一种,只往 stderr
      // 写一行:对「被顶替」是对的(别人刚写了新凭据,我这份该丢),对「只是我慢了」是
      // 破坏性的(丢掉的是唯一有效的那一份)。现在后端把第二种直接写进去了,所以能走到这里的
      // 只剩 superseded;真出现别的 code,要看得见而不是被一行日志吃掉。
      const code = await this.leaseCode(res);
      if (code === "superseded") {
        log("credential commit superseded:库里已是别人刷出来的新凭据,本轮继续使用内存中的这份");
      } else {
        log(`credential commit rejected (${res.status}, code=${code ?? "?"});本轮继续使用内存中的凭据`);
      }
    }
    this.seeded = next;
    return next;
  }

  /** 后端在 409 的 detail 里带的机器可读原因。读不出来返回 undefined。 */
  private async leaseCode(res: Response): Promise<string | undefined> {
    try {
      const body = (await res.json()) as { detail?: { code?: string } | string };
      return typeof body.detail === "object" ? body.detail?.code : undefined;
    } catch {
      return undefined;
    }
  }

  async delete(): Promise<void> {
    // 登出是应用侧的动作(设置页),不该由跑对话的 sidecar 发起 —— 一次刷新失败就把用户
    // 的订阅登录清掉,代价远大于收益。
    throw new Error("sidecar 不负责登出;请在设置里解除该供应商的登录");
  }
}
